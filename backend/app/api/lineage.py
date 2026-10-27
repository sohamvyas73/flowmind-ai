import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.lineage import openlineage as ol
from app.models.lineage import LineageEvent
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution

logger = logging.getLogger(__name__)
router = APIRouter()


def _owned(db: Session, execution_id: UUID, user: User):
    ex = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    if ex is None:
        raise HTTPException(status_code=404, detail="Run not found")
    wf = db.query(Workflow).filter(Workflow.id == ex.workflow_id).first()
    if user.role != "admin" and (wf is None or str(wf.user_id) != str(user.id)):
        raise HTTPException(status_code=403, detail="Access denied")
    return ex, wf


@router.get("/runs/{execution_id}")
async def run_lineage(execution_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """What each data step of a run read and produced, and whether its quality checks passed."""
    ex, wf = _owned(db, execution_id, user)
    labels = {n["id"]: (n.get("data") or {}).get("label", n["id"]) for n in ((wf.graph_data or {}).get("nodes", []) if wf else [])}
    count = db.query(LineageEvent).filter(LineageEvent.execution_id == execution_id).count()
    return {
        "execution_id": str(execution_id),
        "workflow": wf.name if wf else None,
        "status": ex.status.value if hasattr(ex.status, "value") else str(ex.status),
        "steps": ol.lineage_summary(ex.execution_trace or [], labels),
        "events": count,
    }


@router.get("/runs/{execution_id}/events")
async def run_events(execution_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """The run's OpenLineage RunEvents (standard JSON, ready to send to Marquez / DataHub / OpenMetadata)."""
    _owned(db, execution_id, user)
    rows = (
        db.query(LineageEvent).filter(LineageEvent.execution_id == execution_id)
        .order_by(LineageEvent.event_time, LineageEvent.created_at).all()
    )
    return [r.payload for r in rows]
