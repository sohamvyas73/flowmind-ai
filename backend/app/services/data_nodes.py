"""Phase 2 data nodes: Load Data, Clean, Combine, Summarise, SQL.

The Simple nodes (Clean / Combine / Summarise) do not run their own code: each one *compiles its settings to a
single SQL SELECT*, which is then executed by the same sandboxed DuckDB engine as the Pro SQL node. The compiled
SQL is returned in the node result so people can see, learn from, and copy it ("Open as SQL").

Nodes pass datasets by reference: a result carries ``dataset_id`` (a Parquet file in the user's storage) plus a
small, PII-masked ``dataset`` preview (schema + sample rows).
"""
import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.connectors.base import ConnectorError
from app.connectors.postgres import PostgresConnector, stream_table_to_parquet
from app.core.config import settings
from app.core.database import SessionLocal
from app.data.dataset import LineageEdge
from app.engine.duckdb_engine import EngineError, EngineInput, qi, run_sql
from app.models.connection import Connection
from app.models.data import Dataset
from app.services import dataset_service as ds
from app.services import quality
from app.services.dataset_service import DataError
from app.storage.local import StorageError, storage, tenant_key
from app.warehouse.base import WarehouseError
from app.warehouse.registry import is_warehouse

logger = logging.getLogger(__name__)

DATA_NODE_TYPES = {"loadDataNode", "cleanDataNode", "combineDataNode", "summariseDataNode", "sqlNode", "qualityGateNode",
                   "pullDataNode"}
_NUMERIC_PREFIXES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
                     "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL")
_SAFE_TYPE = re.compile(r"^[A-Za-z0-9_(), ]+$")
_AGG_FUNCS = {"count", "count_distinct", "sum", "avg", "min", "max", "median"}
_NUMERIC_AGGS = {"sum", "avg", "median"}
_JOIN_KEYWORDS = {"inner": "INNER", "left": "LEFT", "right": "RIGHT", "full": "FULL"}


class DataNodeError(Exception):
    """A user-facing problem with a node's settings or data."""


# ── helpers ─────────────────────────────────────────────────────────────────────

def _is_numeric(t: str) -> bool:
    return (t or "").upper().startswith(_NUMERIC_PREFIXES)


def _is_text(t: str) -> bool:
    return (t or "").upper().startswith("VARCHAR")


def _lit(v: Any) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", (label or "").lower()).strip("_")
    if s and s[0].isdigit():
        s = "t_" + s
    return s[:40]


def _col_index(cols: List[Dict[str, Any]]) -> Dict[str, str]:
    return {c["name"]: c.get("type", "") for c in cols}


def _need(types: Dict[str, str], col: str, what: str = "column") -> str:
    if col not in types:
        avail = ", ".join(list(types)[:15]) + ("…" if len(types) > 15 else "")
        raise DataNodeError(f"{what.capitalize()} '{col}' was not found in the input. Available columns: {avail}")
    return col


def _unique(names: List[str]) -> None:
    seen, dup = set(), []
    for n in names:
        if n.lower() in seen and n not in dup:
            dup.append(n)
        seen.add(n.lower())
    if dup:
        raise DataNodeError(f"Two columns would end up with the same name: {', '.join(dup)}")


# ── compilers: settings → one SELECT ────────────────────────────────────────────

