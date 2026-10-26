import json
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.secrets import decrypt
from app.jobs.scheduler import CronError, validate_cron
from app.models.schedule import Schedule
from app.models.user import User
from app.models.workflow import Workflow
from app.schemas.runs import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from app.services.run_service import get_owned_workflow

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(s: Schedule, wf_name: Optional[str]) -> ScheduleResponse:
    raw = decrypt(s.input_data)
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    return ScheduleResponse(
        id=s.id, workflow_id=s.workflow_id, workflow_name=wf_name, name=s.name, cron=s.cron,
        timezone=s.timezone, enabled=s.enabled, next_run_at=s.next_run_at, last_run_at=s.last_run_at,
        last_status=s.last_status, last_execution_id=s.last_execution_id, input_data=data,
        created_at=s.created_at,
    )


def _owned(db: Session, schedule_id: UUID, user: User) -> Schedule:
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if s is None or (user.role != "admin" and str(s.user_id) != str(user.id)):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return s


@router.get("", response_model=List[ScheduleResponse])
async def list_schedules(
    workflow_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Schedule, Workflow.name).outerjoin(Workflow, Workflow.id == Schedule.workflow_id)
    if current_user.role != "admin":
        q = q.filter(Schedule.user_id == current_user.id)
    if workflow_id:
        q = q.filter(Schedule.workflow_id == workflow_id)
    return [_to_response(s, n) for s, n in q.order_by(Schedule.created_at.desc()).all()]


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = get_owned_workflow(db, body.workflow_id, current_user)
    if db.query(Schedule).filter(Schedule.user_id == current_user.id).count() >= settings.MAX_SCHEDULES_PER_USER:
        raise HTTPException(status_code=409, detail=f"Schedule limit reached ({settings.MAX_SCHEDULES_PER_USER})")
    try:
        first = validate_cron(body.cron, body.timezone)
    except CronError as e:
        raise HTTPException(status_code=422, detail=str(e))
    s = Schedule(
        user_id=current_user.id, workflow_id=workflow.id, name=body.name, cron=body.cron.strip(),
        timezone=body.timezone, enabled=body.enabled, next_run_at=first if body.enabled else None,
        input_data=json.dumps(body.input_data) if body.input_data else None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_response(s, workflow.name)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = _owned(db, schedule_id, current_user)
    data = body.model_dump(exclude_unset=True)
    cron = (data.get("cron") or s.cron).strip()
    tz = data.get("timezone") or s.timezone
    try:
        first = validate_cron(cron, tz)
    except CronError as e:
        raise HTTPException(status_code=422, detail=str(e))
    s.cron, s.timezone = cron, tz
    if "name" in data and data["name"]:
        s.name = data["name"]
    if "input_data" in data:
        s.input_data = json.dumps(data["input_data"]) if data["input_data"] else None
    if "enabled" in data and data["enabled"] is not None:
        s.enabled = data["enabled"]
    s.next_run_at = first if s.enabled else None
    db.commit()
    db.refresh(s)
    wf = db.query(Workflow).filter(Workflow.id == s.workflow_id).first()
    return _to_response(s, wf.name if wf else None)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = _owned(db, schedule_id, current_user)
    db.delete(s)
    db.commit()
    return None
