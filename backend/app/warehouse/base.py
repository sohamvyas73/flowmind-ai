"""Warehouse adapters: run SQL in the customer's own engine (ClickHouse, PostgreSQL/Redshift, Snowflake, BigQuery,
Databricks) and bring back only what is asked for.

Two rules hold for every adapter:
* Anything that reads goes through `query()`, which refuses everything except a single, side-effect-free SELECT.
* Anything that writes goes through `write_table()`, which needs a read-write connection and only runs statements
  FlowMind generated itself (never user-typed SQL).
"""
import asyncio
import datetime as dt
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import sqlglot
from sqlglot import exp

SAMPLE_ROWS = 100
MAX_PULL_ROWS = 1_000_000


class WarehouseError(Exception):
    """A user-facing warehouse problem (unreachable, refused, bad SQL, unsupported)."""


@dataclass
class Result:
    columns: List[Dict[str, str]]                 # [{"name", "type"}] with DuckDB-style type names
    rows: List[List[Any]] = field(default_factory=list)
    truncated: bool = False


# ── canonical types ─────────────────────────────────────────────────────────────

def canonical_type(native: str, dialect: Optional[str] = None) -> str:
    """Map a warehouse's type name to the DuckDB-style names the data nodes understand (VARCHAR, BIGINT, DOUBLE…)."""
    t = (native or "").strip()
    prev = None
    while prev != t:                              # ClickHouse wrappers
        prev = t
        m = re.match(r"^(Nullable|LowCardinality)\((.*)\)$", t)
        if m:
            t = m.group(2)
    u = t.upper()
    if re.match(r"^(U?INT\d*|BIGINT|SMALLINT|TINYINT|INTEGER|INT\d?|NUMBER\(\d+,\s*0\)|LONG|SHORT|BYTE|SERIAL|BIGSERIAL)$", u):
        return "BIGINT"
    if re.match(r"^(FLOAT\d*|DOUBLE( PRECISION)?|REAL|FLOAT64|FIXED)$", u):
        return "DOUBLE"
    m = re.match(r"^(DECIMAL|NUMERIC|NUMBER|BIGNUMERIC)\((\d+),\s*(\d+)\)$", u) or re.match(r"^DECIMAL\d*\((\d+)\)$", u)
    if m and len(m.groups()) == 3:
        return "BIGINT" if m.group(3) == "0" else f"DECIMAL({m.group(2)},{m.group(3)})"
    if u in ("DECIMAL", "NUMERIC", "NUMBER", "BIGNUMERIC"):
        return "DOUBLE"
    if re.match(r"^DECIMAL(32|64|128|256)\(", u):
        return "DOUBLE"
    if u in ("BOOL", "BOOLEAN"):
        return "BOOLEAN"
    if u.startswith("DATE") and not u.startswith("DATETIME") and not u.startswith("DATE_TIME"):
        return "DATE"
    if u.startswith(("TIMESTAMP", "DATETIME")):
        return "TIMESTAMP"
    if re.match(r"^(STRING|TEXT|CHAR.*|VARCHAR.*|CHARACTER.*|FIXEDSTRING.*|UUID|NAME|BPCHAR.*)$", u):
        return "VARCHAR"
    return "VARCHAR"


def _num(v: Any, kind: str) -> Any:
    if v is None or v == "":
        return None
    if kind == "BIGINT":
        return int(float(v)) if isinstance(v, str) and ("." in v or "e" in v.lower()) else int(v)
    return float(v)


def coerce(value: Any, ctype: str, *, flavour: str = "") -> Any:
    """Warehouse REST APIs return everything as text; turn it back into real values."""
    if value is None:
        return None
    if ctype == "BIGINT" or ctype == "DOUBLE" or ctype.startswith("DECIMAL"):
        try:
            return _num(value, "BIGINT" if ctype == "BIGINT" else "DOUBLE")
        except (TypeError, ValueError):
            return None
    if ctype == "BOOLEAN":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "t", "yes")
    if ctype == "DATE":
        if isinstance(value, (dt.date, dt.datetime)):
            return value if not isinstance(value, dt.datetime) else value.date()
        s = str(value)
        if re.fullmatch(r"-?\d+", s) and flavour == "snowflake":                 # Snowflake: days since the epoch
            return dt.date(1970, 1, 1) + dt.timedelta(days=int(s))
        try:
            return dt.date.fromisoformat(s[:10])
        except ValueError:
            return None
    if ctype == "TIMESTAMP":
        if isinstance(value, dt.datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        s = str(value)
        if re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", s) and flavour in ("snowflake", "bigquery"):
            return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=float(s))      # epoch seconds
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=None)
        except ValueError:
            return None
    return value if isinstance(value, str) else str(value)


