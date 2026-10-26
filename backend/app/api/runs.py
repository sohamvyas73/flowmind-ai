import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.jobs.queue import queue
from app.models.job import Job
from app.models.user import User
from app.models.workflow import ExecutionStatus, Workflow, WorkflowExecution
from app.schemas.runs import JobInfo, RunAccepted, RunCreate, RunDetail, RunSummary
from app.services.run_service import get_owned_workflow, prepare_run

logger = logging.getLogger(__name__)
router = APIRouter()


def _job_for(db: Session, execution_id) -> Optional[Job]:
    return (
        db.query(Job).filter(Job.execution_id == execution_id).order_by(Job.created_at.desc()).first()
    )


def _job_info(j: Optional[Job]) -> Optional[JobInfo]:
    if j is None:
        return None
    return JobInfo(
        id=j.id, state=j.state, attempts=j.attempts, max_attempts=j.max_attempts,
        run_after=j.run_after, last_error=j.last_error, cancel_requested=j.cancel_requested,
    )


def _summary(db: Session, ex: WorkflowExecution, wf_name: Optional[str]) -> dict:
    return dict(
        execution_id=ex.id, workflow_id=ex.workflow_id, workflow_name=wf_name,
        status=ex.status.value if hasattr(ex.status, "value") else str(ex.status),
        triggered_by=ex.triggered_by, schedule_id=ex.schedule_id,
        started_at=ex.started_at, completed_at=ex.completed_at, error_message=ex.error_message,
        job=_job_info(_job_for(db, ex.id)),
    )


def _owned_execution(db: Session, execution_id: UUID, user: User):
    ex = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    if ex is None:
        raise HTTPException(status_code=404, detail="Run not found")
    wf = db.query(Workflow).filter(Workflow.id == ex.workflow_id).first()
    if user.role != "admin" and (wf is None or str(wf.user_id) != str(user.id)):
        raise HTTPException(status_code=403, detail="Access denied")
    return ex, wf


@router.post("", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    body: RunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a workflow in the background. Poll GET /runs/{execution_id} for progress."""
    workflow = get_owned_workflow(db, body.workflow_id, current_user)
    execution_id, job_id = prepare_run(
        db, current_user, workflow, body.input_data, triggered_by="background", enqueue=True,
    )
    return RunAccepted(execution_id=execution_id, job_id=job_id, status=ExecutionStatus.PENDING.value)


@router.get("", response_model=List[RunSummary])
async def list_runs(
    workflow_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(WorkflowExecution, Workflow.name).join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
    if current_user.role != "admin":
        q = q.filter(Workflow.user_id == current_user.id)
    if workflow_id:
        q = q.filter(WorkflowExecution.workflow_id == workflow_id)
    if status_filter:
        try:
            q = q.filter(WorkflowExecution.status == ExecutionStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown status")
    rows = q.order_by(WorkflowExecution.started_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [RunSummary(**_summary(db, ex, name)) for ex, name in rows]


@router.get("/{execution_id}", response_model=RunDetail)
async def get_run(
    execution_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ex, wf = _owned_execution(db, execution_id, current_user)
    return RunDetail(
        **_summary(db, ex, wf.name if wf else None),
        input_data=ex.input_data, output_data=ex.output_data, execution_trace=ex.execution_trace,
    )


@router.post("/{execution_id}/cancel", response_model=RunSummary)
async def cancel_run(
    execution_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a queued run immediately, or ask a running one to stop. Reserved credits are refunded."""
    ex, wf = _owned_execution(db, execution_id, current_user)
    job = _job_for(db, ex.id)
    if job is None or ex.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="Run is not cancellable (already finished, or not a background run)")
    state = queue.cancel(job.id)
    if state == "cancelled":  # was still queued: nothing running, finalise now
        from app.services.run_service import abort_execution
        abort_execution(ex.id, "Cancelled by user", cancelled=True)
    db.expire_all()
    ex = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    return RunSummary(**_summary(db, ex, wf.name if wf else None))
