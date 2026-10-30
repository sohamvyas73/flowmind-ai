"""Call a customer's model-scoring endpoint (MLflow `mlflow models serve`, or any JSON-over-HTTP scorer).

FlowMind never loads or runs model code itself: the model lives behind the customer's endpoint, so a registry artifact
cannot execute inside this process.
"""
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from app.core.url_safety import UnsafeURLError, safe_request

INPUT_FORMATS = ["mlflow_records", "mlflow_split", "records"]
MAX_BATCH = 1000


class ScoreError(Exception):
    """A user-facing scoring failure."""


def auth_headers(config: Dict[str, Any]) -> Dict[str, str]:
    token = config.get("token")
    if not token:
        return {}
    if config.get("auth_type") == "header":
        return {config.get("header_name") or "X-API-Key": token}
    return {"Authorization": f"Bearer {token}"}


def build_payload(fmt: str, rows: List[Dict[str, Any]], features: List[str]) -> Dict[str, Any]:
    if fmt == "mlflow_split":
        return {"dataframe_split": {"columns": features, "data": [[r.get(f) for f in features] for r in rows]}}
    if fmt == "records":
        return {"records": rows}
    return {"dataframe_records": rows}


def parse_predictions(body: Any, expected: int) -> List[Dict[str, Any]]:
    """Normalise a scorer response to [{prediction, prediction_proba?}], one per input row."""
    preds = body.get("predictions", body.get("outputs")) if isinstance(body, dict) else body
    if not isinstance(preds, list):
        raise ScoreError("The endpoint did not return a list of predictions (expected {\"predictions\": [...]})")
    if len(preds) != expected:
        raise ScoreError(f"The endpoint returned {len(preds)} predictions for {expected} rows")
    out = []
    for p in preds:
        if isinstance(p, list) and p and all(isinstance(x, (int, float)) for x in p):
            top = max(range(len(p)), key=lambda i: p[i])         # class probabilities → winning class + confidence
            out.append({"prediction": top, "prediction_proba": float(p[top])})
        elif isinstance(p, dict) and "prediction" in p:
            out.append({"prediction": p["prediction"], **({"prediction_proba": float(p["probability"])} if "probability" in p else {})})
        elif isinstance(p, (int, float, str, bool)) or p is None:
            out.append({"prediction": p})
        else:
            raise ScoreError("The endpoint returned a prediction shape FlowMind cannot read (use a number, text or a probability list)")
    return out


async def score_rows(config: Dict[str, Any], rows: List[Dict[str, Any]], features: List[str],
                     allow_hosts: Iterable[str]) -> Tuple[List[Dict[str, Any]], int]:
    if not rows:
        return [], 0
    if len(rows) > MAX_BATCH:
        raise ScoreError(f"At most {MAX_BATCH} rows per request")
    payload = build_payload(config.get("input_format") or "mlflow_records", rows, features)
    t0 = time.monotonic()
    try:
        r = await safe_request("POST", config["url"], timeout=60, allow_hosts=allow_hosts,
                               headers={**auth_headers(config), "Content-Type": "application/json"}, json=payload)
    except UnsafeURLError as e:
        raise ScoreError(str(e))
    except httpx.HTTPError as e:
        raise ScoreError(f"Could not reach the model endpoint: {type(e).__name__}")
    ms = int((time.monotonic() - t0) * 1000)
    if r.status_code >= 400:
        raise ScoreError(f"The model endpoint returned HTTP {r.status_code}: {r.text[:200]}")
    try:
        body = r.json()
    except ValueError:
        raise ScoreError("The model endpoint did not return JSON")
    return parse_predictions(body, len(rows)), ms


async def endpoint_health(config: Dict[str, Any], allow_hosts: Iterable[str]) -> Dict[str, Any]:
    parts = urlsplit(config["url"])
    path = config.get("health_path") or "/ping"
    url = f"{parts.scheme}://{parts.netloc}/{path.lstrip('/')}"
    t0 = time.monotonic()
    try:
        r = await safe_request("GET", url, timeout=10, allow_hosts=allow_hosts, headers=auth_headers(config))
    except UnsafeURLError as e:
        return {"ok": False, "message": str(e)}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Could not reach the endpoint: {type(e).__name__}"}
    return {"ok": r.status_code < 400, "message": f"HTTP {r.status_code} from {path}",
            "latency_ms": int((time.monotonic() - t0) * 1000)}
