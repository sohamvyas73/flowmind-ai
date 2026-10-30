import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.ml import endpoints
from app.ml.mlflow_client import MlflowError
from app.models.ml import MlFeedbackBatch
from app.models.user import User
from app.services import ml_nodes

router = APIRouter()

MAX_MODELS = 30
VERSIONS_SHOWN = 5


def _fail(e: Exception, code: int = 422):
    raise HTTPException(status_code=code, detail=str(e))


@router.get("/connections/{connection_id}/models")
async def list_models(connection_id: UUID, user: User = Depends(get_current_user)):
    """Registered models, their recent versions, aliases and training metrics, from the user's MLflow connection."""
    try:
        cfg, mode, allow, name = await asyncio.to_thread(ml_nodes._connection, user.id, str(connection_id), "mlflow")
        client = ml_nodes.mlflow_client(cfg, allow)
        out: List[Dict[str, Any]] = []
        for m in (await client.list_models(MAX_MODELS)):
            aliases: Dict[str, str] = {a["alias"]: str(a["version"]) for a in (m.get("aliases") or [])}
            versions = []
            for v in (await client.versions(m["name"]))[:VERSIONS_SHOWN]:
                versions.append({
                    "version": str(v["version"]), "status": v.get("status"), "run_id": v.get("run_id"),
                    "created": v.get("creation_timestamp"), "metrics": await client.run_metrics(v.get("run_id")),
                    "aliases": sorted(a for a, ver in aliases.items() if ver == str(v["version"])),
                })
            out.append({"name": m["name"], "versions": versions, "aliases": aliases})
        return {"connection": name, "can_promote": mode == "read_write", "models": out}
    except (ml_nodes.MlNodeError, MlflowError) as e:
        _fail(e)


class ScoreIn(BaseModel):
    features: List[str] = Field(min_length=1)
    record: Dict[str, Any]


@router.post("/endpoints/{connection_id}/score")
async def try_endpoint(connection_id: UUID, body: ScoreIn, user: User = Depends(get_current_user)):
    """'Try it' for the Models page: score one record against the user's own endpoint."""
    try:
        cfg, _, allow, name = await asyncio.to_thread(ml_nodes._connection, user.id, str(connection_id), "ml_endpoint")
        missing = [f for f in body.features if f not in body.record]
        if missing:
            raise ml_nodes.MlNodeError(f"Missing value(s) for: {', '.join(missing)}")
        row = {f: ml_nodes._clean(ml_nodes._num(body.record[f])) for f in body.features}
        preds, ms = await endpoints.score_rows(cfg, [row], body.features, allow)
        return {"endpoint": name, "features": row, "prediction": preds[0]["prediction"],
                "probability": preds[0].get("prediction_proba"), "latency_ms": ms}
    except (ml_nodes.MlNodeError, endpoints.ScoreError) as e:
        _fail(e)


class FeedbackOut(BaseModel):
    id: UUID
    model_name: str
    task_type: str
    rows: int
    metric: str
    value: float
    details: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/feedback", response_model=List[FeedbackOut])
async def feedback_history(model: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Newest first: how each model's predictions compared with real outcomes, capture by capture."""
    q = db.query(MlFeedbackBatch).filter(MlFeedbackBatch.user_id == user.id)
    if model:
        q = q.filter(MlFeedbackBatch.model_name == model)
    return q.order_by(MlFeedbackBatch.created_at.desc()).limit(limit).all()
