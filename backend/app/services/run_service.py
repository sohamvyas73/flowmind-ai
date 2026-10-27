"""Run orchestration shared by the synchronous endpoints, the async /runs API, schedules and the job worker.

Lifecycle:  prepare_run (reserve credits, create PENDING execution)  →  execute_prepared (run, persist,
settle credits)  →  or abort_execution (cancel / dead-letter: refund the reservation).
"""
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.ratelimit import limiter
from app.core.secrets import inject_graph_secrets, load_secrets, redact
from app.jobs.queue import queue
from app.lineage import store as lineage_store
from app.models.user import CreditUsage, PlatformSetting, User
from app.models.workflow import ExecutionStatus, Workflow, WorkflowExecution
from app.services.workflow_executor import WorkflowExecutor

logger = logging.getLogger(__name__)
workflow_executor = WorkflowExecutor()

RUN_JOB_KIND = "workflow_run"

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
    # Data nodes: flat base; larger scans / long compute add credits (see _data_usage_extra)
    "loadDataNode": 1,
    "cleanDataNode": 1,
    "combineDataNode": 2,
    "summariseDataNode": 1,
    "sqlNode": 2,
    "qualityGateNode": 1,
}

_DATA_NODES = {"loadDataNode", "cleanDataNode", "combineDataNode", "summariseDataNode", "sqlNode", "qualityGateNode"}
_SCAN_BYTES_PER_CREDIT = 100 * 1024 * 1024     # +1 credit per full 100 MB scanned
_COMPUTE_SECONDS_PER_CREDIT = 30               # +1 credit per full 30 s of compute


def _data_usage_extra(result: Dict[str, Any]) -> int:
    u = result.get("_usage") or {}
    return int(u.get("scanned_bytes", 0) // _SCAN_BYTES_PER_CREDIT) + int(u.get("compute_s", 0) // _COMPUTE_SECONDS_PER_CREDIT)


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
            if node_type in _DATA_NODES:
                if "error" in result and "quality" not in result:
                    continue                       # a failed data node did no billable work (a failed quality check did)
                cost += _data_usage_extra(result)
                desc = f"Data · {node_type.replace('Node', '')} · {int(result.get('row_count') or 0):,} rows"
            elif node_type == "indianKycNode":
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


def _adjust_credits(db: Session, user_id: Any, delta: int) -> None:
    if delta == 0:
        return
    new_used = User.credits_used + delta
    db.execute(
        update(User).where(User.id == user_id)
        .values(credits_used=case((new_used < 0, 0), else_=new_used))
    )


def _settle_execution(db: Session, execution_id: Any, user_id: Any, actual: int) -> bool:
    """Replace this execution's reservation with actual usage, exactly once.

    The reservation is zeroed with a conditional UPDATE, so a redelivered job (or a retry after a crash)
    cannot refund/charge twice. Returns False if it was already settled."""
    reserved = db.query(WorkflowExecution.reserved_credits).filter(WorkflowExecution.id == execution_id).scalar() or 0
    res = db.execute(
        update(WorkflowExecution)
        .where(WorkflowExecution.id == execution_id, WorkflowExecution.reserved_credits == reserved)
        .values(reserved_credits=0)
    )
    if res.rowcount == 0:
        db.rollback()
        return False
    _adjust_credits(db, user_id, actual - reserved)
    db.commit()
    return True


def get_owned_workflow(db: Session, workflow_id: Any, user: User, denied: str = "Access denied") -> Workflow:
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if user.role != "admin" and str(workflow.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail=denied)
    return workflow


def prepare_run(
    db: Session,
    user: User,
    workflow: Workflow,
    input_data: Optional[Dict[str, Any]],
    *,
    triggered_by: str = "manual",
    schedule_id: Any = None,
    rate_limit: bool = True,
    enqueue: bool = False,
    group_key: Optional[str] = None,
) -> tuple:
    """Reserve credits and create the execution (and, when `enqueue`, its job in the same transaction).

    Raises 402 before anything is created if the balance is short. Returns (execution_id, job_id|None)."""
    if rate_limit:
        limiter.check(f"run:{user.id}", settings.TRIGGER_RATE_LIMIT_PER_MIN)

    user_id = user.id
    graph = inject_graph_secrets(workflow.graph_data, load_secrets(workflow.secrets))
    reserved = _reserve_credits(db, user, _estimate_cost(graph, _resolve_api_keys(user, db)))

    try:
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            status=ExecutionStatus.PENDING if enqueue else ExecutionStatus.RUNNING,
            input_data=redact(input_data),
            triggered_by=triggered_by,
            schedule_id=schedule_id,
            billed_user_id=user_id,
            reserved_credits=reserved,
        )
        db.add(execution)
        db.flush()
        job_id = None
        if enqueue:
            job_id = queue.enqueue(
                RUN_JOB_KIND,
                {"input_data": input_data or {}},
                db=db,
                user_id=user_id,
                execution_id=execution.id,
                group_key=group_key,
            )
        db.commit()
        return execution.id, job_id
    except Exception:
        db.rollback()
        if reserved:  # nothing was created: give the reservation back
            _adjust_credits(db, user_id, -reserved)
            db.commit()
        raise


