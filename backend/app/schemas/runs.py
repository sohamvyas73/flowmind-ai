from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    workflow_id: UUID
    input_data: Optional[Dict[str, Any]] = None


class JobInfo(BaseModel):
    id: UUID
    state: str
    attempts: int
    max_attempts: int
    run_after: Optional[datetime] = None
    last_error: Optional[str] = None
    cancel_requested: bool = False


class RunSummary(BaseModel):
    execution_id: UUID
    workflow_id: UUID
    workflow_name: Optional[str] = None
    status: str
    triggered_by: Optional[str] = None
    schedule_id: Optional[UUID] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    job: Optional[JobInfo] = None


class RunDetail(RunSummary):
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    execution_trace: Optional[list] = None


class RunAccepted(BaseModel):
    execution_id: UUID
    job_id: UUID
    status: str


class ScheduleCreate(BaseModel):
    workflow_id: UUID
    name: str = Field("Schedule", min_length=1, max_length=255)
    cron: str
    timezone: str = "UTC"
    input_data: Optional[Dict[str, Any]] = None
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    cron: Optional[str] = None
    timezone: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ScheduleResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    workflow_name: Optional[str] = None
    name: str
    cron: str
    timezone: str
    enabled: bool
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_execution_id: Optional[UUID] = None
    input_data: Optional[Dict[str, Any]] = None
    created_at: datetime
