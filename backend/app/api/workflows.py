import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from uuid import UUID
from app.core.database import get_db
from app.core.secrets import extract_graph_secrets, dump_secrets, load_secrets
from app.core.auth import get_current_user
from app.models.workflow import Workflow, WorkflowExecution, ExecutionStatus
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    ExecutionCreate, ExecutionResponse, TriggerResponse
)
from app.services.run_service import get_owned_workflow, prepare_run, execute_prepared
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    clean_graph, node_secrets = extract_graph_secrets(workflow.graph_data.model_dump())
    db_workflow = Workflow(
        user_id=current_user.id,
        name=workflow.name,
        description=workflow.description,
        graph_data=clean_graph,
        secrets=dump_secrets(node_secrets),
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    return db_workflow


@router.get("/workflows", response_model=List[WorkflowResponse])
async def list_workflows(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Workflow)
    if current_user.role != "admin":
        q = q.filter(Workflow.user_id == current_user.id)
    return q.order_by(Workflow.updated_at.desc()).offset(skip).limit(limit).all()


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if current_user.role != "admin" and str(workflow.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return workflow


@router.put("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    workflow_update: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not db_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if current_user.role != "admin" and str(db_workflow.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = workflow_update.model_dump(exclude_unset=True)
    if update_data.get("graph_data") is not None:
        # "__secret__" placeholders keep the stored secret; new plaintext values get vaulted
        clean_graph, node_secrets = extract_graph_secrets(
            update_data["graph_data"], load_secrets(db_workflow.secrets)
        )
        update_data["graph_data"] = clean_graph
        db_workflow.secrets = dump_secrets(node_secrets)
    for field, value in update_data.items():
        setattr(db_workflow, field, value)

    db_workflow.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow updated | workflow_id=%s name=%r", workflow_id, db_workflow.name)
    return db_workflow


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if current_user.role != "admin" and str(workflow.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    db.query(Schedule).filter(Schedule.workflow_id == workflow_id).delete()
    deleted_executions = db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == workflow_id
    ).delete()
    db.delete(workflow)
    db.commit()
    logger.info(
        "Workflow deleted | workflow_id=%s | executions_removed=%d",
        workflow_id, deleted_executions,
    )
    return None


async def _run_inline(
    db: Session, user: User, workflow: Workflow, input_data: Optional[Dict[str, Any]], source: str, triggered_by: str,
) -> tuple:
    """Synchronous run: prepare, release the DB connection, execute, settle. Returns (execution_id, live_result)."""
    workflow_id = workflow.id
    execution_id, _ = prepare_run(db, user, workflow, input_data, triggered_by=triggered_by)
    db.close()
    logger.info("%s | workflow_id=%s execution=%s", source, workflow_id, execution_id)
    result = await execute_prepared(execution_id, input_data)
    return execution_id, result


@router.post("/workflows/{workflow_id}/execute", response_model=ExecutionResponse)
async def execute_workflow(
    workflow_id: UUID,
    execution_data: ExecutionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = get_owned_workflow(db, workflow_id, current_user)
    execution_id, _ = await _run_inline(db, current_user, workflow, execution_data.input_data, "EXECUTE", "manual")
    return db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()


@router.post("/workflows/{workflow_id}/trigger", response_model=TriggerResponse)
async def trigger_workflow(
    workflow_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = get_owned_workflow(db, workflow_id, current_user, "Access denied — use your own API token")

    try:
        input_data: Dict[str, Any] = await request.json()
    except Exception:
        input_data = {}

    execution_id, result = await _run_inline(db, current_user, workflow, input_data, "TRIGGER", "api")
    execution = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    # Callers get the real output; only the persisted copy is redacted
    live_output = result.get("review_data") if result.get("status") == "paused" else result.get("final_output")
    return TriggerResponse(
        workflow_id=workflow_id,
        execution_id=execution_id,
        status=execution.status.value,
        output=live_output if execution.status == ExecutionStatus.COMPLETED and isinstance(live_output, dict) else None,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    # Verify ownership via parent workflow
    if current_user.role != "admin":
        workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
        if not workflow or str(workflow.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Access denied")

    return execution


@router.get("/workflows/{workflow_id}/executions", response_model=List[ExecutionResponse])
async def list_workflow_executions(
    workflow_id: UUID,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if current_user.role != "admin" and str(workflow.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    return (
        db.query(WorkflowExecution)
        .filter(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.started_at.desc())
        .offset(skip).limit(limit).all()
    )
