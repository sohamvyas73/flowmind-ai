"""Phase 5 ML nodes: Predict, Batch Score, Drift Check, Feedback Capture, Registry Promote.

Models are never loaded or executed inside FlowMind. Scoring goes to the customer's own endpoint, and the registry is
reached over MLflow's REST API, so a model artifact cannot run code in this process. Every node needs an explicit,
user-chosen connection: nothing is picked automatically.
"""
import asyncio
import json
import math
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.connectors.ml import mlflow_client
from app.core.database import SessionLocal
from app.data.dataset import LineageEdge, _jsonable
from app.engine.duckdb_engine import EngineInput, run_sql
from app.ml import drift as drift_lib
from app.ml import endpoints
from app.ml.mlflow_client import MlflowError, check_alias, check_model_name
from app.models.connection import Connection
from app.models.ml import MlFeedbackBatch
from app.services import data_nodes
from app.services import dataset_service as ds
from app.storage.local import storage, tenant_key

ML_NODE_TYPES = {"predictNode", "batchScoreNode", "driftCheckNode", "feedbackNode", "registryPromoteNode"}
MAX_SCORE_ROWS = 500_000
DEFAULT_SCORE_ROWS = 100_000
MAX_FEEDBACK_ROWS = 1_000_000
MAX_DRIFT_ROWS = 2_000_000
_COL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}


class MlNodeError(Exception):
    """A user-facing problem with an ML node's settings, data or endpoint."""


def _user(context: Dict[str, Any]):
    uid = context.get("_user_id")
    if not uid:
        raise MlNodeError("ML nodes can only run for a signed-in user")
    return uid