def compile_clean(cfg: Dict[str, Any], cols: List[Dict[str, Any]], src: str = "input", hash_fn: Optional[Any] = None) -> str:
    types = _col_index(cols)
    names = list(types)
    steps: List[str] = []

    def add(select_body: str) -> None:
        prev = steps[-1][0] if steps else src
        steps.append((f"s{len(steps) + 1}", select_body.replace("{prev}", prev)))  # type: ignore[arg-type]

    # 1. trim whitespace
    trim_cols = [c for c in names if _is_text(types[c])] if cfg.get("trimAll") else list(cfg.get("trimText") or [])
    for c in trim_cols:
        _need(types, c)
        if not _is_text(types[c]):
            raise DataNodeError(f"Cannot trim '{c}': it is {types[c]}, not text")
    if trim_cols:
        add("SELECT * REPLACE (" + ", ".join(f"trim({qi(c)}) AS {qi(c)}" for c in trim_cols) + ") FROM {prev}")

    # 2. change case
    tc = cfg.get("textCase") or {}
    case_cols = list(tc.get("columns") or [])
    if case_cols:
        fn = {"lower": "lower", "upper": "upper"}.get(tc.get("mode"))
        if not fn:
            raise DataNodeError("Text case must be 'lower' or 'upper'")
        for c in case_cols:
            _need(types, c)
            if not _is_text(types[c]):
                raise DataNodeError(f"Cannot change the case of '{c}': it is {types[c]}, not text")
        add("SELECT * REPLACE (" + ", ".join(f"{fn}({qi(c)}) AS {qi(c)}" for c in case_cols) + ") FROM {prev}")

    # 3. drop rows with missing values
    drops = list(cfg.get("dropMissing") or [])
    if drops:
        conds = []
        for c in drops:
            _need(types, c)
            q = qi(c)
            conds.append(f"({q} IS NULL OR trim({q}) = '')" if _is_text(types[c]) else f"{q} IS NULL")
        add("SELECT * FROM {prev} WHERE NOT (" + " OR ".join(conds) + ")")

    # 4. fill missing values
    fills = [f for f in (cfg.get("fillMissing") or []) if f.get("column")]
    if fills:
        parts = []
        for f in fills:
            c = _need(types, f["column"])
            q, t, v = qi(c), types[c], f.get("value", "")
            if _is_text(t):
                parts.append(f"COALESCE(NULLIF(trim({q}), ''), {_lit(v)}) AS {q}")
            else:
                if not _SAFE_TYPE.match(t):
                    raise DataNodeError(f"Cannot fill '{c}' (unsupported type {t})")
                parts.append(f"COALESCE({q}, CAST({_lit(v)} AS {t})) AS {q}")
        add("SELECT * REPLACE (" + ", ".join(parts) + ") FROM {prev}")

    # 4b. protect personal data (hash / mask / redact / blank)
    protects = [p for p in (cfg.get("protect") or []) if p.get("column")]
    if protects:
        parts = []
        for p in protects:
            c = _need(types, p["column"])
            q, method = qi(c), p.get("method", "hash")
            as_text = f"CAST({q} AS VARCHAR)"
            if method == "hash":
                salt = str(cfg.get("hashSalt") or "")
                inner = f"{_lit(salt)} || {as_text}" if salt else as_text
                expr = hash_fn(inner) if hash_fn else f"sha256({inner})"
            elif method == "mask":
                expr = f"CASE WHEN {q} IS NULL THEN NULL ELSE repeat('*', greatest(length({as_text}) - 4, 0)) || right({as_text}, 4) END"
            elif method == "redact":
                expr = f"CASE WHEN {q} IS NULL THEN NULL ELSE '[REMOVED]' END"
            elif method == "blank":
                if not _SAFE_TYPE.match(types[c]):
                    raise DataNodeError(f"Cannot blank '{c}' (unsupported type {types[c]})")
                expr = f"CAST(NULL AS {types[c]})"
            else:
                raise DataNodeError(f"Unknown way to protect '{c}': {method}. Use hash, mask, redact or blank")
            parts.append(f"{expr} AS {q}")
        add("SELECT * REPLACE (" + ", ".join(parts) + ") FROM {prev}")

    # 5. remove duplicate rows
    if cfg.get("removeDuplicates"):
        add("SELECT DISTINCT * FROM {prev}")

    # 6. keep / rename columns
    keep = list(cfg.get("keepColumns") or [])
    renames = {r["from"]: r["to"] for r in (cfg.get("rename") or []) if r.get("from") and r.get("to")}
    for k in keep:
        _need(types, k)
    for old, new in renames.items():
        _need(types, old)
        if not str(new).strip():
            raise DataNodeError(f"New name for '{old}' is empty")
    final_names = keep or names
    if keep or renames:
        out_names = [renames.get(n, n) for n in final_names]
        _unique(out_names)
        add("SELECT " + ", ".join(f"{qi(n)} AS {qi(renames.get(n, n))}" for n in final_names) + " FROM {prev}")

    if not steps:
        return f"SELECT * FROM {src}"
    ctes = ",\n".join(f"{name} AS ({body})" for name, body in steps[:-1])
    last = steps[-1][1]
    return (f"WITH {ctes}\n{last}" if ctes else last)