async def execute_prepared(execution_id: Any, input_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Run a prepared execution and persist the outcome. Idempotent for already-finished executions."""
    terminal = (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED)
    db = SessionLocal()
    try:
        execution = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
        if execution is None or execution.status in terminal:
            return {}
        workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
        user = None
        billed_id = execution.billed_user_id or (workflow.user_id if workflow is not None else None)
        if billed_id:
            user = db.query(User).filter(User.id == billed_id).first()
        if workflow is None or user is None:
            _finish_failed(db, execution, "Workflow or owner no longer exists")
            return {}

        # Credits and API keys belong to whoever started the run (the schedule owner for scheduled runs)
        user_id, email = user.id, user.email
        workflow_id = workflow.id
        workflow_name = workflow.name
        started_at = execution.started_at
        graph = inject_graph_secrets(workflow.graph_data, load_secrets(workflow.secrets))
        resolved_keys = _resolve_api_keys(user, db)
        execution.status = ExecutionStatus.RUNNING
        db.commit()
        logger.info("RUN start | execution=%s workflow=%s user=%s", execution_id, workflow_id, email)
    finally:
        db.close()  # release the pooled connection while LLM / HTTP calls run

    result: Dict[str, Any] = {}
    error: Optional[str] = None
    try:
        result = await workflow_executor.execute_workflow(
            graph, input_data, resolved_keys=resolved_keys, user_id=user_id, execution_id=execution_id,
        )
    except Exception as e:
        error = str(e)
        logger.error("RUN FAILED | execution=%s | %s", execution_id, e, exc_info=True)

    trace = result.get("execution_trace") or []
    labels = {n["id"]: (n.get("data") or {}).get("label", n["id"]) for n in graph.get("nodes", [])}
    sources = {e["source"] for e in graph.get("edges", [])}
    terminal_ids = [n["id"] for n in graph.get("nodes", []) if n["id"] not in sources]
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
            _settle_execution(fresh, execution_id, user_id, charged)
    finally:
        fresh.close()
    if charged:
        logger.info("Credits charged | user=%s credits=%d", email, charged)

    await lineage_store.record_run(
        user_id=user_id, execution_id=execution_id, workflow_name=workflow_name, started_at=started_at,
        completed_at=datetime.utcnow(), status=("failed" if error or result.get("status") == "failed" else "completed"),
        error=error or result.get("error"), trace=trace, labels=labels, terminal_node_ids=terminal_ids,
    )
    return result


def _finish_failed(db: Session, execution: WorkflowExecution, message: str, cancelled: bool = False) -> None:
    execution.status = ExecutionStatus.CANCELLED if cancelled else ExecutionStatus.FAILED
    execution.error_message = message
    execution.completed_at = datetime.utcnow()
    db.commit()
    workflow = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
    owner = execution.billed_user_id or (workflow.user_id if workflow else None)
    if owner:
        _settle_execution(db, execution.id, owner, 0)  # full refund of the reservation
    else:
        db.execute(update(WorkflowExecution).where(WorkflowExecution.id == execution.id).values(reserved_credits=0))
        db.commit()


def abort_execution(execution_id: Any, message: str, cancelled: bool = False) -> None:
    """Mark a not-finished execution failed/cancelled and refund its reservation (idempotent)."""
    with SessionLocal() as db:
        execution = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
        if execution is None or execution.status in (
            ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED
        ):
            return
        _finish_failed(db, execution, message, cancelled=cancelled)


# ── job handlers ───────────────────────────────────────────────────────────────

async def handle_run_job(job) -> Optional[Dict[str, Any]]:
    await execute_prepared(job.execution_id, (job.payload or {}).get("input_data"))
    return None


async def on_run_dead(job) -> None:
    abort_execution(job.execution_id, f"Run could not be completed after {job.attempts} attempt(s): {job.last_error or 'unknown error'}")


async def on_run_cancelled(job) -> None:
    abort_execution(job.execution_id, "Cancelled by user", cancelled=True)


# ── preview (dry run) ──────────────────────────────────────────────────────────

async def preview_run(user: User, workflow: Workflow, input_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Run the pipeline on a small sample without charging credits or touching AI/HTTP/KYC nodes.

    Returns, per executed node, its status plus the dataset schema/sample and the SQL it compiled to."""
    limiter.check(f"preview:{user.id}", settings.PREVIEW_RATE_LIMIT_PER_MIN)
    graph = inject_graph_secrets(workflow.graph_data, load_secrets(workflow.secrets))
    labels = {n["id"]: (n.get("data") or {}).get("label", n["id"]) for n in graph.get("nodes", [])}
    result = await workflow_executor.execute_workflow(graph, input_data, user_id=user.id, dry_run=True)

    steps = []
    for step in result.get("execution_trace") or []:
        r = step.get("result") or {}
        item: Dict[str, Any] = {
            "node_id": step["node_id"], "node_type": step["node_type"], "label": labels.get(step["node_id"]),
            "status": "error" if "error" in r else "skipped" if r.get("skipped") else "ok",
        }
        if "error" in r:
            item["error"] = r["error"]
        if r.get("skipped"):
            item["note"] = r.get("note")
        if r.get("dataset"):
            item["dataset"] = r["dataset"]
            item["sql"] = r.get("sql")
        if r.get("quality"):
            item["quality"] = r["quality"]
        steps.append(item)
    out = {"status": result.get("status", "failed"), "sample_rows": settings.DRY_RUN_ROWS, "nodes": steps}
    if result.get("status") == "failed":
        out["error"] = result.get("error")
        out["failed_node_id"] = result.get("failed_node_id")
    return redact(out)