def _guard(fn):
    async def wrapper(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await fn(node_data, context)
        except (MlNodeError, endpoints.ScoreError, MlflowError, drift_lib.DriftConfigError,
                data_nodes.DataNodeError, ds.DataError) as e:
            return {"error": str(e)}
        except Exception as e:                                    # never let one node crash the worker
            return {"error": f"{type(e).__name__}: {e}"}
    return wrapper


def _connection(user_id, connection_id: Any, wanted: str) -> Tuple[Dict[str, Any], str, List[str], str]:
    noun = "MLflow connection" if wanted == "mlflow" else "model endpoint connection"
    if not connection_id:
        raise MlNodeError(f"Choose a {noun}. Nothing is chosen for you — add one on the Connections page.")
    with SessionLocal() as db:
        try:
            c = db.query(Connection).filter(Connection.id == uuid.UUID(str(connection_id)), Connection.user_id == user_id).first()
        except ValueError:
            c = None
        if c is None:
            raise MlNodeError(f"That {noun} no longer exists. Pick one of your saved connections.")
        if c.type != wanted:
            raise MlNodeError(f"'{c.name}' is a {c.type} connection; this node needs a {wanted} connection")
        return json.loads(c.config or "{}"), c.access_mode, list(c.host_allowlist or []), c.name


def _features(node_data: Dict[str, Any]) -> List[str]:
    feats = [f.strip() for f in (node_data.get("features") or []) if isinstance(f, str) and f.strip()]
    if not feats:
        raise MlNodeError("List the features the model expects (the column / field names it was trained on). "
                          "Nothing is guessed, so no private column is sent by accident.")
    if len(set(feats)) != len(feats):
        raise MlNodeError("A feature is listed twice")
    return feats


def _flat(previous: Any) -> Dict[str, Any]:
    if not isinstance(previous, dict):
        return {}
    for k in ("inputs", "transformed"):
        if isinstance(previous.get(k), dict):
            return previous[k]
    return previous


def _num(v: Any) -> Any:
    """'64000' -> 64000, '3.5' -> 3.5; anything else unchanged (form fields arrive as text)."""
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                f = float(s)
                return f if math.isfinite(f) else v
            except ValueError:
                return v
    return v


def _clean(v: Any) -> Any:
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return _jsonable(v)


def _prediction_type(values: List[Any]) -> Tuple[pa.DataType, str]:
    vals = [v for v in values if v is not None]
    if vals and all(isinstance(v, bool) for v in vals):
        return pa.bool_(), "BOOLEAN"
    if vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return pa.int64(), "BIGINT"
    if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return pa.float64(), "DOUBLE"
    return pa.string(), "VARCHAR"


def _coerce(values: List[Any], t: pa.DataType) -> List[Any]:
    if pa.types.is_string(t):
        return [None if v is None else str(v) for v in values]
    if pa.types.is_floating(t):
        return [None if v is None else float(v) for v in values]
    return values


def _summary(values: List[Any]) -> Dict[str, Any]:
    vals = [v for v in values if v is not None]
    if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) and len(set(vals)) > 20:
        a = np.array(vals, dtype=float)
        return {"mean": float(a.mean()), "min": float(a.min()), "max": float(a.max())}
    counts: Dict[str, int] = {}
    for v in vals:
        counts[str(v)] = counts.get(str(v), 0) + 1
    return {"counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:20])}


# ── Predict (one record) ────────────────────────────────────────────────────────

@_guard
async def run_predict(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    uid = _user(context)
    cfg, _, allow, conn_name = await asyncio.to_thread(_connection, uid, node_data.get("connectionId"), "ml_endpoint")
    feats = _features(node_data)
    prev = context.get("previous_output") or {}
    if isinstance(prev, dict) and prev.get("dataset_id"):
        raise MlNodeError("This node scores one record. To score a whole table, use Batch Score.")
    record = _flat(prev)
    missing = [f for f in feats if f not in record]
    if missing:
        avail = ", ".join(list(record)[:15]) + ("…" if len(record) > 15 else "")
        raise MlNodeError(f"Feature(s) not found in the previous node's output: {', '.join(missing)}. Available fields: {avail}")
    auto = node_data.get("autoNumbers", True)
    row = {f: _clean(_num(record[f]) if auto else record[f]) for f in feats}
    preds, ms = await endpoints.score_rows(cfg, [row], feats, allow)
    p = preds[0]
    return {
        "prediction": p["prediction"], "probability": p.get("prediction_proba"), "prediction_id": str(uuid.uuid4()),
        "features": row, "model_endpoint": conn_name, "latency_ms": ms, "timestamp": datetime.utcnow().isoformat(),
    }


# ── Batch Score (a table) ───────────────────────────────────────────────────────

@_guard
async def run_batch_score(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    uid = _user(context)
    cfg, _, allow, conn_name = await asyncio.to_thread(_connection, uid, node_data.get("connectionId"), "ml_endpoint")
    feats = _features(node_data)
    up, path = await asyncio.to_thread(data_nodes._one, context, "Batch Score")
    cols = [c["name"] for c in up.columns]
    missing = [f for f in feats if f not in cols]
    if missing:
        raise MlNodeError(f"Column(s) not found: {', '.join(missing)}. Available columns: {', '.join(cols[:15])}")
    out_col = (node_data.get("outputColumn") or "prediction").strip()
    if not _COL.match(out_col):
        raise MlNodeError("Output column: start with a letter or underscore, then letters, numbers or underscores")
    proba_col = f"{out_col}_proba"
    if out_col in cols:
        raise MlNodeError(f"The table already has a column named '{out_col}'. Choose another output column name.")
    try:
        bs = int(node_data.get("batchSize") or 200)
        limit = int(node_data.get("maxRows") or DEFAULT_SCORE_ROWS)
    except (TypeError, ValueError):
        raise MlNodeError("Batch size and max rows must be numbers")
    bs, limit = max(1, min(bs, endpoints.MAX_BATCH)), max(1, min(limit, MAX_SCORE_ROWS))
    total = up.result.get("row_count") or 0
    if total > limit:
        raise MlNodeError(f"This table has {total:,} rows but the limit for one Batch Score is {limit:,}. "
                          "Filter it first, or raise 'Max rows' (up to 500,000).")

    # pass 1: score
    preds: List[Dict[str, Any]] = []
    latencies: List[int] = []

    def _batches():
        pf = pq.ParquetFile(path)
        for b in pf.iter_batches(batch_size=bs, columns=feats):
            yield [{f: _clean(v) for f, v in r.items()} for r in b.to_pylist()]
    it = await asyncio.to_thread(lambda: list(_batches()))
    offset = 0
    for rows in it:
        try:
            res, ms = await endpoints.score_rows(cfg, rows, feats, allow)
        except endpoints.ScoreError as e:
            raise MlNodeError(f"Scoring stopped at row {offset + 1:,}: {e}")
        preds += res
        latencies.append(ms)
        offset += len(rows)
    values = [p["prediction"] for p in preds]
    probas = [p.get("prediction_proba") for p in preds]
    has_proba = any(v is not None for v in probas) and proba_col not in cols
    ptype, pduck = _prediction_type(values)
    new_cols = [{"name": out_col, "type": pduck}] + ([{"name": proba_col, "type": "DOUBLE"}] if has_proba else [])

    # pass 2: write the table with the new column(s)
    ds_id = uuid.uuid4()
    key = tenant_key(uid, "datasets", f"{ds_id}.parquet")
    out_path = storage.path_for(key)

    def _quota():
        with SessionLocal() as db:
            ds.check_quota(db, uid)
    await asyncio.to_thread(_quota)

    def _write() -> List[Dict[str, Any]]:
        pf = pq.ParquetFile(path)
        schema = pf.schema_arrow.append(pa.field(out_col, ptype))
        if has_proba:
            schema = schema.append(pa.field(proba_col, pa.float64()))
        pos, sample = 0, []
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with pq.ParquetWriter(out_path, schema) as w:
            for b in pf.iter_batches(batch_size=50_000):
                n = b.num_rows
                tbl = pa.Table.from_batches([b]).append_column(out_col, pa.array(_coerce(values[pos:pos + n], ptype), type=ptype))
                if has_proba:
                    tbl = tbl.append_column(proba_col, pa.array(probas[pos:pos + n], type=pa.float64()))
                if len(sample) < 100:
                    sample += tbl.slice(0, 100 - len(sample)).to_pylist()
                w.write_table(tbl)
                pos += n
        return sample
    sample = await asyncio.to_thread(_write)
    out_bytes = storage.size(key)

    edges = [LineageEdge(source=f"dataset:{up.dataset_id}", operation="score"),
             LineageEdge(source=f"model:{conn_name}", operation="model", namespace="flowmind://models", name=conn_name)]
    result = await data_nodes._register(
        context, ds_id=ds_id, key=key, label=node_data.get("label") or "Batch Score",
        sql=f"-- scored {len(values):,} rows with the model endpoint '{conn_name}' → column {out_col}",
        columns=[{"name": c["name"], "type": c.get("type", "")} for c in up.columns] + new_cols, sample=sample,
        row_count=len(values), out_bytes=out_bytes, lineage=edges,
        usage={"scanned_bytes": 0, "compute_s": 0, "scanned_rows": len(values)},
        extra={"scored_rows": len(values), "model_endpoint": conn_name, "output_columns": [c["name"] for c in new_cols],
               "avg_latency_ms": int(sum(latencies) / max(len(latencies), 1)), "requests": len(latencies),
               "prediction_summary": _summary(values)},
        node_id=context.get("current_node_id", ""))
    return result


# ── Drift Check ─────────────────────────────────────────────────────────────────

def _is_number(t: str) -> bool:
    return data_nodes._is_numeric(t)


def _load_columns(path: str, names: List[str], kinds: Dict[str, str]) -> Dict[str, Any]:
    t = pq.read_table(path, columns=names)
    if t.num_rows > MAX_DRIFT_ROWS:
        t = t.slice(0, MAX_DRIFT_ROWS)
    out: Dict[str, Any] = {}
    for n in names:
        col = t.column(n)
        if kinds[n] == "numeric":
            out[n] = pc.fill_null(col.cast(pa.float64()), float("nan")).to_numpy()
        else:
            out[n] = col.to_pylist()
    return out


@data_nodes._guard
async def run_drift_check(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    uid = _user(context)
    label = node_data.get("label") or "Drift check"
    ref_name = (node_data.get("referenceFile") or "").strip()
    if not ref_name:
        raise MlNodeError("Choose the reference file: the data the model was trained on (upload it on the Data page).")
    try:
        warn, alert = float(node_data.get("warnAt") or 0.1), float(node_data.get("alertAt") or 0.25)
    except (TypeError, ValueError):
        raise MlNodeError("Thresholds must be numbers")
    on_drift = node_data.get("onDrift", "stop")
    if on_drift not in ("stop", "warn"):
        raise MlNodeError("'When data has drifted' must be 'stop' or 'warn'")
    up, cur_path = await asyncio.to_thread(data_nodes._one, context, "Drift Check")

    def _ref():
        with SessionLocal() as db:
            f = ds.get_file(db, uid, name=ref_name)
            return f.format, storage.path_for(f.storage_key), f.columns or []
    fmt, ref_path, ref_cols = await asyncio.to_thread(_ref)
    ref_types = {c["name"]: c.get("type", "") for c in ref_cols}
    cur_types = {c["name"]: c.get("type", "") for c in up.columns}
    wanted = [c.strip() for c in (node_data.get("columns") or []) if isinstance(c, str) and c.strip()]
    shared = [c for c in cur_types if c in ref_types]
    if wanted:
        bad = [c for c in wanted if c not in shared]
        if bad:
            raise MlNodeError(f"Column(s) not in both tables: {', '.join(bad)}")
        names = wanted
    else:
        pii = {c["name"] for c in up.result.get("dataset", {}).get("columns", []) if "pii" in (c.get("tags") or [])}
        names = [c for c in shared if c not in pii]          # personal data is never profiled unless asked for by name
    if not names:
        raise MlNodeError("The reference file and the current table share no columns to compare")
    kinds = {c: ("numeric" if _is_number(ref_types[c]) and _is_number(cur_types[c]) else "category") for c in names}

    tmp_dir = storage.path_for(tenant_key(uid, "tmp"))
    os.makedirs(tmp_dir, exist_ok=True)
    ref_parquet = os.path.join(tmp_dir, f"{uuid.uuid4()}.ref.parquet")
    try:
        sel = ", ".join(data_nodes.qi(c) for c in names)
        res = await run_sql([EngineInput("f", ref_path, fmt)], f"SELECT {sel} FROM f LIMIT {MAX_DRIFT_ROWS}", ref_parquet, sample_rows=0)
        ref = await asyncio.to_thread(_load_columns, ref_parquet, names, kinds)
    finally:
        if os.path.exists(ref_parquet):
            os.remove(ref_parquet)
    cur = await asyncio.to_thread(_load_columns, cur_path, names, kinds)
    skipped: List[Dict[str, str]] = []
    if not wanted:                                           # IDs and free text change every time: not drift
        for c in [c for c in names if kinds[c] == "category"]:
            if len(ref[c]) > 50 and len(set(ref[c])) / len(ref[c]) > 0.5:
                skipped.append({"name": c, "reason": "looks like an ID or free text (almost every value is different)"})
                kinds.pop(c)
        if not kinds:
            raise MlNodeError("Every shared column looks like an ID or free text. Pick the columns to compare.")
    report = drift_lib.compare(ref, cur, kinds, warn=warn, alert=alert)
    report.update(skipped=skipped, reference_file=ref_name, reference_rows=res.row_count, current_rows=up.result.get("row_count"))

    base = {
        "dataset_id": up.dataset_id, "dataset": up.result["dataset"], "row_count": up.result.get("row_count"),
        "columns": up.result.get("columns"), "sql": f"-- drift check vs {ref_name}", "drift": report,
        "_usage": {"scanned_bytes": 0, "compute_s": res.compute_s}, "dry_run": bool(context.get("_dry_run")),
        "timestamp": datetime.utcnow().isoformat(),
    }
    if report["drifted"] and on_drift == "stop":
        base["error"] = drift_lib.summarise(report, label)
    return base


# ── Feedback Capture ────────────────────────────────────────────────────────────

def _norm(v: Any) -> str:
    n = _num(v)
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return str(n).strip().lower()


def feedback_metrics(task: str, preds: List[Any], actuals: List[Any]) -> Dict[str, Any]:
    pairs = [(p, a) for p, a in zip(preds, actuals) if p is not None and a is not None]
    if not pairs:
        raise MlNodeError("There are no rows with both a prediction and an actual outcome")
    if task == "regression":
        try:
            err = np.array([float(_num(p)) - float(_num(a)) for p, a in pairs], dtype=float)
        except (TypeError, ValueError):
            raise MlNodeError("Regression feedback needs numeric prediction and actual columns")
        return {"rows": len(pairs), "metric": "mae", "value": float(np.abs(err).mean()),
                "details": {"rmse": float(np.sqrt((err ** 2).mean())), "bias": float(err.mean())}}
    ok = sum(1 for p, a in pairs if _norm(p) == _norm(a))
    per: Dict[str, Dict[str, int]] = {}
    for p, a in pairs:
        d = per.setdefault(_norm(a), {"actual": 0, "correct": 0})
        d["actual"] += 1
        d["correct"] += int(_norm(p) == _norm(a))
    return {"rows": len(pairs), "metric": "accuracy", "value": ok / len(pairs), "details": {"per_class": per}}


@data_nodes._guard
async def run_feedback(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    uid = _user(context)
    model = (node_data.get("modelName") or "").strip()
    if not model:
        raise MlNodeError("Give the model a name to track (for example churn-model). It is only a label for the history.")
    task = node_data.get("taskType")
    if task not in ("classification", "regression"):
        raise MlNodeError("Choose the task type: classification or regression")
    pcol, acol = (node_data.get("predictionColumn") or "").strip(), (node_data.get("actualColumn") or "").strip()
    if not pcol or not acol:
        raise MlNodeError("Name the prediction column and the actual-outcome column")
    on_fail = node_data.get("onFail", "warn")
    if on_fail not in ("stop", "warn"):
        raise MlNodeError("'When the model gets worse' must be 'stop' or 'warn'")
    thr_raw = node_data.get("threshold")
    thr: Optional[float] = None
    if thr_raw not in (None, ""):
        try:
            thr = float(thr_raw)
        except (TypeError, ValueError):
            raise MlNodeError("Threshold must be a number")

    ups = data_nodes._upstreams(context)
    passthrough: Dict[str, Any] = {}
    if ups:
        up, path = await asyncio.to_thread(data_nodes._one, context, "Feedback Capture")
        names = [c["name"] for c in up.columns]
        for c in (pcol, acol):
            if c not in names:
                raise MlNodeError(f"Column '{c}' was not found. Available columns: {', '.join(names[:15])}")

        def _read():
            t = pq.read_table(path, columns=[pcol, acol])
            t = t.slice(0, MAX_FEEDBACK_ROWS)
            return t.column(pcol).to_pylist(), t.column(acol).to_pylist()
        preds, actuals = await asyncio.to_thread(_read)
        passthrough = {"dataset_id": up.dataset_id, "dataset": up.result["dataset"], "row_count": up.result.get("row_count"),
                       "columns": up.result.get("columns"), "sql": "-- feedback captured"}
    else:
        rec = _flat(context.get("previous_output"))
        if pcol not in rec or acol not in rec:
            raise MlNodeError(f"Fields '{pcol}' and '{acol}' were not found in the previous node's output "
                              f"(or connect a table). Available fields: {', '.join(list(rec)[:15])}")
        preds, actuals = [rec[pcol]], [rec[acol]]
        passthrough = {k: v for k, v in rec.items()} if isinstance(rec, dict) else {}

    m = feedback_metrics(task, preds, actuals)
    dry = bool(context.get("_dry_run"))
    if not dry:
        def _save():
            with SessionLocal() as db:
                db.add(MlFeedbackBatch(user_id=uid, model_name=model, task_type=task, rows=m["rows"], metric=m["metric"],
                                       value=m["value"], details=m["details"], execution_id=context.get("_execution_id")))
                db.commit()
        await asyncio.to_thread(_save)

    below = thr is not None and ((m["value"] < thr) if m["metric"] == "accuracy" else (m["value"] > thr))
    report = {**m, "model": model, "task": task, "threshold": thr, "breached": bool(below), "recorded": not dry}
    out = {**passthrough, "feedback": report, "_usage": {"scanned_bytes": 0, "compute_s": 0}, "dry_run": dry,
           "timestamp": datetime.utcnow().isoformat()}
    if below and on_fail == "stop":
        want = f"at least {thr:g}" if m["metric"] == "accuracy" else f"at most {thr:g}"
        out["error"] = (f"'{model}' got worse: {m['metric']} is {m['value']:.3f} over {m['rows']:,} rows, expected {want}. "
                        "Consider retraining.")
    return out


# ── Registry Promote ────────────────────────────────────────────────────────────

def check_gates(gates: List[Dict[str, Any]], metrics: Dict[str, float]) -> List[Dict[str, Any]]:
    out = []
    for g in gates:
        name, op = (g.get("metric") or "").strip(), g.get("op", ">=")
        if not name:
            raise MlNodeError("Every gate needs a metric name")
        if op not in _OPS:
            raise MlNodeError(f"Gate operator must be one of: {', '.join(_OPS)}")
        try:
            want = float(g.get("value"))
        except (TypeError, ValueError):
            raise MlNodeError(f"Gate '{name}': the value must be a number")
        have = metrics.get(name)
        out.append({"metric": name, "op": op, "value": want, "actual": have,
                    "passed": have is not None and _OPS[op](have, want),
                    **({"note": f"the run has no metric called '{name}'"} if have is None else {})})
    return out


@_guard
async def run_registry_promote(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    uid = _user(context)
    cfg, mode, allow, conn_name = await asyncio.to_thread(_connection, uid, node_data.get("connectionId"), "mlflow")
    if mode != "read_write":
        raise MlNodeError(f"The connection '{conn_name}' is read-only, so it cannot change the registry. "
                          "Set its access to 'Read & write' on the Connections page if you want promotion.")
    model = check_model_name(node_data.get("modelName") or "")
    alias = check_alias(node_data.get("alias") or "")
    on_fail = node_data.get("onFail", "stop")
    if on_fail not in ("stop", "skip"):
        raise MlNodeError("'When a gate fails' must be 'stop' or 'skip'")
    client = mlflow_client(cfg, allow)

    want = str(node_data.get("version") or "latest").strip()
    want = _render(want, context)
    if want == "latest":
        versions = await client.versions(model)
        if not versions:
            raise MlNodeError(f"'{model}' has no versions in the registry")
        ver = versions[0]
    elif want.isdigit():
        ver = await client.version(model, want)
    else:
        raise MlNodeError("Version must be 'latest' or a version number")
    if ver.get("status") not in (None, "READY"):
        raise MlNodeError(f"Version {ver['version']} is not ready yet (status {ver.get('status')})")

    metrics = await client.run_metrics(ver.get("run_id"))
    gates = check_gates([g for g in (node_data.get("gates") or []) if isinstance(g, dict)], metrics)
    current = await client.alias_version(model, alias)
    if node_data.get("beatCurrent") and current and current != str(ver["version"]):
        m = (node_data.get("compareMetric") or "").strip()
        if not m:
            raise MlNodeError("Name the metric to compare with the current model")
        cur_metrics = await client.run_metrics((await client.version(model, current)).get("run_id"))
        higher = node_data.get("higherIsBetter", True)
        mine, theirs = metrics.get(m), cur_metrics.get(m)
        ok = mine is not None and theirs is not None and ((mine > theirs) if higher else (mine < theirs))
        gates.append({"metric": f"{m} vs current v{current}", "op": ">" if higher else "<", "value": theirs, "actual": mine, "passed": ok,
                      **({"note": "one of the runs has no such metric"} if mine is None or theirs is None else {})})

    failed = [g for g in gates if not g["passed"]]
    report = {"model": model, "version": str(ver["version"]), "alias": alias, "previous_version": current, "metrics": metrics,
              "gates": gates, "connection": conn_name}
    if failed:
        why = "; ".join(f"{g['metric']} {g['op']} {g['value']:g} (got {g['actual'] if g['actual'] is not None else 'nothing'})" for g in failed)
        if on_fail == "stop":
            return {**report, "promoted": False, "error": f"Promotion blocked for {model} v{ver['version']}: {why}",
                    "timestamp": datetime.utcnow().isoformat()}
        return {**report, "promoted": False, "reason": f"Skipped: {why}", "timestamp": datetime.utcnow().isoformat()}
    if current == str(ver["version"]):
        return {**report, "promoted": False, "reason": f"v{ver['version']} already has the alias '{alias}'",
                "timestamp": datetime.utcnow().isoformat()}
    await client.set_alias(model, alias, str(ver["version"]))
    return {**report, "promoted": True, "reason": f"'{alias}' now points to v{ver['version']}"
                                                  + (f" (was v{current})" if current else ""),
            "timestamp": datetime.utcnow().isoformat()}


def _render(text: str, context: Dict[str, Any]) -> str:
    rec = _flat(context.get("previous_output"))

    def sub(m: "re.Match[str]") -> str:
        val: Any = rec
        for part in m.group(1).strip().split("."):
            val = val.get(part) if isinstance(val, dict) else None
        return "" if val is None else str(val)
    return re.sub(r"\{\{([^}]+)\}\}", sub, text).strip()