def compile_combine(
    cfg: Dict[str, Any], left_cols: List[Dict[str, Any]], right_cols: List[Dict[str, Any]],
    left_alias: str = "input", right_alias: str = "input2",
) -> str:
    jt = _JOIN_KEYWORDS.get(str(cfg.get("joinType", "inner")).lower())
    if not jt:
        raise DataNodeError("Join type must be inner, left, right or full")
    keys = [k for k in (cfg.get("keys") or []) if k.get("left") and k.get("right")]
    if not keys:
        raise DataNodeError("Choose at least one column to match on (e.g. customer_id = customer_id)")
    lt, rt = _col_index(left_cols), _col_index(right_cols)
    for k in keys:
        _need(lt, k["left"], "left column")
        _need(rt, k["right"], "right column")
        if _is_numeric(lt[k["left"]]) != _is_numeric(rt[k["right"]]) or _is_text(lt[k["left"]]) != _is_text(rt[k["right"]]):
            raise DataNodeError(
                f"Cannot match '{k['left']}' ({lt[k['left']]}) with '{k['right']}' ({rt[k['right']]}): "
                "the types differ. Clean or convert one side first."
            )
    shared = {k["left"] for k in keys if k["left"] == k["right"]}
    left_names, taken = list(lt), set(n.lower() for n in lt)
    select: List[str] = []
    for c in left_names:
        select.append(f"COALESCE(l.{qi(c)}, r.{qi(c)}) AS {qi(c)}" if c in shared else f"l.{qi(c)} AS {qi(c)}")
    for c in rt:
        if c in shared:
            continue
        out = c
        if out.lower() in taken:
            out = f"{c}_right"
            n = 2
            while out.lower() in taken:
                out, n = f"{c}_right{n}", n + 1
        taken.add(out.lower())
        select.append(f"r.{qi(c)} AS {qi(out)}")
    on = " AND ".join(f"l.{qi(k['left'])} = r.{qi(k['right'])}" for k in keys)
    return f"SELECT {', '.join(select)}\nFROM {qi(left_alias)} AS l\n{jt} JOIN {qi(right_alias)} AS r ON {on}"


def compile_summarise(cfg: Dict[str, Any], cols: List[Dict[str, Any]], src: str = "input") -> str:
    types = _col_index(cols)
    group = list(cfg.get("groupBy") or [])
    aggs = [a for a in (cfg.get("aggregations") or []) if a.get("fn")]
    for g in group:
        _need(types, g)
    if not group and not aggs:
        raise DataNodeError("Choose a column to group by and/or something to calculate (e.g. total of amount)")
    parts = [qi(g) for g in group]
    out_names = list(group)
    for a in aggs:
        fn, col = a["fn"], a.get("column") or "*"
        if fn not in _AGG_FUNCS:
            raise DataNodeError(f"Unknown calculation '{fn}'. Use: {', '.join(sorted(_AGG_FUNCS))}")
        if col == "*":
            if fn != "count":
                raise DataNodeError(f"'{fn}' needs a column")
            expr, default = "count(*)", "row_count"
        else:
            _need(types, col)
            if fn in _NUMERIC_AGGS and not _is_numeric(types[col]):
                raise DataNodeError(
                    f"Cannot {fn} '{col}': it is {types[col]}, not numbers. Convert it first (Clean node or SQL)."
                )
            expr = f"count(DISTINCT {qi(col)})" if fn == "count_distinct" else f"{fn}({qi(col)})"
            default = f"{fn}_{col}"
        name = (a.get("as") or default).strip()
        parts.append(f"{expr} AS {qi(name)}")
        out_names.append(name)
    _unique(out_names)
    sql = f"SELECT {', '.join(parts)}\nFROM {src}"
    if group:
        gq = ", ".join(qi(g) for g in group)
        sql += f"\nGROUP BY {gq}\nORDER BY {gq}"
    return sql


# ── runtime ─────────────────────────────────────────────────────────────────────

@dataclass
class Upstream:
    node_id: str
    label: str
    dataset_id: Optional[str]                 # None for a table that lives in the user's warehouse (pushdown)
    columns: List[Dict[str, Any]]
    result: Dict[str, Any]


def _user_id(context: Dict[str, Any]):
    uid = context.get("_user_id")
    if not uid:
        raise DataNodeError("Data nodes can only run for a signed-in user")
    return uid


