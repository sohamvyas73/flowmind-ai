"""Pushdown: run data nodes *inside* the customer's warehouse and leave the data there.

A Load Data node set to "leave the data in my warehouse" does not copy rows. It produces a *relation*: the SELECT that
defines the table, in the warehouse's own SQL dialect. Each following Clean / Combine / Summarise / SQL node compiles its
settings to SQL (the same compilers the hosted engine uses), translates it to the warehouse's dialect and wraps it around
the upstream relation. Only a small PII-masked sample and the schema come back to FlowMind. A Pull node brings a table into
FlowMind when something that needs the actual rows (AI, ML, quality checks) comes next; Save to warehouse writes a result
back as a table.
"""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pyarrow.parquet as pq
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify

from app.core.config import settings
from app.core.database import SessionLocal
from app.data.dataset import LineageEdge
from app.models.connection import Connection
from app.services import data_nodes as dn
from app.services import dataset_service as ds
from app.storage.local import storage, tenant_key
from app.warehouse.base import (MAX_PULL_ROWS, Result, Warehouse, WarehouseError, quote_ident, rows_to_parquet,
                                table_ref, to_rows)
from app.warehouse.registry import is_warehouse, open_warehouse

PUSHDOWN_KINDS = {"clean", "combine", "summarise", "sql"}
MAX_WRITE_ROWS = 200_000
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast", "system", "sys", "mysql", "performance_schema", "snowflake",
                   "pg_internal", "pg_automv"}

# ── dialect-specific pieces ─────────────────────────────────────────────────────

# lowercase hex SHA-256 of a text expression (DuckDB's sha256() returns lowercase hex, so results match across engines)
_HASH = {
    "clickhouse": "lower(hex(SHA256(__x__)))",
    "postgres": "encode(sha256(convert_to(__x__, 'UTF8')), 'hex')",
    "redshift": "sha2(__x__, 256)",
    "snowflake": "SHA2(__x__, 256)",
    "bigquery": "LOWER(TO_HEX(SHA256(__x__)))",
    "databricks": "sha2(__x__, 256)",
}


def _rename_tables(tree: exp.Expression, mapping: Dict[str, str]) -> exp.Expression:
    """Point table references at uniquely named relations, keeping the original name as the alias.

    (Re-using the name `input` for every step breaks engines that treat `WITH input AS (… input …)` as recursion.)"""
    def swap(node):
        if isinstance(node, exp.Table) and not node.args.get("db") and node.name in mapping:
            alias = node.alias or node.name
            new = node.copy()
            new.set("this", exp.to_identifier(mapping[node.name], quoted=True))
            new.set("alias", exp.TableAlias(this=exp.to_identifier(alias, quoted=True)))
            return new
        return node
    return tree.transform(swap)


def rewrite_user_sql(user_sql: str, mapping: Dict[str, str], dialect: str) -> str:
    try:
        tree = sqlglot.parse_one(user_sql, read=dialect)
        return _rename_tables(tree, mapping).sql(dialect=dialect)
    except sqlglot.errors.SqlglotError as e:
        raise dn.DataNodeError(f"Could not read this SQL for {dialect}: {str(e).splitlines()[0][:200]}")


def transpile(duck_sql: str, schemas: Dict[str, List[Dict[str, Any]]], dialect: str, rename: Optional[Dict[str, str]] = None) -> str:
    """DuckDB-flavoured SELECT → the warehouse's dialect, with every `*` expanded using the known columns."""
    try:
        tree = sqlglot.parse_one(duck_sql, read="duckdb")
        schema = {alias: {c["name"]: c.get("type") or "VARCHAR" for c in cols} for alias, cols in schemas.items()}
        tree = qualify(tree, schema=schema, dialect="duckdb", quote_identifiers=True, validate_qualify_columns=False)

        def swap(node):
            if isinstance(node, exp.Anonymous) and str(node.this).lower() == "fm_sha256":
                tpl = sqlglot.parse_one(_HASH[dialect], read=dialect)
                arg = node.expressions[0]
                return tpl.transform(lambda n: arg.copy() if isinstance(n, exp.Column) and n.name == "__x__" else n)
            return node
        tree = tree.transform(swap)
        if rename:
            tree = _rename_tables(tree, rename)
        return tree.sql(dialect=dialect, identify=True)
    except dn.DataNodeError:
        raise
    except sqlglot.errors.SqlglotError as e:
        raise dn.DataNodeError(f"This step cannot be translated to {dialect}: {str(e).splitlines()[0][:200]}")