# ── identifiers ─────────────────────────────────────────────────────────────────

_SIMPLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str, dialect: str) -> str:
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)


def table_ref(dialect: str, *parts: str) -> str:
    """schema.table (or catalog.schema.table), quoting only what needs it so Snowflake keeps its case-insensitivity."""
    out = []
    for p in parts:
        if not p:
            continue
        if "\x00" in p or "\n" in p or len(p) > 255:
            raise WarehouseError("Invalid table name")
        out.append(p if _SIMPLE.match(p) else quote_ident(p, dialect))
    if not out:
        raise WarehouseError("Choose a table")
    return ".".join(out)


# ── read-only guard ─────────────────────────────────────────────────────────────

_FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Merge, exp.Command,
                    exp.Copy, exp.TruncateTable, exp.Set, exp.Use, exp.Transaction, exp.Commit, exp.Rollback,
                    exp.Grant, exp.LoadData, exp.Pragma)
# table functions / functions that read files, call other servers or have side effects
_FORBIDDEN_FUNCS = {
    "url", "urlcluster", "file", "filecluster", "s3", "s3cluster", "hdfs", "hdfscluster", "remote", "remotesecure",
    "mysql", "postgresql", "mongodb", "jdbc", "odbc", "sqlite", "redis", "azureblobstorage", "gcs", "iceberg", "deltalake",
    "hudi", "input", "executable", "cluster", "clusterallreplicas", "dictget", "dblink", "dblink_exec", "pg_read_file",
    "pg_read_binary_file", "pg_ls_dir", "pg_sleep", "pg_terminate_backend", "pg_cancel_backend", "lo_import", "lo_export",
    "copy", "read_csv", "read_parquet", "read_json", "read_text", "system", "sleep", "sleepeachrow", "get_object", "http_get",
    "http_post", "external_function", "system$wait", "system$cancel_query", "system$abort_session", "load_file",
}