def _upstreams(context: Dict[str, Any]) -> List[Upstream]:
    node_id = context.get("current_node_id", "")
    out: List[Upstream] = []
    for src in context.get("_incoming", {}).get(node_id, []):
        r = (context.get("_outputs") or {}).get(src) or {}
        if r.get("dataset_id") or r.get("pushdown"):
            out.append(Upstream(src, context.get("_labels", {}).get(src, src), r.get("dataset_id"), r["dataset"]["columns"], r))
    return out


WAREHOUSE_TABLE_MSG = ("This table lives in your warehouse. {what} works on tables inside FlowMind: "
                       "add a Pull node first to bring it in (or keep working in the warehouse with Clean, Combine, Summarise or SQL).")


def _db_load_inputs(user_id, ups: List[Upstream], what: str = "This step") -> List[Tuple[Upstream, str]]:
    if any(u.result.get("pushdown") for u in ups):
        raise DataNodeError(WAREHOUSE_TABLE_MSG.format(what=what))
    with SessionLocal() as db:
        return [(u, storage.path_for(ds.get_dataset(db, user_id, u.dataset_id).storage_key)) for u in ups]


async def _materialise(
    context: Dict[str, Any], *, sql: str, inputs: List[EngineInput], lineage: List[LineageEdge],
    label: str, extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user_id = _user_id(context)
    dry = bool(context.get("_dry_run"))
    node_id = context.get("current_node_id", "")
    ds_id = uuid.uuid4()
    key = tenant_key(user_id, "datasets", f"{ds_id}.parquet")
    out_path = storage.path_for(key)

    def _quota():
        with SessionLocal() as db:
            ds.check_quota(db, user_id)
    if not dry:
        await asyncio.to_thread(_quota)

    res = await run_sql(inputs, sql, out_path, sample_rows=100)
    return await _register(context, ds_id=ds_id, key=key, label=label, sql=sql, columns=res.columns,
                           sample=res.sample, row_count=res.row_count, out_bytes=res.out_bytes,
                           lineage=lineage, usage={"compute_s": res.compute_s, "scanned_bytes": res.scanned_bytes,
                                                   "scanned_rows": res.scanned_rows}, extra=extra, node_id=node_id)


async def _register(
    context, *, ds_id, key, label, sql, columns, sample, row_count, out_bytes, lineage, usage, extra, node_id,
) -> Dict[str, Any]:
    user_id = _user_id(context)
    dry = bool(context.get("_dry_run"))

    def _save() -> None:
        with SessionLocal() as db:
            try:
                if not dry:
                    ds.check_quota(db, user_id)
            except DataError:
                storage.delete(key)
                raise
            db.add(Dataset(
                id=ds_id, user_id=user_id, name=label, storage_key=key, size_bytes=out_bytes, row_count=row_count,
                columns=columns, execution_id=context.get("_execution_id"), node_id=node_id, sql=sql,
                lineage=[e.model_dump() for e in lineage], expires_at=ds.default_expiry(dry),
            ))
            db.commit()
    await asyncio.to_thread(_save)

    ref = ds.make_ref(columns, sample, row_count=row_count, size_bytes=out_bytes, dataset_id=ds_id,
                      produced_by=node_id, lineage=lineage, path=f"dataset:{ds_id}")
    result: Dict[str, Any] = {
        "dataset_id": str(ds_id),
        "dataset": ref.model_dump(mode="json"),
        "row_count": row_count,
        "columns": [c["name"] for c in columns],
        "sql": sql,
        "dry_run": dry,
        "_usage": usage,
        "timestamp": datetime.utcnow().isoformat(),
    }
    result.update(extra or {})
    return result


def _guard(fn):
    async def wrapper(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await fn(node_data, context)
        except (DataNodeError, DataError, EngineError, ConnectorError, StorageError, WarehouseError) as e:
            return {"error": str(e)}
        except Exception as e:  # never let a data node crash the whole worker
            logger.exception("data node failed")
            return {"error": f"{type(e).__name__}: {e}"}
    return wrapper


@_guard
async def run_load(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    user_id = _user_id(context)
    label = node_data.get("label") or "Load Data"
    cap = settings.DRY_RUN_ROWS if context.get("_dry_run") else settings.MAX_LOAD_ROWS
    try:
        limit = int(node_data.get("maxRows") or cap)
    except (TypeError, ValueError):
        raise DataNodeError("Max rows must be a number")
    limit = max(1, min(limit, cap))
    source = node_data.get("source", "file")

    if source == "file":
        def _file():
            with SessionLocal() as db:
                f = ds.get_file(db, user_id, file_id=node_data.get("fileId"), name=node_data.get("fileName"))
                return f.name, f.format, storage.path_for(f.storage_key)
        name, fmt, path = await asyncio.to_thread(_file)
        sql = f"SELECT * FROM src LIMIT {limit}"
        return await _materialise(
            context, sql=sql, inputs=[EngineInput("src", path, fmt)],
            lineage=[LineageEdge(source=f"file:{name}", operation="read", namespace="flowmind://files", name=name)],
            label=label,
        )

    if source == "connection":
        def _conn():
            with SessionLocal() as db:
                try:
                    c = db.query(Connection).filter(
                        Connection.id == uuid.UUID(str(node_data.get("connectionId"))), Connection.user_id == user_id
                    ).first()
                except ValueError:
                    c = None
                if c is None:
                    raise DataNodeError("Connection not found. Pick one of your saved connections.")
                if c.type != "postgres" and not is_warehouse(c.type):
                    raise DataNodeError(f"Load Data needs a database or warehouse connection (this one is {c.type})")
                return json.loads(c.config), c.access_mode, list(c.host_allowlist or []), c.name, c.type, c.id
        config, mode, allow, conn_name, conn_type, conn_id = await asyncio.to_thread(_conn)
        if conn_type != "postgres" or node_data.get("runOn") == "warehouse":
            from app.services import pushdown                      # data stays in the warehouse, or a warehouse other than Postgres
            return await pushdown.load_from_warehouse(node_data, context, pushdown.Conn(conn_id, conn_name, conn_type, config, mode, allow))
        table = (node_data.get("table") or "").strip()
        if not table:
            raise DataNodeError("Choose a table to load")
        schema = (node_data.get("schema") or "public").strip()
        ds_id = uuid.uuid4()
        key = tenant_key(user_id, "datasets", f"{ds_id}.parquet")
        out_path = storage.path_for(key)

        def _quota():
            with SessionLocal() as db:
                ds.check_quota(db, user_id)
        if not context.get("_dry_run"):
            await asyncio.to_thread(_quota)
        rows = await stream_table_to_parquet(
            PostgresConnector(), config, access_mode=mode, allow_hosts=allow, schema=schema, table=table,
            columns=node_data.get("columns") or [], limit=limit, out_path=out_path,
        )
        info = await ds.sample_of(out_path, "parquet", 100, storage.path_for(tenant_key(user_id, "datasets", f"{ds_id}.probe.parquet")))
        return await _register(
            context, ds_id=ds_id, key=key, label=label, sql=f"-- loaded {rows:,} rows from {conn_name}: {schema}.{table}",
            columns=info["columns"], sample=info["sample"], row_count=rows, out_bytes=storage.size(key),
            lineage=[LineageEdge(
                source=f"connection:{conn_name}/{schema}.{table}", operation="read",
                namespace=f"postgres://{config.get('host')}:{config.get('port', 5432)}",
                name=f"{config.get('database')}.{schema}.{table}")],
            usage={"compute_s": 0, "scanned_bytes": storage.size(key), "scanned_rows": rows},
            extra=None, node_id=context.get("current_node_id", ""),
        )

    raise DataNodeError("Choose where to load data from: an uploaded file or a database connection")


def _one(context: Dict[str, Any], what: str) -> Tuple[Upstream, str]:
    ups = _upstreams(context)
    if not ups:
        raise DataNodeError(f"{what} needs data: connect a Load Data (or another data) node to its input")
    loaded = _db_load_inputs(_user_id(context), ups[:1], what)
    return loaded[0]


def _lineage(ups: List[Upstream], op: str) -> List[LineageEdge]:
    return [LineageEdge(source=f"dataset:{u.dataset_id}", operation=op) for u in ups]


async def _maybe_pushdown(kind: str, node_data: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """If the input table lives in the user's warehouse, run this step there instead of in DuckDB."""
    from app.services import pushdown
    ups = _upstreams(context)
    if ups and pushdown.pushdown_upstreams(ups):
        return await pushdown.run_step(kind, node_data, ups, context)
    return None


@_guard
async def run_clean(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    pd = await _maybe_pushdown("clean", node_data, context)
    if pd is not None:
        return pd
    up, path = await asyncio.to_thread(_one, context, "Clean")
    sql = compile_clean(node_data, up.columns)
    return await _materialise(context, sql=sql, inputs=[EngineInput("input", path)],
                              lineage=_lineage([up], "clean"), label=node_data.get("label") or "Clean")


@_guard
async def run_summarise(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    pd = await _maybe_pushdown("summarise", node_data, context)
    if pd is not None:
        return pd
    up, path = await asyncio.to_thread(_one, context, "Summarise")
    sql = compile_summarise(node_data, up.columns)
    return await _materialise(context, sql=sql, inputs=[EngineInput("input", path)],
                              lineage=_lineage([up], "summarise"), label=node_data.get("label") or "Summarise")


@_guard
async def run_combine(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    pd = await _maybe_pushdown("combine", node_data, context)
    if pd is not None:
        return pd
    ups = _upstreams(context)
    if len(ups) < 2:
        raise DataNodeError("Combine needs two inputs: connect two data nodes to it (first = left table, second = right)")
    if node_data.get("swap"):
        ups = [ups[1], ups[0]] + ups[2:]
    left, right = ups[0], ups[1]
    loaded = await asyncio.to_thread(_db_load_inputs, _user_id(context), [left, right])
    sql = compile_combine(node_data, left.columns, right.columns)
    return await _materialise(
        context, sql=sql,
        inputs=[EngineInput("input", loaded[0][1]), EngineInput("input2", loaded[1][1])],
        lineage=_lineage([left, right], "combine"), label=node_data.get("label") or "Combine",
        extra={"left": left.label, "right": right.label},
    )


@_guard
async def run_sql_node(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    pd = await _maybe_pushdown("sql", node_data, context)
    if pd is not None:
        return pd
    ups = _upstreams(context)
    if not ups:
        raise DataNodeError("SQL needs data: connect a data node to its input")
    loaded = await asyncio.to_thread(_db_load_inputs, _user_id(context), ups)
    inputs: List[EngineInput] = []
    names = {"input"}
    for i, (u, path) in enumerate(loaded):
        inputs.append(EngineInput("input" if i == 0 else f"input{i + 1}", path))
        if i > 0:
            names.add(f"input{i + 1}")
    for u, path in loaded:                                    # friendly alias from the upstream node's label
        s = slug(u.label)
        if s and s not in names:
            names.add(s)
            inputs.append(EngineInput(s, path))
    sql = (node_data.get("query") or "").strip()
    if not sql:
        raise DataNodeError("Write a SQL query, e.g. SELECT * FROM input LIMIT 10")
    return await _materialise(
        context, sql=sql, inputs=inputs, lineage=_lineage([u for u, _ in loaded], "sql"),
        label=node_data.get("label") or "SQL",
        extra={"tables": [i.alias for i in inputs]},
    )


@_guard
async def run_quality_gate(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Check the incoming table. The table itself passes through unchanged (no copy); a `quality` report is added."""
    user_id = _user_id(context)
    up, path = await asyncio.to_thread(_one, context, "Quality check")
    label = node_data.get("label") or "Quality check"
    out_dir = storage.path_for(tenant_key(user_id, "tmp"))
    os.makedirs(out_dir, exist_ok=True)
    try:
        report = await quality.evaluate(node_data.get("rules"), up.columns, path, out_dir)
    except quality.QualityConfigError as e:
        raise DataNodeError(str(e))

    base = {
        "dataset_id": up.dataset_id,
        "dataset": up.result["dataset"],
        "row_count": up.result.get("row_count"),
        "columns": up.result.get("columns"),
        "sql": report["sql"],
        "quality": report,
        "_usage": report["usage"],
        "dry_run": bool(context.get("_dry_run")),
        "timestamp": datetime.utcnow().isoformat(),
    }
    on_fail = node_data.get("onFail", "stop")
    if on_fail not in ("stop", "warn"):
        raise DataNodeError("'When a check fails' must be 'stop' or 'warn'")
    if not report["passed"] and on_fail == "stop":
        base["error"] = quality.summarise(report, label)
    return base