def with_relations(relations: Dict[str, str], body_sql: str, dialect: str) -> str:
    """`WITH "input" AS (<upstream SELECT>), … <body>`, merging with a WITH the body may already start with."""
    ctes = ", ".join(f"{quote_ident(name, dialect)} AS ({sql})" for name, sql in relations.items())
    body = body_sql.strip()
    rest = re.sub(r"(?is)^with\s+", "", body, count=1)
    if rest != body:
        return f"WITH {ctes}, {rest}"
    return f"WITH {ctes}\n{body}"


def lineage_identity(wtype: str, config: Dict[str, Any], schema: str, table: str) -> Tuple[str, str]:
    """OpenLineage (namespace, name) for a warehouse table, following the OpenLineage naming conventions."""
    if wtype == "clickhouse":
        host = re.sub(r"^https?://", "", config.get("url", "")).rstrip("/")
        return f"clickhouse://{host}", f"{schema or config.get('database') or 'default'}.{table}"
    if wtype in ("postgres", "redshift"):
        return f"{wtype}://{config.get('host')}:{config.get('port', 5432)}", f"{config.get('database')}.{schema or 'public'}.{table}"
    if wtype == "snowflake":
        return f"snowflake://{config.get('account')}", ".".join(x for x in (config.get("database"), schema or config.get("schema"), table) if x)
    if wtype == "bigquery":
        return "bigquery", ".".join(x for x in (config.get("project"), schema or config.get("dataset"), table) if x)
    if wtype == "databricks":
        return f"databricks://{config.get('host')}", ".".join(x for x in (config.get("catalog"), schema or config.get("schema"), table) if x)
    return f"{wtype}://", f"{schema}.{table}"


# ── connections ─────────────────────────────────────────────────────────────────

class Conn:
    def __init__(self, cid, name, type_, config, mode, allow):
        self.id, self.name, self.type, self.config, self.mode, self.allow = cid, name, type_, config, mode, allow

    def warehouse(self, *, write: bool = False) -> Warehouse:
        return open_warehouse(self.type, self.config, "read_write" if write else self.mode, self.allow)


def load_connection(user_id, connection_id: Any) -> Conn:
    if not connection_id:
        raise dn.DataNodeError("Choose a warehouse connection. Nothing is chosen for you — add one on the Connections page.")
    with SessionLocal() as db:
        try:
            c = db.query(Connection).filter(Connection.id == uuid.UUID(str(connection_id)), Connection.user_id == user_id).first()
        except ValueError:
            c = None
        if c is None:
            raise dn.DataNodeError("That connection no longer exists. Pick one of your saved connections.")
        if not is_warehouse(c.type):
            raise dn.DataNodeError(f"'{c.name}' is a {c.type} connection, not a warehouse")
        return Conn(c.id, c.name, c.type, json.loads(c.config or "{}"), c.access_mode, list(c.host_allowlist or []))


def _safe(fn):
    """Warehouse errors become node errors."""
    async def wrapper(*a, **kw):
        try:
            return await fn(*a, **kw)
        except WarehouseError as e:
            raise dn.DataNodeError(str(e))
    return wrapper


# ── results ─────────────────────────────────────────────────────────────────────

