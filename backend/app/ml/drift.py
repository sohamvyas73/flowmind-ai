"""Data drift: Population Stability Index (PSI) per column between a reference (training) table and a current table.

PSI < 0.1 is stable, 0.1–0.25 a moderate shift, ≥ 0.25 a significant shift (the industry rule of thumb).
Pure functions, no I/O: easy to test and to reason about.
"""
import math
from collections import Counter
from typing import Any, Dict, List, Sequence

import numpy as np

EPS = 1e-4
BINS = 10
MAX_CATEGORIES = 20


class DriftConfigError(Exception):
    pass


def _psi(ref_counts: Sequence[float], cur_counts: Sequence[float]) -> float:
    rt, ct = float(sum(ref_counts)) or 1.0, float(sum(cur_counts)) or 1.0
    total = 0.0
    for r, c in zip(ref_counts, cur_counts):
        rp, cp = max(r / rt, EPS), max(c / ct, EPS)
        total += (cp - rp) * math.log(cp / rp)
    return total


def numeric_psi(ref: np.ndarray, cur: np.ndarray) -> Dict[str, Any]:
    """Quantile bins from the reference; a separate bucket for missing values."""
    rv, cv = ref[~np.isnan(ref)], cur[~np.isnan(cur)]
    if rv.size == 0 or cv.size == 0:
        raise DriftConfigError("a column has no numeric values to compare")
    edges = np.unique(np.quantile(rv, np.linspace(0, 1, BINS + 1)[1:-1]))
    r_hist = np.bincount(np.searchsorted(edges, rv, side="right"), minlength=len(edges) + 1)
    c_hist = np.bincount(np.searchsorted(edges, cv, side="right"), minlength=len(edges) + 1)
    r_all = list(r_hist) + [int(np.isnan(ref).sum())]
    c_all = list(c_hist) + [int(np.isnan(cur).sum())]
    return {
        "psi": _psi(r_all, c_all),
        "reference": {"mean": float(rv.mean()), "std": float(rv.std()), "missing": int(np.isnan(ref).sum())},
        "current": {"mean": float(cv.mean()), "std": float(cv.std()), "missing": int(np.isnan(cur).sum())},
    }


def category_psi(ref: Sequence[Any], cur: Sequence[Any]) -> Dict[str, Any]:
    rc = Counter("(missing)" if v is None else str(v) for v in ref)
    cc = Counter("(missing)" if v is None else str(v) for v in cur)
    keep = [k for k, _ in rc.most_common(MAX_CATEGORIES) if k != "(missing)"]
    cats = keep + ["(other)", "(missing)"]

    def fold(c: Counter) -> List[int]:
        known = sum(c.get(k, 0) for k in keep) + c.get("(missing)", 0)
        return [c.get(k, 0) for k in keep] + [sum(c.values()) - known, c.get("(missing)", 0)]
    r_all, c_all = fold(rc), fold(cc)
    rt, ct = sum(rc.values()) or 1, sum(cc.values()) or 1
    # explain with the real values (including brand-new ones), not the folded buckets used for the score
    moved = sorted(((abs(cc.get(k, 0) / ct - rc.get(k, 0) / rt), k, rc.get(k, 0) / rt, cc.get(k, 0) / ct)
                    for k in set(rc) | set(cc)), reverse=True)[:3]
    return {
        "psi": _psi(r_all, c_all),
        "reference": {"categories": len(rc)},
        "current": {"categories": len(cc)},
        "top_changes": [{"value": k, "reference_share": round(a, 4), "current_share": round(b, 4)} for _, k, a, b in moved],
    }


def status_for(psi: float, warn: float, alert: float) -> str:
    return "drift" if psi >= alert else "warning" if psi >= warn else "ok"


def compare(ref: Dict[str, Any], cur: Dict[str, Any], kinds: Dict[str, str], *, warn: float = 0.1, alert: float = 0.25) -> Dict[str, Any]:
    if not 0 < warn < alert:
        raise DriftConfigError("Warning threshold must be above 0 and below the drift threshold")
    cols: List[Dict[str, Any]] = []
    for name, kind in kinds.items():
        d = numeric_psi(ref[name], cur[name]) if kind == "numeric" else category_psi(ref[name], cur[name])
        d.update(name=name, kind=kind, psi=round(d["psi"], 4), status=status_for(d["psi"], warn, alert))
        cols.append(d)
    cols.sort(key=lambda c: c["psi"], reverse=True)
    drifted = [c["name"] for c in cols if c["status"] == "drift"]
    warned = [c["name"] for c in cols if c["status"] == "warning"]
    return {
        "columns": cols, "max_psi": cols[0]["psi"] if cols else 0.0, "drifted": drifted, "warned": warned,
        "warn_threshold": warn, "alert_threshold": alert,
        "status": "drift" if drifted else "warning" if warned else "ok",
    }


def summarise(rep: Dict[str, Any], label: str) -> str:
    worst = rep["columns"][0]
    return (f"Data drift in '{label}': {len(rep['drifted'])} of {len(rep['columns'])} column(s) shifted significantly "
            f"({', '.join(rep['drifted'][:5])}); worst is '{worst['name']}' with PSI {worst['psi']} "
            f"(limit {rep['alert_threshold']}).")
