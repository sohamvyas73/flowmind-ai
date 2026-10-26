import logging
import math
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import case, update
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from uuid import UUID
from app.core.database import get_db, SessionLocal
from app.core.ratelimit import limiter
from app.core.secrets import (
    extract_graph_secrets, inject_graph_secrets, dump_secrets, load_secrets, redact,
)
from app.core.auth import get_current_user
from app.models.workflow import Workflow, WorkflowExecution, ExecutionStatus
from app.models.user import User, CreditUsage, PlatformSetting
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    ExecutionCreate, ExecutionResponse, TriggerResponse
)
from app.services.workflow_executor import WorkflowExecutor
from app.core.config import settings
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()
workflow_executor = WorkflowExecutor()

def _resolve_api_keys(user: User, db: Session) -> Dict[str, Any]:
    """Build resolved API key dict: user keys > platform defaults > env.
    Also tracks _key_sources so billing knows whether the user supplied their own key."""
    platform = db.query(PlatformSetting).filter(PlatformSetting.id == 1).first()

    def pick(user_val, platform_attr, env_attr, default=None):
        return user_val or (getattr(platform, platform_attr, None) if platform else None) \
               or getattr(settings, env_attr, None) or default

    def source(user_val, platform_attr):
        if user_val:
            return "user"
        if platform and getattr(platform, platform_attr, None):
            return "platform"
        return "env"

    return {
        "gemini_api_key":    pick(user.gemini_api_key,    "gemini_api_key",    "GEMINI_API_KEY"),
        "gemini_model":      pick(user.gemini_model,      "gemini_model",      "GEMINI_MODEL", "gemini-1.5-pro"),
        "openai_api_key":    pick(user.openai_api_key,    "openai_api_key",    "OPENAI_API_KEY"),
        "openai_model":      pick(user.openai_model,      "openai_model",      "OPENAI_MODEL", "gpt-4o"),
        "anthropic_api_key": pick(user.anthropic_api_key, "anthropic_api_key", "ANTHROPIC_API_KEY"),
        "anthropic_model":   pick(user.anthropic_model,   "anthropic_model",   "ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        # Track which provider key came from the user — used by billing to skip charges
        "_key_sources": {
            "gemini":    source(user.gemini_api_key,    "gemini_api_key"),
            "openai":    source(user.openai_api_key,    "openai_api_key"),
            "anthropic": source(user.anthropic_api_key, "anthropic_api_key"),
        },
    }


CREDIT_COSTS: Dict[str, int] = {
    "inputNode": 0,
    "outputNode": 0,
    "transformNode": 1,
    "formatterNode": 1,
    "aggregatorNode": 1,
    "ruleNode": 1,
    "switchNode": 1,
    "validatorNode": 1,
    "humanReviewNode": 1,
    "codeNode": 2,
    "httpNode": 2,
    "aiNode": 10,
    "verificationNode": 10,
    "decisionNode": 10,
    "indianKycNode": 15,
}


_TOKEN_BASED_NODES = {"aiNode", "verificationNode", "decisionNode"}
_TOKENS_PER_CREDIT = 1000  # 1 credit = 1,000 tokens, configurable here


def _tokens_to_credits(total_tokens: int) -> int:
    """Convert token count to credits. Minimum 1 credit per call."""
    return max(1, math.ceil(total_tokens / _TOKENS_PER_CREDIT))


def _charge_credits(
    db: Session,
    user_id: Any,
    workflow_id: Any,
    execution_id: Any,
    execution_trace: List[Dict],
    resolved_keys: Optional[Dict[str, Any]] = None,
) -> int:
    if not execution_trace:
        return 0

    # Which provider keys did the user supply themselves?
    key_sources = (resolved_keys or {}).get("_key_sources", {})

    total = 0
    for step in execution_trace:
        node_type = step.get("node_type", "")
        result = step.get("result") or {}

        # ── Token-based billing for AI nodes ─────────────────────────────────
        if node_type in _TOKEN_BASED_NODES:
            # Currently all AI nodes run on Gemini; extend this mapping when per-node
            # model selection is added (Phase 3).
            provider = "gemini"
            if key_sources.get(provider) == "user":
                # User is paying for this with their own API key — no credit charge
                logger.info(
                    "Credits skipped | node=%s | user owns %s key", node_type, provider
                )
                continue

            token_usage = result.get("_token_usage") or {}
            prompt_t     = int(token_usage.get("prompt_tokens", 0))
            completion_t = int(token_usage.get("completion_tokens", 0))
            total_t      = int(token_usage.get("total_tokens", 0))

            if total_t > 0:
                cost = _tokens_to_credits(total_t)
                token_str = f"{total_t:,} tokens ({prompt_t:,} in + {completion_t:,} out)"
            else:
                cost = 1
                token_str = "tokens not tracked"

            if node_type == "aiNode":
                desc = f"AI Agent · {result.get('task', 'inference')} · {token_str}"
            elif node_type == "verificationNode":
                desc = f"Verification · {result.get('verification_type', '')} · {token_str}"
            else:
                desc = f"Decision · {result.get('decision', '')} · {token_str}"

        # ── Flat-rate billing for all other nodes ─────────────────────────────
        else:
            cost = CREDIT_COSTS.get(node_type, 1)
            if cost == 0:
                continue
            if node_type == "indianKycNode":
                desc = f"Indian KYC · {result.get('document_type', '')} · {result.get('provider', '')}"
            elif node_type == "httpNode":
                desc = f"HTTP {result.get('method', 'GET')} · {(result.get('url') or '')[:60]}"
            else:
                desc = node_type

        db.add(CreditUsage(
            user_id=user_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_type=node_type,
            credits=cost,
            description=desc,
        ))
        total += cost

    return total


def _estimate_cost(graph: Dict[str, Any], resolved_keys: Dict[str, Any]) -> int:
    """Upper-bound credit estimate used to reserve balance before a run (each node once)."""
    own_key = (resolved_keys.get("_key_sources") or {}).get("gemini") == "user"
    est = 0
    for node in graph.get("nodes", []) or []:
        ntype = node.get("type", "")
        if ntype in _TOKEN_BASED_NODES:
            est += 0 if own_key else 1  # token billing is at least 1 credit per call
        else:
            est += CREDIT_COSTS.get(ntype, 1)
    return est


def _reserve_credits(db: Session, user: User, estimate: int) -> int:
    """Atomically reserve `estimate` credits or raise 402. Admins are never blocked."""
    if user.role == "admin" or estimate <= 0:
        return 0
    res = db.execute(
        update(User)
        .where(User.id == user.id, User.credits_used + estimate <= User.credits_total)
        .values(credits_used=User.credits_used + estimate)
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient credits: this workflow needs up to {estimate} credits. Ask your admin for a top-up.",
        )
    return estimate


def _settle_credits(db: Session, user_id: Any, reserved: int, actual: int) -> None:
    """Replace the reservation with actual usage in one atomic UPDATE (refunds if actual < reserved)."""
    delta = actual - reserved
    if delta == 0:
        return
    new_used = User.credits_used + delta
    db.execute(
        update(User).where(User.id == user_id)
        .values(credits_used=case((new_used < 0, 0), else_=new_used))
    )
    db.commit()


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


def _get_owned_workflow(db: Session, workflow_id: UUID, user: User, denied: str = "Access denied") -> Workflow:
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if user.role != "admin" and str(workflow.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail=denied)
    return workflow


async def _run_workflow(
    db: Session, user: User, workflow: Workflow, input_data: Optional[Dict[str, Any]], source: str,
) -> tuple:
    """Reserve credits, run the workflow WITHOUT holding a DB connection, then settle.

    Returns (execution_id, live_result). Raises 402 before anything runs if credits are short.
    """
    limiter.check(f"run:{user.id}", settings.TRIGGER_RATE_LIMIT_PER_MIN)

    user_id, email = user.id, user.email
    workflow_id = workflow.id
    graph = inject_graph_secrets(workflow.graph_data, load_secrets(workflow.secrets))
    resolved_keys = _resolve_api_keys(user, db)

    reserved = _reserve_credits(db, user, _estimate_cost(graph, resolved_keys))

    execution = WorkflowExecution(
        workflow_id=workflow_id,
        status=ExecutionStatus.RUNNING,
        input_data=redact(input_data),
    )
    db.add(execution)
    db.commit()
    execution_id = execution.id
    logger.info("%s | workflow_id=%s user=%s reserved=%d", source, workflow_id, email, reserved)

    # Release the pooled connection while we wait on LLM / HTTP calls
    db.close()

    result: Dict[str, Any] = {}
    error: Optional[str] = None
    try:
        result = await workflow_executor.execute_workflow(graph, input_data, resolved_keys=resolved_keys)
    except Exception as e:
        error = str(e)
        logger.error("%s FAILED | execution_id=%s | %s", source, execution_id, e, exc_info=True)

    trace = result.get("execution_trace") or []
    charged = 0
    fresh = SessionLocal()
    try:
        try:
            execution = fresh.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
            if error or result.get("status") == "failed":
                execution.status = ExecutionStatus.FAILED
                execution.error_message = error or (
                    f"Node '{result.get('failed_node_label', result.get('failed_node_id'))}' "
                    f"failed: {result.get('error')}"
                )
            elif result.get("status") == "paused":
                execution.status = ExecutionStatus.COMPLETED
                execution.output_data = redact(result.get("review_data"))
            else:
                execution.status = ExecutionStatus.COMPLETED
                execution.output_data = redact(result.get("final_output"))
            execution.execution_trace = redact(trace)
            execution.completed_at = datetime.utcnow()
            charged = _charge_credits(fresh, user_id, workflow_id, execution_id, trace, resolved_keys=resolved_keys)
            fresh.commit()
        finally:
            _settle_credits(fresh, user_id, reserved, charged)
    finally:
        fresh.close()
    if charged:
        logger.info("Credits charged | user=%s credits=%d", email, charged)
    return execution_id, result


@router.post("/workflows/{workflow_id}/execute", response_model=ExecutionResponse)
async def execute_workflow(
    workflow_id: UUID,
    execution_data: ExecutionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = _get_owned_workflow(db, workflow_id, current_user)
    execution_id, _ = await _run_workflow(db, current_user, workflow, execution_data.input_data, "EXECUTE")
    return db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()


@router.post("/workflows/{workflow_id}/trigger", response_model=TriggerResponse)
async def trigger_workflow(
    workflow_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = _get_owned_workflow(db, workflow_id, current_user, "Access denied — use your own API token")

    try:
        input_data: Dict[str, Any] = await request.json()
    except Exception:
        input_data = {}

    execution_id, result = await _run_workflow(db, current_user, workflow, input_data, "TRIGGER")
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