def _relation_result(context: Dict[str, Any], conn: Conn, sql: str, shown_sql: str, sample: Result, *, label: str,
                     lineage: List[LineageEdge], node_id: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cols = [{"name": c["name"], "type": c["type"]} for c in sample.columns]
    ref = ds.make_ref(cols, to_rows(sample), row_count=None, size_bytes=None, produced_by=node_id, lineage=lineage,
                      path=f"pushdown:{conn.name}")
    ref.location.target = "pushdown"
    ref.location.connection_id = conn.id
    out: Dict[str, Any] = {
        "pushdown": {"connection_id": str(conn.id), "connection_name": conn.name, "type": conn.type, "sql": sql},
        "dataset": ref.model_dump(mode="json"),
        "row_count": None,
        "columns": [c["name"] for c in cols],
        "sql": shown_sql,
        "runs_in": conn.name,
        "dry_run": bool(context.get("_dry_run")),
        "_usage": {"scanned_bytes": 0, "compute_s": 0, "scanned_rows": 0},
        "timestamp": datetime.utcnow().isoformat(),
    }
    out.update(extra or {})
    return out


def _canon(name: Any, cols: List[Dict[str, Any]]) -> Any:
    """Match a typed column name to the warehouse's real spelling, ignoring case (Snowflake reports REGION, people type region)."""
    if not isinstance(name, str) or name == "*":
        return name
    names = [c["name"] for c in cols]
    if name in names:
        return name
    hits = [n for n in names if n.lower() == name.lower()]
    return hits[0] if len(hits) == 1 else name


def align_columns(kind: str, cfg: Dict[str, Any], cols: List[Dict[str, Any]], right_cols: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Copy of a node's settings with every column name spelled the way the warehouse spells it."""
    c = json.loads(json.dumps(cfg))
    fix = lambda v: _canon(v, cols)
    if kind == "clean":
        for k in ("trimText", "dropMissing", "keepColumns"):
            c[k] = [fix(x) for x in (c.get(k) or [])]
        if c.get("textCase"):
            c["textCase"]["columns"] = [fix(x) for x in (c["textCase"].get("columns") or [])]
        for f in c.get("fillMissing") or []:
            f["column"] = fix(f.get("column"))
        for p_ in c.get("protect") or []:
            p_["column"] = fix(p_.get("column"))
        for r in c.get("rename") or []:
            r["from"] = fix(r.get("from"))
    elif kind == "summarise":
        c["groupBy"] = [fix(x) for x in (c.get("groupBy") or [])]
        for a in c.get("aggregations") or []:
            a["column"] = fix(a.get("column"))
    elif kind == "combine":
        for k in c.get("keys") or []:
            k["left"] = fix(k.get("left"))
            k["right"] = _canon(k.get("right"), right_cols or [])
    return c


def pushdown_upstreams(ups: List[dn.Upstream]) -> bool:
    flags = [bool(u.result.get("pushdown")) for u in ups]
    if any(flags) and not all(flags):
        raise dn.DataNodeError("These inputs live in different places (one in your warehouse, one inside FlowMind). "
                               "Use a Pull node to bring the warehouse table in, or Save to warehouse to put the other one there.")
    return any(flags)


def _same_conn(ups: List[dn.Upstream]) -> str:
    ids = {u.result["pushdown"]["connection_id"] for u in ups}
    if len(ids) > 1:
        raise dn.DataNodeError("Both inputs must come from the same warehouse connection to be combined there.")
    return ids.pop()


# ── Load Data (warehouse source) ────────────────────────────────────────────────

@_safe
async def load_from_warehouse(node_data: Dict[str, Any], context: Dict[str, Any], conn: Conn) -> Dict[str, Any]:
    user_id = dn._user_id(context)
    label = node_data.get("label") or "Load Data"
    run_on = node_data.get("runOn")
    if run_on not in ("warehouse", "flowmind"):
        raise dn.DataNodeError("Choose where this runs: 'In my warehouse' (data stays there) or 'Copy into FlowMind'.")
    wh = conn.warehouse()
    table = (node_data.get("table") or "").strip()
    if not table:
        raise dn.DataNodeError("Choose a table to load")
    schema = (node_data.get("schema") or "").strip() or wh.default_schema()
    cols = [c for c in (node_data.get("columns") or []) if isinstance(c, str) and c.strip()]
    # simple names stay unquoted so the warehouse applies its own case rules (Snowflake: region → REGION)
    select = ", ".join(c if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", c.strip()) else quote_ident(c.strip(), wh.dialect) for c in cols) if cols else "*"
    cap = settings.DRY_RUN_ROWS if context.get("_dry_run") else (settings.MAX_LOAD_ROWS if run_on == "flowmind" else None)
    try:
        want = int(node_data.get("maxRows") or 0) or None
    except (TypeError, ValueError):
        raise dn.DataNodeError("Max rows must be a number")
    limit = min(x for x in (cap, want) if x) if (cap or want) else None
    rel = f"SELECT {select} FROM {table_ref(wh.dialect, schema, table)}" + (f" LIMIT {int(limit)}" if limit else "")
    ns, nm = lineage_identity(conn.type, conn.config, schema, table)
    edge = LineageEdge(source=f"connection:{conn.name}/{schema}.{table}", operation="read", namespace=ns, name=nm)
    node_id = context.get("current_node_id", "")

    if run_on == "warehouse":
        sample = await wh.sample(rel)
        return _relation_result(context, conn, rel, rel, sample, label=label, lineage=[edge], node_id=node_id)

    # copy into FlowMind compute
    res = await wh.pull(rel, int(limit or settings.MAX_LOAD_ROWS))
    return await _store_pulled(context, res, label=label, edge=edge, sql=f"-- copied {len(res.rows):,} rows from {conn.name}: {schema}.{table}")


async def _store_pulled(context: Dict[str, Any], res: Result, *, label: str, edge: LineageEdge, sql: str) -> Dict[str, Any]:
    user_id = dn._user_id(context)
    ds_id = uuid.uuid4()
    key = tenant_key(user_id, "datasets", f"{ds_id}.parquet")

    def _quota():
        with SessionLocal() as db:
            ds.check_quota(db, user_id)
    if not context.get("_dry_run"):
        await asyncio.to_thread(_quota)
    cols, sample = await asyncio.to_thread(rows_to_parquet, res, storage.path_for(key))
    return await dn._register(
        context, ds_id=ds_id, key=key, label=label, sql=sql, columns=cols, sample=sample, row_count=len(res.rows),
        out_bytes=storage.size(key), lineage=[edge], usage={"compute_s": 0, "scanned_bytes": storage.size(key), "scanned_rows": len(res.rows)},
        extra={"truncated": res.truncated} if res.truncated else None, node_id=context.get("current_node_id", ""))


# ── Clean / Combine / Summarise / SQL ───────────────────────────────────────────

@_safe
async def run_step(kind: str, node_data: Dict[str, Any], ups: List[dn.Upstream], context: Dict[str, Any]) -> Dict[str, Any]:
    if kind not in PUSHDOWN_KINDS:
        raise dn.DataNodeError("This node cannot run inside the warehouse")
    user_id = dn._user_id(context)
    conn = await asyncio.to_thread(load_connection, user_id, _same_conn(ups))
    wh = conn.warehouse()
    d = wh.dialect
    label = node_data.get("label") or kind.capitalize()
    node_id = context.get("current_node_id", "")

    def uniq(alias: str) -> str:
        return f"fm_{uuid.uuid4().hex[:8]}_{alias}"

    if kind == "combine":
        if len(ups) < 2:
            raise dn.DataNodeError("Combine needs two inputs: connect two data nodes to it (first = left table, second = right)")
        if node_data.get("swap"):
            ups = [ups[1], ups[0]] + ups[2:]
        left, right = ups[0], ups[1]
        duck = dn.compile_combine(align_columns("combine", node_data, left.columns, right.columns), left.columns, right.columns)
        names = {"input": uniq("input"), "input2": uniq("input2")}
        body = transpile(duck, {"input": left.columns, "input2": right.columns}, d, rename=names)
        rels = {names["input"]: left.result["pushdown"]["sql"], names["input2"]: right.result["pushdown"]["sql"]}
        used, shown = [left, right], body
    elif kind == "sql":
        user_sql = (node_data.get("query") or "").strip().rstrip(";")
        if not user_sql:
            raise dn.DataNodeError(f"Write a SQL query in {wh.label}'s own SQL, e.g. SELECT * FROM input LIMIT 10")
        names, source_sql = {}, {}
        for i, u in enumerate(ups):
            nm = "input" if i == 0 else f"input{i + 1}"
            names[nm], source_sql[nm] = uniq(nm), u.result["pushdown"]["sql"]
        for u in ups:
            sl = dn.slug(u.label)
            if sl and sl not in names:
                names[sl], source_sql[sl] = uniq(sl), u.result["pushdown"]["sql"]
        body = rewrite_user_sql(user_sql, names, d)
        rels = {names[k]: source_sql[k] for k in names}
        used, shown = ups, user_sql
    else:
        up = ups[0]
        names = {"input": uniq("input")}
        if kind == "clean":
            duck = dn.compile_clean(align_columns("clean", node_data, up.columns), up.columns, hash_fn=lambda x: f"fm_sha256({x})")
        else:
            duck = dn.compile_summarise(align_columns("summarise", node_data, up.columns), up.columns)
        body = transpile(duck, {"input": up.columns}, d, rename=names)
        rels, used, shown = {names["input"]: up.result["pushdown"]["sql"]}, [up], body

    full = with_relations(rels, body, d)
    sample = await wh.sample(full)
    lineage = [LineageEdge(source=f"pushdown:{u.label}", operation=kind) for u in used]
    # carry the warehouse tables this relation ultimately reads, so lineage still names the real sources
    for u in used:
        lineage += [LineageEdge(**e) for e in (u.result.get("dataset", {}).get("lineage") or []) if e.get("namespace")]
    return _relation_result(context, conn, full, shown, sample, label=label, lineage=lineage, node_id=node_id,
                            extra={"tables": list(names)} if kind == "sql" else None)


# ── Pull (bring into FlowMind) ──────────────────────────────────────────────────

@dn._guard
async def run_pull(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = dn._user_id(context)
    ups = dn._upstreams(context)
    if not ups:
        raise dn.DataNodeError("Pull needs a table from your warehouse: connect a Load Data (in my warehouse) or another pushdown node")
    if not ups[0].result.get("pushdown"):
        raise dn.DataNodeError("This table is already inside FlowMind. Pull is only for tables that live in your warehouse.")
    up = ups[0]
    conn = await asyncio.to_thread(load_connection, user_id, up.result["pushdown"]["connection_id"])
    try:
        want = int(node_data.get("maxRows") or settings.MAX_LOAD_ROWS)
    except (TypeError, ValueError):
        raise dn.DataNodeError("Max rows must be a number")
    cap = settings.DRY_RUN_ROWS if context.get("_dry_run") else min(MAX_PULL_ROWS, settings.MAX_LOAD_ROWS)
    limit = max(1, min(want, cap))
    try:
        res = await conn.warehouse().pull(up.result["pushdown"]["sql"], limit)
    except WarehouseError as e:
        raise dn.DataNodeError(str(e))
    edges = [LineageEdge(**e) for e in (up.result.get("dataset", {}).get("lineage") or [])] or [LineageEdge(source=f"pushdown:{up.label}", operation="pull")]
    out = await _store_pulled(context, res, label=node_data.get("label") or "Pull", edge=edges[0],
                              sql=f"-- pulled {len(res.rows):,} rows from {conn.name}")
    if res.truncated:
        out["note"] = f"Stopped at {limit:,} rows (the limit on this node). Filter or summarise in the warehouse first to bring in less."
    return out


# ── Save to warehouse ───────────────────────────────────────────────────────────

def _check_target(conn: Conn, schema: str, table: str, wh: Warehouse) -> None:
    if not _IDENT.match(table):
        raise dn.DataNodeError("Table name: letters, numbers and underscores, starting with a letter or underscore")
    if schema and not _IDENT.match(schema):
        raise dn.DataNodeError("Schema name: letters, numbers and underscores, starting with a letter or underscore")
    if (schema or "").lower() in _SYSTEM_SCHEMAS:
        raise dn.DataNodeError(f"'{schema}' is a system schema; FlowMind will not write there")
    only = (conn.config.get("write_schema") or "").strip()
    if only and (schema or wh.default_schema()).lower() != only.lower():
        raise dn.DataNodeError(f"This connection only allows writing to the '{only}' schema")


@dn._guard
async def run_write(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = dn._user_id(context)
    conn = await asyncio.to_thread(load_connection, user_id, node_data.get("connectionId"))
    if conn.mode != "read_write":
        raise dn.DataNodeError(f"The connection '{conn.name}' is read-only. Set its access to 'Read & write' on the Connections page "
                               "if you want FlowMind to create tables.")
    mode = node_data.get("mode")
    if mode not in ("create", "replace", "append"):
        raise dn.DataNodeError("Choose what to do: create a new table (fails if it exists), replace it, or append to it. Nothing is chosen for you.")
    wh = conn.warehouse(write=True)
    table = (node_data.get("table") or "").strip()
    schema = (node_data.get("schema") or "").strip() or wh.default_schema()
    _check_target(conn, schema, table, wh)
    target = table_ref(wh.dialect, schema, table)
    ups = dn._upstreams(context)
    if not ups:
        raise dn.DataNodeError("Save to warehouse needs a table to save: connect a data node to its input")
    up = ups[0]
    try:
        if up.result.get("pushdown"):
            if up.result["pushdown"]["connection_id"] != str(conn.id):
                raise dn.DataNodeError("The table lives in a different warehouse than this connection. Pull it into FlowMind first, "
                                       "or use the connection it came from.")
            await wh.write_table(target, up.result["pushdown"]["sql"], mode)
            how = "created in the warehouse (no data left it)"
        else:
            if not wh.supports_insert:
                raise dn.DataNodeError(f"Writing a FlowMind table into {wh.label} is not supported yet. "
                                       "Keep the data in the warehouse (Load Data → In my warehouse) and use Save to warehouse on that.")
            path = (await asyncio.to_thread(dn._db_load_inputs, user_id, [up]))[0][1]
            table_data = await asyncio.to_thread(pq.read_table, path)
            if table_data.num_rows > MAX_WRITE_ROWS:
                raise dn.DataNodeError(f"This table has {table_data.num_rows:,} rows; writing more than {MAX_WRITE_ROWS:,} rows from FlowMind "
                                       "is not supported. Do the work inside the warehouse instead.")
            cols = [{"name": c["name"], "type": c.get("type", "VARCHAR")} for c in up.columns]
            rows = [[r.get(c["name"]) for c in cols] for r in table_data.to_pylist()]
            await wh.insert_rows(target, cols, rows, mode)
            how = f"{len(rows):,} rows copied in from FlowMind"
    except WarehouseError as e:
        raise dn.DataNodeError(str(e))

    rel = f"SELECT * FROM {target}"
    ns, nm = lineage_identity(conn.type, conn.config, schema, table)
    sample = await _safe(wh_sample)(conn, rel)
    count: Optional[int] = None
    try:
        count = await conn.warehouse().count(rel)
    except WarehouseError:
        pass
    edge = LineageEdge(source=f"connection:{conn.name}/{schema}.{table}", operation="write", namespace=ns, name=nm)
    out = _relation_result(context, conn, rel, rel, sample, label=node_data.get("label") or "Save to warehouse", lineage=[edge],
                           node_id=context.get("current_node_id", ""),
                           extra={"written": {"table": f"{schema}.{table}" if schema else table, "mode": mode, "how": how, "rows": count,
                                              "connection": conn.name}})
    out["row_count"] = count
    return out


async def wh_sample(conn: Conn, rel: str) -> Result:
    return await conn.warehouse().sample(rel)
