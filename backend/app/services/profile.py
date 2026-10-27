"""Column profiling and suggested quality checks.

One aggregate query computes, per column: empty count, distinct count, min, max (and mean for numbers).
From that we propose sensible checks ("order_id is never empty and unique", "quantity stays between 1 and 4",
"status is one of 3 values") so people who don't know what to check can start from a good draft.
Columns tagged as personal data never have their min / max / values exposed.
"""
import math
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set

from app.engine.duckdb_engine import EngineInput, qi, run_sql

MAX_PROFILE_COLUMNS = 100
MAX_ALLOWED_CANDIDATE = 8
_ID_NAME = re.compile(r"(^|_)(id|key|code|number|no|uuid|ref)$", re.I)
_NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
            "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL")


def _is_num(t: str) -> bool:
    return (t or "").upper().startswith(_NUMERIC)


def _is_text(t: str) -> bool:
    return (t or "").upper().startswith("VARCHAR")


def _tidy(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return int(v) if v.is_integer() else round(v, 4)
    return v


async def profile(
    path: str, fmt: str, columns: List[Dict[str, Any]], out_dir: str, pii: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    pii = pii or set()
    cols = columns[:MAX_PROFILE_COLUMNS]
    selects = ["count(*) AS total"]
    for i, c in enumerate(cols):
        q, t = qi(c["name"]), c.get("type", "")
        empty = f"({q} IS NULL OR trim({q}) = '')" if _is_text(t) else f"{q} IS NULL"
        selects += [
            f"count(*) FILTER (WHERE {empty}) AS n{i}",
            f"count(DISTINCT {q}) AS d{i}",
            f"left(CAST(min({q}) AS VARCHAR), 40) AS lo{i}",
            f"left(CAST(max({q}) AS VARCHAR), 40) AS hi{i}",
        ]
        if _is_num(t):
            selects.append(f"avg({q}) AS a{i}")
    sql = "SELECT " + ", ".join(selects) + " FROM input"
    tmp = os.path.join(out_dir, f"{uuid.uuid4()}.p.parquet")
    try:
        res = await run_sql([EngineInput("input", path, fmt)], sql, tmp, sample_rows=1)
    finally:
        _rm(tmp)
    row = res.sample[0]
    total = int(row["total"])

    out_cols: List[Dict[str, Any]] = []
    for i, c in enumerate(cols):
        nulls, distinct = int(row[f"n{i}"]), int(row[f"d{i}"])
        is_pii = c["name"] in pii
        entry = {
            "name": c["name"], "type": c.get("type", ""), "nulls": nulls,
            "null_pct": round(100.0 * nulls / total, 1) if total else 0.0, "distinct": distinct,
            "min": None if is_pii else row[f"lo{i}"], "max": None if is_pii else row[f"hi{i}"],
            "mean": None if is_pii or f"a{i}" not in row else _tidy(row[f"a{i}"]), "pii": is_pii,
        }
        out_cols.append(entry)

    values = await _low_cardinality_values(path, fmt, cols, out_cols, total, out_dir, pii)
    return {
        "total_rows": total,
        "columns": out_cols,
        "suggested_rules": suggest(total, out_cols, values),
        "usage": {"compute_s": res.compute_s, "scanned_bytes": res.scanned_bytes, "scanned_rows": res.scanned_rows},
    }


async def _low_cardinality_values(path, fmt, cols, stats, total, out_dir, pii) -> Dict[str, List[str]]:
    cand = [
        s["name"] for s, c in zip(stats, cols)
        if _is_text(c.get("type", "")) and 0 < s["distinct"] <= MAX_ALLOWED_CANDIDATE and total >= 10 and s["name"] not in pii
    ]
    if not cand:
        return {}
    sel = [f"(SELECT list(DISTINCT CAST({qi(n)} AS VARCHAR) ORDER BY CAST({qi(n)} AS VARCHAR)) "
           f"FROM input WHERE {qi(n)} IS NOT NULL AND trim({qi(n)}) <> '') AS v{i}" for i, n in enumerate(cand)]
    tmp = os.path.join(out_dir, f"{uuid.uuid4()}.p2.parquet")
    try:
        res = await run_sql([EngineInput("input", path, fmt)], "SELECT " + ", ".join(sel) + " FROM input LIMIT 1", tmp, sample_rows=1)
    except Exception:
        return {}
    finally:
        _rm(tmp)
    row = res.sample[0] if res.sample else {}
    return {n: [str(x) for x in (row.get(f"v{i}") or [])] for i, n in enumerate(cand)}


def suggest(total: int, cols: List[Dict[str, Any]], values: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    if total >= 1:
        rules.append({"type": "min_rows", "value": 1, "reason": "The table should not be empty"})
    for c in cols:
        n, t = c["name"], c["type"]
        looks_id = bool(_ID_NAME.search(n))
        if total >= 1 and c["nulls"] == 0 and (looks_id or c["distinct"] == total):
            rules.append({"type": "not_null", "column": n, "reason": f"'{n}' is never empty in this data"})
        elif 0 < c["null_pct"] and not looks_id:
            limit = min(100, int(math.ceil(c["null_pct"])) + 5)
            rules.append({"type": "max_null_pct", "column": n, "max": limit, "severity": "warn",
                          "reason": f"'{n}' is {c['null_pct']}% empty now; warn if it gets worse"})
        if total >= 5 and looks_id and c["distinct"] == total:
            rules.append({"type": "unique", "columns": [n], "reason": f"every '{n}' is different in this data"})
        if _is_num(t) and not looks_id and not c["pii"] and c["min"] is not None and c["max"] is not None and total >= 5:
            rules.append({"type": "range", "column": n, "min": c["min"], "max": c["max"], "severity": "warn",
                          "reason": f"'{n}' currently ranges from {c['min']} to {c['max']} — widen if that's too tight"})
        if n in values and values[n] and len(values[n]) >= 2:
            rules.append({"type": "allowed_values", "column": n, "values": values[n],
                          "reason": f"'{n}' only has these {len(values[n])} values today"})
    return rules[:25]


def _rm(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
