"""Data quality checks ("quality gates").

A gate takes the table coming into it and a list of *rules*. Every row-level rule is turned into a SQL
predicate that is true for a **violating** row, so all rules are evaluated together in a single scan of the
data by the sandboxed engine; a second small query fetches a few masked example rows for each failed rule.
Schema rules need no data scan at all.

Rule types
----------
not_null        column                    no empty / NULL values
unique          columns | column          no duplicated values (NULLs ignored)
range           column, min?, max?        numbers or dates inside [min, max]
allowed_values  column, values            only the listed values
regex           column, pattern           text matches a regular expression (RE2 syntax)
max_null_pct    column, max               at most N percent empty
min_rows        value                     table has at least N rows
max_rows        value                     table has at most N rows
schema          expected, allowExtra?     required columns (and optionally types) exist
expression      expression, label?        custom SQL condition that must be TRUE for every row

Every rule may carry ``severity``: ``error`` (default — can stop the run) or ``warn`` (reported only).
"""
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.data.dataset import Column, build_dataset
from app.engine.duckdb_engine import EngineInput, qi, run_sql

RULE_TYPES = {
    "not_null", "unique", "range", "allowed_values", "regex", "max_null_pct",
    "min_rows", "max_rows", "schema", "expression",
}
MAX_RULES = 50
MAX_EXAMPLES = 5
MAX_ALLOWED_VALUES = 200
_NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
            "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL")
_INTEGER = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT")
_FAMILIES = {"integer", "number", "text", "boolean", "date", "timestamp"}


class QualityConfigError(ValueError):
    """A rule is mis-configured (unknown column, bad number…). The user must fix the node settings."""


@dataclass
class RuleResult:
    id: str
    type: str
    description: str
    severity: str
    status: str                      # pass | fail
    failed: int = 0                  # violating rows (or duplicated values / missing columns, depending on the rule)
    unit: str = "rows"
    message: str = ""
    examples: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "description": self.description, "severity": self.severity,
            "status": self.status, "failed": self.failed, "unit": self.unit, "message": self.message,
            "examples": self.examples, "columns": self.columns,
        }


# ── helpers ─────────────────────────────────────────────────────────────────────

def _lit(v: Any) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _is_numeric(t: str) -> bool:
    return (t or "").upper().startswith(_NUMERIC)


def _is_text(t: str) -> bool:
    return (t or "").upper().startswith("VARCHAR")


def _is_temporal(t: str) -> bool:
    u = (t or "").upper()
    return u.startswith("DATE") or u.startswith("TIMESTAMP")


def type_family(t: str) -> str:
    u = (t or "").upper()
    if u.startswith(_INTEGER):
        return "integer"
    if u.startswith(_NUMERIC):
        return "number"
    if u.startswith("VARCHAR"):
        return "text"
    if u.startswith("BOOL"):
        return "boolean"
    if u == "DATE":
        return "date"
    if u.startswith("TIMESTAMP"):
        return "timestamp"
    return u.lower()


def _types(cols: List[Dict[str, Any]]) -> Dict[str, str]:
    return {c["name"]: c.get("type", "") for c in cols}


def _need(types: Dict[str, str], col: Any, rule_label: str) -> str:
    if not col or col not in types:
        avail = ", ".join(list(types)[:15]) + ("…" if len(types) > 15 else "")
        raise QualityConfigError(f"{rule_label}: column '{col}' was not found. Available columns: {avail}")
    return col


def _columns_of(rule: Dict[str, Any]) -> List[str]:
    cols = rule.get("columns")
    if isinstance(cols, str):
        cols = [c.strip() for c in cols.split(",") if c.strip()]
    if not cols and rule.get("column"):
        cols = [rule["column"]]
    return list(cols or [])


def _number(v: Any, what: str, label: str) -> Optional[float]:
    if v is None or str(v).strip() == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise QualityConfigError(f"{label}: {what} must be a number (got {v!r})")
    if math.isnan(f) or math.isinf(f):
        raise QualityConfigError(f"{label}: {what} must be a finite number")
    return f


def _fmt_num(f: float) -> str:
    return str(int(f)) if float(f).is_integer() else str(f)