def assert_select_only(sql: str, dialect: str) -> str:
    """Return the cleaned statement, or raise. One statement, a SELECT/UNION, no side effects, no file/network functions."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise WarehouseError("The query is empty")
    try:
        stmts = [s for s in sqlglot.parse(text, read=dialect) if s is not None]
    except sqlglot.errors.ParseError as e:
        raise WarehouseError(f"Could not read this SQL for {dialect}: {str(e).splitlines()[0][:200]}")
    if len(stmts) != 1:
        raise WarehouseError("Only one statement is allowed")
    tree = stmts[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery, exp.With)) and not isinstance(tree, exp.SetOperation):
        raise WarehouseError("Only SELECT queries are allowed here. To write data, use the Save to warehouse node.")
    for n in tree.walk():
        node = n[0] if isinstance(n, tuple) else n
        if isinstance(node, _FORBIDDEN_NODES):
            raise WarehouseError("Only SELECT queries are allowed here. To write data, use the Save to warehouse node.")
        if isinstance(node, exp.Select) and node.args.get("into"):
            raise WarehouseError("SELECT … INTO is not allowed")
        fname = None
        if isinstance(node, exp.Anonymous):
            fname = str(node.this)
        elif isinstance(node, exp.Func):
            fname = node.sql_name() if hasattr(node, "sql_name") else None
        elif isinstance(node, exp.Table) and isinstance(node.this, (exp.Anonymous, exp.Func)):
            fname = str(getattr(node.this, "this", "") or node.this.sql_name())
        if fname and fname.lower().split(".")[-1] in _FORBIDDEN_FUNCS:
            raise WarehouseError(f"The function {fname}() is not allowed (it reads files, calls other servers or has side effects)")
        if isinstance(node, exp.Table) and isinstance(node.this, (exp.Anonymous, exp.Func)):
            raise WarehouseError("Table functions are not allowed; query a table or view by name")
    return text


# ── the adapter contract ────────────────────────────────────────────────────────

class Warehouse(ABC):
    type: str = ""
    dialect: str = ""
    label: str = ""
    supports_insert = False

    def __init__(self, config: Dict[str, Any], access_mode: str, allow_hosts: Iterable[str]):
        self.config = config
        self.access_mode = access_mode
        self.allow_hosts = list(allow_hosts)

    # to implement ---------------------------------------------------------------
    @abstractmethod
    async def _run(self, sql: str, *, limit: Optional[int], write: bool) -> Result: ...

    @abstractmethod
    async def tables(self) -> List[Dict[str, str]]: ...

    @abstractmethod
    async def test(self) -> Dict[str, Any]: ...

    def default_schema(self) -> str:
        return ""

    # shared ----------------------------------------------------------------------
    async def query(self, sql: str, *, limit: Optional[int] = None) -> Result:
        clean = assert_select_only(sql, self.dialect)
        return await self._run(clean, limit=limit, write=False)

    async def describe(self, sql: str) -> List[Dict[str, str]]:
        """Column names and types of a SELECT, without reading data."""
        res = await self.query(f"SELECT * FROM ({sql}) AS fm_t WHERE 1 = 0", limit=0)
        return res.columns

    async def sample(self, sql: str, n: int = SAMPLE_ROWS) -> Result:
        return await self.query(f"SELECT * FROM ({sql}) AS fm_t LIMIT {int(n)}", limit=n)

    async def count(self, sql: str) -> int:
        res = await self.query(f"SELECT count(*) AS n FROM ({sql}) AS fm_t", limit=1)
        return int(res.rows[0][0])

    async def pull(self, sql: str, limit: int) -> Result:
        return await self.query(f"SELECT * FROM ({sql}) AS fm_t LIMIT {int(limit)}", limit=limit)

    def _need_write(self) -> None:
        if self.access_mode != "read_write":
            raise WarehouseError("This connection is read-only. Set its access to 'Read & write' to let FlowMind create tables.")

    def create_table_as_statements(self, target: str, select_sql: str, mode: str) -> List[str]:
        if mode == "replace":
            return [f"DROP TABLE IF EXISTS {target}", f"CREATE TABLE {target} AS {select_sql}"]
        if mode == "append":
            return [f"INSERT INTO {target} {select_sql}"]
        return [f"CREATE TABLE {target} AS {select_sql}"]                       # 'create': fails if it exists

    async def write_table(self, target: str, select_sql: str, mode: str = "create") -> None:
        self._need_write()
        if mode not in ("create", "replace", "append"):
            raise WarehouseError("Mode must be create, replace or append")
        select = assert_select_only(select_sql, self.dialect)
        for stmt in self.create_table_as_statements(target, select, mode):
            await self._run(stmt, limit=None, write=True)

    async def insert_rows(self, target: str, columns: List[Dict[str, str]], rows: Sequence[Sequence[Any]], mode: str) -> None:
        raise WarehouseError(f"Writing a FlowMind table into {self.label} is not supported yet. "
                             "Use Save to warehouse on a table that already lives in the warehouse.")


# ── rows → Parquet ──────────────────────────────────────────────────────────────

def _arrow_kind(values: List[Any]) -> str:
    vs = [v for v in values if v is not None]
    if not vs:
        return "string"
    if all(isinstance(v, bool) for v in vs):
        return "bool"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vs):
        return "int64"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in vs):
        return "float64"
    if all(isinstance(v, dt.datetime) for v in vs):
        return "timestamp"
    if all(isinstance(v, dt.date) and not isinstance(v, dt.datetime) for v in vs):
        return "date32"
    return "string"


def rows_to_parquet(result: Result, out_path: str) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    """Write rows to Parquet. Returns (columns with DuckDB types, first rows as dicts)."""
    import os
    import pyarrow as pa
    import pyarrow.parquet as pq

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    arrays, fields, cols = [], [], []
    for i, c in enumerate(result.columns):
        vals = [r[i] for r in result.rows]
        kind = _arrow_kind(vals)
        if kind == "float64":
            vals = [None if v is None else float(v) for v in vals]
        if kind == "string":
            vals = [None if v is None else (v if isinstance(v, str) else str(v)) for v in vals]
        t = {"bool": pa.bool_(), "int64": pa.int64(), "float64": pa.float64(), "timestamp": pa.timestamp("us"),
             "date32": pa.date32(), "string": pa.string()}[kind]
        arrays.append(pa.array(vals, type=t))
        fields.append(pa.field(c["name"], t))
        duck = {"bool": "BOOLEAN", "int64": "BIGINT", "float64": "DOUBLE", "timestamp": "TIMESTAMP", "date32": "DATE", "string": "VARCHAR"}[kind]
        cols.append({"name": c["name"], "type": duck})
    pq.write_table(pa.Table.from_arrays(arrays, schema=pa.schema(fields)), out_path)
    sample = [dict(zip((c["name"] for c in cols), r)) for r in result.rows[:SAMPLE_ROWS]]
    return cols, sample


def to_rows(result: Result) -> List[Dict[str, Any]]:
    names = [c["name"] for c in result.columns]
    return [dict(zip(names, r)) for r in result.rows]
