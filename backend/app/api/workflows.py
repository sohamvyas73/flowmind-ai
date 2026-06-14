import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from uuid import UUID
from app.core.database import get_db
from app.models.workflow import Workflow, WorkflowExecution, ExecutionStatus
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    ExecutionCreate, ExecutionResponse, TriggerResponse
)
from app.services.workflow_executor import WorkflowExecutor
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()
workflow_executor = WorkflowExecutor()

@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(workflow: WorkflowCreate, db: Session = Depends(get_db)):
    """Create a new workflow"""
    db_workflow = Workflow(
        name=workflow.name,
        description=workflow.description,
        graph_data=workflow.graph_data.dict()
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)
    return db_workflow

@router.get("/workflows", response_model=List[WorkflowResponse])
async def list_workflows(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all workflows"""
    workflows = db.query(Workflow).offset(skip).limit(limit).all()
    return workflows

@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: UUID, db: Session = Depends(get_db)):
    """Get a specific workflow"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow

@router.put("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(workflow_id: UUID, workflow_update: WorkflowUpdate, db: Session = Depends(get_db)):
    """Update a workflow"""
    db_workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not db_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # model_dump() in Pydantic v2 already serializes nested models to plain dicts
    update_data = workflow_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_workflow, field, value)

    db_workflow.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_workflow)
    logger.info("Workflow updated | workflow_id=%s name=%r", workflow_id, db_workflow.name)
    return db_workflow

@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, db: Session = Depends(get_db)):
    """Delete a workflow and all its executions"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    deleted_executions = db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == workflow_id
    ).delete()
    db.delete(workflow)
    db.commit()
    logger.info("Workflow deleted | workflow_id=%s | executions_removed=%d", workflow_id, deleted_executions)
    return None

@router.post("/workflows/{workflow_id}/execute", response_model=ExecutionResponse)
async def execute_workflow(workflow_id: UUID, execution_data: ExecutionCreate, db: Session = Depends(get_db)):
    """Execute a workflow"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    logger.info("EXECUTE request | workflow_id=%s name=%r", workflow_id, workflow.name)

    execution = WorkflowExecution(
        workflow_id=workflow_id,
        status=ExecutionStatus.RUNNING,
        input_data=execution_data.input_data,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    logger.info("Execution record created | execution_id=%s", execution.id)

    try:
        result = await workflow_executor.execute_workflow(
            workflow.graph_data,
            execution_data.input_data,
        )
        if result.get("status") == "failed":
            execution.status = ExecutionStatus.FAILED
            execution.error_message = (
                f"Node '{result.get('failed_node_label', result.get('failed_node_id'))}' "
                f"failed: {result.get('error')}"
            )
            execution.execution_trace = result.get("execution_trace")
            execution.completed_at = datetime.utcnow()
            logger.error("Execution FAILED (node error) | execution_id=%s | %s", execution.id, execution.error_message)
        elif result.get("status") == "paused":
            execution.status = ExecutionStatus.COMPLETED
            execution.output_data = result.get("review_data")
            execution.execution_trace = result.get("execution_trace")
            execution.completed_at = datetime.utcnow()
            logger.info(
                "Execution PAUSED (human review) | execution_id=%s | paused_at_node=%s",
                execution.id, result.get("paused_node_label"),
            )
        else:
            execution.status = ExecutionStatus.COMPLETED
            execution.output_data = result.get("final_output")
            execution.execution_trace = result.get("execution_trace")
            execution.completed_at = datetime.utcnow()
            logger.info("Execution COMPLETED | execution_id=%s", execution.id)

    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
        execution.completed_at = datetime.utcnow()
        logger.error("Execution FAILED (exception) | execution_id=%s | error=%s", execution.id, e, exc_info=True)

    db.commit()
    db.refresh(execution)
    return execution

@router.post("/workflows/{workflow_id}/trigger", response_model=TriggerResponse)
async def trigger_workflow(workflow_id: UUID, request: Request, db: Session = Depends(get_db)):
    """Trigger a workflow via live API — accepts any JSON body as input"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        input_data: Dict[str, Any] = await request.json()
    except Exception:
        input_data = {}

    # Log body keys but never log file contents (base64 floods logs)
    safe_keys = {k: ("<file>" if isinstance(v, str) and v.startswith("data:") else v)
                 for k, v in input_data.items() if not isinstance(v, dict)}
    logger.info("TRIGGER request | workflow_id=%s name=%r | body_keys=%s", workflow_id, workflow.name, safe_keys)

    execution = WorkflowExecution(
        workflow_id=workflow_id,
        status=ExecutionStatus.RUNNING,
        input_data=input_data,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    logger.info("Execution record created | execution_id=%s", execution.id)

    try:
        result = await workflow_executor.execute_workflow(workflow.graph_data, input_data)
        if result.get("status") == "failed":
            execution.status = ExecutionStatus.FAILED
            execution.error_message = (
                f"Node '{result.get('failed_node_label', result.get('failed_node_id'))}' "
                f"failed: {result.get('error')}"
            )
            execution.execution_trace = result.get("execution_trace")
            execution.completed_at = datetime.utcnow()
            logger.error("Trigger FAILED (node error) | execution_id=%s | %s", execution.id, execution.error_message)
        elif result.get("status") == "paused":
            execution.status = ExecutionStatus.COMPLETED
            execution.output_data = result.get("review_data")
            execution.execution_trace = result.get("execution_trace")
            execution.completed_at = datetime.utcnow()
            logger.info("Trigger PAUSED (human review) | execution_id=%s", execution.id)
        else:
            execution.status = ExecutionStatus.COMPLETED
            execution.output_data = result.get("final_output")
            execution.execution_trace = result.get("execution_trace")
            execution.completed_at = datetime.utcnow()
            logger.info("Trigger COMPLETED | execution_id=%s", execution.id)
    except Exception as e:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
        execution.completed_at = datetime.utcnow()
        logger.error("Trigger FAILED (exception) | execution_id=%s | error=%s", execution.id, e, exc_info=True)

    db.commit()
    db.refresh(execution)

    return TriggerResponse(
        workflow_id=workflow_id,
        execution_id=execution.id,
        status=execution.status.value,
        output=execution.output_data,
    )

@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(execution_id: UUID, db: Session = Depends(get_db)):
    """Get execution details"""
    execution = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution

@router.get("/workflows/{workflow_id}/executions", response_model=List[ExecutionResponse])
async def list_workflow_executions(workflow_id: UUID, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """List executions for a workflow"""
    executions = db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == workflow_id
    ).offset(skip).limit(limit).all()
    return executions