def _bound_sql(v: Any, col_type: str, label: str, what: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (sql literal, display text) for a range bound, for numeric or temporal columns."""
    if v is None or str(v).strip() == "":
        return None, None
    if _is_numeric(col_type):
        f = _number(v, what, label)
        return _fmt_num(f), _fmt_num(f)
    s = str(v).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", s):
        raise QualityConfigError(f"{label}: {what} must be a date like 2026-03-31 (got {v!r})")
    return f"CAST({_lit(s)} AS {col_type})", s


# ── describing and normalising ──────────────────────────────────────────────────

def describe(rule: Dict[str, Any]) -> str:
    t = rule.get("type")
    cols = ", ".join(_columns_of(rule))
    if t == "not_null":
        return f"{cols} must not be empty"
    if t == "unique":
        return f"{cols} must be unique"
    if t == "range":
        lo, hi = rule.get("min"), rule.get("max")
        has_lo, has_hi = str(lo or "").strip() != "", str(hi or "").strip() != ""
        if has_lo and has_hi:
            return f"{cols} must be between {lo} and {hi}"
        return f"{cols} must be {'at least ' + str(lo) if has_lo else 'at most ' + str(hi)}"
    if t == "allowed_values":
        vals = _allowed(rule)
        shown = ", ".join(vals[:6]) + ("…" if len(vals) > 6 else "")
        return f"{cols} must be one of: {shown}"
    if t == "regex":
        return f"{cols} must match {rule.get('pattern')}"
    if t == "max_null_pct":
        return f"{cols} may be at most {rule.get('max')}% empty"
    if t == "min_rows":
        return f"table must have at least {rule.get('value')} rows"
    if t == "max_rows":
        return f"table must have at most {rule.get('value')} rows"
    if t == "schema":
        exp = rule.get("expected") or []
        return "columns must match the contract: " + ", ".join(
            e["name"] + (f" ({e['type']})" if e.get("type") else "") for e in exp[:6]) + ("…" if len(exp) > 6 else "")
    if t == "expression":
        return rule.get("label") or f"condition holds: {rule.get('expression')}"
    return str(t)


def _allowed(rule: Dict[str, Any]) -> List[str]:
    v = rule.get("values")
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",")]
    return [str(x) for x in (v or []) if str(x).strip() != ""]


def normalise(rules: Any) -> List[Dict[str, Any]]:
    if not isinstance(rules, list) or not rules:
        raise QualityConfigError("Add at least one check")
    if len(rules) > MAX_RULES:
        raise QualityConfigError(f"Too many checks (max {MAX_RULES})")
    out = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or r.get("type") not in RULE_TYPES:
            raise QualityConfigError(f"Check {i + 1}: unknown type {r.get('type') if isinstance(r, dict) else r!r}")
        rr = dict(r)
        rr["id"] = str(rr.get("id") or f"r{i + 1}")
        sev = rr.get("severity") or "error"
        if sev not in ("error", "warn"):
            raise QualityConfigError(f"Check {i + 1}: severity must be 'error' or 'warn'")
        rr["severity"] = sev
        out.append(rr)
    ids = [r["id"] for r in out]
    if len(set(ids)) != len(ids):
        raise QualityConfigError("Check ids must be unique")
    return out


# ── SQL generation ──────────────────────────────────────────────────────────────

def _violation(rule: Dict[str, Any], types: Dict[str, str]) -> Optional[str]:
    """SQL predicate that is TRUE for a violating row (row-level rules only)."""
    t, label = rule["type"], describe(rule)
    if t == "not_null":
        cols = _columns_of(rule)
        if not cols:
            raise QualityConfigError(f"{label}: choose a column")
        parts = []
        for c in cols:
            _need(types, c, label)
            q = qi(c)
            parts.append(f"({q} IS NULL OR trim({q}) = '')" if _is_text(types[c]) else f"{q} IS NULL")
        return " OR ".join(parts)
    if t == "range":
        c = _need(types, rule.get("column"), label)
        if not (_is_numeric(types[c]) or _is_temporal(types[c])):
            raise QualityConfigError(f"{label}: '{c}' is {types[c]}; a range needs a number or date column")
        lo, _ = _bound_sql(rule.get("min"), types[c], label, "min")
        hi, _ = _bound_sql(rule.get("max"), types[c], label, "max")
        if lo is None and hi is None:
            raise QualityConfigError(f"{label}: give a minimum and/or a maximum")
        conds = []
        if lo is not None:
            conds.append(f"{qi(c)} < {lo}")
        if hi is not None:
            conds.append(f"{qi(c)} > {hi}")
        return f"{qi(c)} IS NOT NULL AND (" + " OR ".join(conds) + ")"
    if t == "allowed_values":
        c = _need(types, rule.get("column"), label)
        vals = _allowed(rule)
        if not vals:
            raise QualityConfigError(f"{label}: list at least one allowed value")
        if len(vals) > MAX_ALLOWED_VALUES:
            raise QualityConfigError(f"{label}: too many values (max {MAX_ALLOWED_VALUES})")
        lits = ", ".join(_lit(v) for v in vals)
        return f"{qi(c)} IS NOT NULL AND CAST({qi(c)} AS VARCHAR) NOT IN ({lits})"
    if t == "regex":
        c = _need(types, rule.get("column"), label)
        pat = str(rule.get("pattern") or "")
        if not pat:
            raise QualityConfigError(f"{label}: give a pattern")
        if len(pat) > 500:
            raise QualityConfigError(f"{label}: pattern is too long")
        try:
            re.compile(pat)
        except re.error as e:
            raise QualityConfigError(f"{label}: invalid pattern ({e})")
        return f"{qi(c)} IS NOT NULL AND NOT regexp_matches(CAST({qi(c)} AS VARCHAR), {_lit(pat)})"
    if t == "expression":
        expr = str(rule.get("expression") or "").strip().rstrip(";")
        if not expr:
            raise QualityConfigError(f"{label}: write a condition, e.g. quantity * unit_price > 0")
        if len(expr) > 1000 or ";" in expr:
            raise QualityConfigError(f"{label}: the condition must be one SQL expression")
        return f"NOT COALESCE(({expr}), FALSE)"
    return None


def _group_cols(rule: Dict[str, Any], types: Dict[str, str]) -> List[str]:
    cols = _columns_of(rule)
    label = describe(rule)
    if not cols:
        raise QualityConfigError(f"{label}: choose at least one column")
    for c in cols:
        _need(types, c, label)
    return cols


def build_checks(rules: List[Dict[str, Any]], cols: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """Return (the single aggregate SQL, per-rule plan). Raises QualityConfigError for bad settings."""
    types = _types(cols)
    selects = ["count(*) AS total"]
    plan: Dict[str, Dict[str, Any]] = {}
    for r in rules:
        rid, t = r["id"], r["type"]
        if t == "schema":
            plan[rid] = {"kind": "schema"}
            continue
        if t in ("min_rows", "max_rows"):
            v = _number(r.get("value"), "value", describe(r))
            if v is None or v < 0:
                raise QualityConfigError(f"{describe(r)}: give a row count")
            plan[rid] = {"kind": t, "value": int(v)}
            continue
        if t == "max_null_pct":
            c = _need(types, r.get("column"), describe(r))
            m = _number(r.get("max"), "max", describe(r))
            if m is None or not 0 <= m <= 100:
                raise QualityConfigError(f"{describe(r)}: max must be between 0 and 100")
            q = qi(c)
            cond = f"({q} IS NULL OR trim({q}) = '')" if _is_text(types[c]) else f"{q} IS NULL"
            selects.append(f"count(*) FILTER (WHERE {cond}) AS {qi(rid)}")
            plan[rid] = {"kind": "null_pct", "max": m, "violation": cond}
            continue
        if t == "unique":
            cs = _group_cols(r, types)
            notnull = " AND ".join(f"{qi(c)} IS NOT NULL" for c in cs)
            grp = ", ".join(qi(c) for c in cs)
            selects.append(
                f"(SELECT count(*) FROM (SELECT 1 FROM input WHERE {notnull} GROUP BY {grp} HAVING count(*) > 1)) AS {qi(rid)}"
            )
            plan[rid] = {"kind": "unique", "cols": cs, "notnull": notnull}
            continue
        v = _violation(r, types)
        selects.append(f"count(*) FILTER (WHERE {v}) AS {qi(rid)}")
        plan[rid] = {"kind": "rows", "violation": v}
    sql = "SELECT " + ",\n       ".join(selects) + "\nFROM input"
    return sql, plan


# ── schema contract ─────────────────────────────────────────────────────────────

def check_schema(rule: Dict[str, Any], cols: List[Dict[str, Any]]) -> RuleResult:
    types = _types(cols)
    expected = rule.get("expected") or []
    if not expected:
        raise QualityConfigError("schema: list the expected columns")
    problems: List[str] = []
    for e in expected:
        name, want = e.get("name"), (e.get("type") or "").strip()
        if name not in types:
            problems.append(f"missing column '{name}'")
            continue
        if want:
            fam = want.lower()
            actual = type_family(types[name])
            ok = (fam == actual) or (fam == "number" and actual in ("integer", "number")) \
                or types[name].upper().startswith(want.upper())
            if not ok:
                problems.append(f"'{name}' is {types[name]}, expected {want}")
    if not rule.get("allowExtra", True):
        names = {e.get("name") for e in expected}
        extra = [c for c in types if c not in names]
        if extra:
            problems.append("unexpected columns: " + ", ".join(extra[:8]))
    return RuleResult(
        rule["id"], "schema", describe(rule), rule["severity"], "pass" if not problems else "fail",
        failed=len(problems), unit="problems", message="; ".join(problems),
    )


# ── evaluation ──────────────────────────────────────────────────────────────────

async def evaluate(
    rules_in: Any, columns: List[Dict[str, Any]], data_path: str, out_dir: str, *, data_format: str = "parquet",
) -> Dict[str, Any]:
    """Run all rules over the table and return a report dict. Raises QualityConfigError for bad settings."""
    rules = normalise(rules_in)
    sql, plan = build_checks(rules, columns)

    tmp = os.path.join(out_dir, f"{uuid.uuid4()}.q.parquet")
    res = await run_sql([EngineInput("input", data_path, data_format)], sql, tmp, sample_rows=1)
    _rm(tmp)
    row = res.sample[0] if res.sample else {}
    total = int(row.get("total", 0))

    results: List[RuleResult] = []
    to_sample: List[Tuple[RuleResult, Dict[str, Any]]] = []
    for r in rules:
        rid, p = r["id"], plan[r["id"]]
        desc, sev = describe(r), r["severity"]
        kind = p["kind"]
        if kind == "schema":
            results.append(check_schema(r, columns))
            continue
        if kind in ("min_rows", "max_rows"):
            bad = total < p["value"] if kind == "min_rows" else total > p["value"]
            results.append(RuleResult(rid, r["type"], desc, sev, "fail" if bad else "pass", failed=1 if bad else 0,
                                      unit="table", message=f"table has {total:,} rows" if bad else ""))
            continue
        failed = int(row.get(rid, 0) or 0)
        if kind == "null_pct":
            pct = (100.0 * failed / total) if total else 0.0
            bad = pct > p["max"]
            res_ = RuleResult(rid, r["type"], desc, sev, "fail" if bad else "pass", failed=failed,
                              message=f"{pct:.1f}% empty ({failed:,} of {total:,} rows)" if bad else "")
        elif kind == "unique":
            res_ = RuleResult(rid, r["type"], desc, sev, "fail" if failed else "pass", failed=failed, unit="duplicated values",
                              message=f"{failed:,} value(s) appear more than once" if failed else "")
        else:
            res_ = RuleResult(rid, r["type"], desc, sev, "fail" if failed else "pass", failed=failed,
                              message=f"{failed:,} of {total:,} rows break this rule" if failed else "")
        results.append(res_)
        if res_.status == "fail" and kind in ("rows", "unique", "null_pct") and len(to_sample) < 6:
            to_sample.append((res_, p))

    await _attach_examples(to_sample, columns, data_path, data_format, out_dir)
    by_id = {r["id"]: r for r in rules}
    for x in results:
        x.columns = _columns_of(by_id[x.id])

    errors = [x for x in results if x.status == "fail" and x.severity == "error"]
    warnings = [x for x in results if x.status == "fail" and x.severity == "warn"]
    return {
        "passed": not errors,
        "total_rows": total,
        "checks": len(results),
        "failed_errors": len(errors),
        "failed_warnings": len(warnings),
        "rules": [x.to_dict() for x in results],
        "sql": sql,
        "usage": {"compute_s": res.compute_s, "scanned_bytes": res.scanned_bytes, "scanned_rows": res.scanned_rows},
    }


async def _attach_examples(
    items: List[Tuple[RuleResult, Dict[str, Any]]], columns: List[Dict[str, Any]], path: str, fmt: str, out_dir: str,
) -> None:
    """Fetch a few example offending rows per failed rule (masked like every other preview)."""
    for res_, p in items:
        if p["kind"] == "unique":
            grp = ", ".join(qi(c) for c in p["cols"])
            q = (f"SELECT {grp}, count(*) AS times_seen FROM input WHERE {p['notnull']} "
                 f"GROUP BY {grp} HAVING count(*) > 1 ORDER BY times_seen DESC LIMIT {MAX_EXAMPLES}")
            cols_meta = [c for c in columns if c["name"] in p["cols"]] + [{"name": "times_seen", "type": "BIGINT"}]
        else:
            q = f"SELECT * FROM input WHERE {p['violation']} LIMIT {MAX_EXAMPLES}"
            cols_meta = columns
        tmp = os.path.join(out_dir, f"{uuid.uuid4()}.ex.parquet")
        try:
            r = await run_sql([EngineInput("input", path, fmt)], q, tmp, sample_rows=MAX_EXAMPLES)
        except Exception:  # examples are a convenience; never fail the check because of them
            continue
        finally:
            _rm(tmp)
        ref = build_dataset([Column(name=c["name"], type=c.get("type", "")) for c in cols_meta], r.sample,
                            sample_limit=MAX_EXAMPLES)
        res_.examples = ref.sample


def _rm(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def summarise(report: Dict[str, Any], label: str) -> str:
    """One readable sentence for run history / error messages."""
    bad = [r for r in report["rules"] if r["status"] == "fail" and r["severity"] == "error"]
    parts = []
    for r in bad[:4]:
        detail = r["message"] or f"{r['failed']} {r['unit']}"
        parts.append(f"{r['description']} ({detail})")
    more = f" and {len(bad) - 4} more" if len(bad) > 4 else ""
    return f"{len(bad)} of {report['checks']} quality checks did not pass — " + "; ".join(parts) + more
