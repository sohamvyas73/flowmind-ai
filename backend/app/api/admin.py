import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.core.auth import get_admin_user, generate_api_token, hash_password
from app.models.user import User, CreditUsage, UserRole, PlatformSetting
from app.models.workflow import Workflow, WorkflowExecution, ExecutionStatus

logger = logging.getLogger(__name__)
router = APIRouter()


class PlatformSettingUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    clear_openai_api_key: bool = False
    clear_anthropic_api_key: bool = False
    clear_gemini_api_key: bool = False


def _mask(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "****"


def _get_or_create_platform(db: Session) -> PlatformSetting:
    setting = db.query(PlatformSetting).filter(PlatformSetting.id == 1).first()
    if not setting:
        setting = PlatformSetting(id=1)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


@router.get("/stats")
async def get_platform_stats(
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_workflows = db.query(func.count(Workflow.id)).scalar() or 0
    total_executions = db.query(func.count(WorkflowExecution.id)).scalar() or 0
    total_credits = db.query(func.sum(User.credits_used)).scalar() or 0

    completed = db.query(func.count(WorkflowExecution.id)).filter(
        WorkflowExecution.status == ExecutionStatus.COMPLETED
    ).scalar() or 0
    failed = db.query(func.count(WorkflowExecution.id)).filter(
        WorkflowExecution.status == ExecutionStatus.FAILED
    ).scalar() or 0

    kyc_calls = db.query(func.count(CreditUsage.id)).filter(
        CreditUsage.node_type == "indianKycNode"
    ).scalar() or 0
    http_calls = db.query(func.count(CreditUsage.id)).filter(
        CreditUsage.node_type == "httpNode"
    ).scalar() or 0
    ai_calls = db.query(func.count(CreditUsage.id)).filter(
        CreditUsage.node_type == "aiNode"
    ).scalar() or 0

    return {
        "total_users": total_users,
        "total_workflows": total_workflows,
        "total_executions": total_executions,
        "total_credits_consumed": total_credits,
        "completed_executions": completed,
        "failed_executions": failed,
        "success_rate": round(completed / total_executions * 100, 1) if total_executions else 0,
        "third_party": {
            "kyc_calls": kyc_calls,
            "http_calls": http_calls,
            "ai_calls": ai_calls,
        },
    }


@router.get("/users")
async def list_users(
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    result = []
    for user in users:
        wf_count = db.query(func.count(Workflow.id)).filter(Workflow.user_id == user.id).scalar() or 0
        exec_count = (
            db.query(func.count(WorkflowExecution.id))
            .join(Workflow, WorkflowExecution.workflow_id == Workflow.id)
            .filter(Workflow.user_id == user.id)
            .scalar() or 0
        )
        result.append({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "api_token": user.api_token,
            "credits_total": user.credits_total,
            "credits_used": user.credits_used,
            "credits_remaining": user.credits_total - user.credits_used,
            "is_active": user.is_active,
            "workflow_count": wf_count,
            "execution_count": exec_count,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        })
    return result


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if "credits_total" in data:
        user.credits_total = max(0, int(data["credits_total"]))
    if "is_active" in data:
        user.is_active = bool(data["is_active"])
    if "role" in data and data["role"] in ("user", "admin"):
        user.role = UserRole.ADMIN if data["role"] == "admin" else UserRole.USER

    db.commit()
    db.refresh(user)
    return {
        "id": str(user.id),
        "email": user.email,
        "credits_total": user.credits_total,
        "credits_used": user.credits_used,
        "is_active": user.is_active,
        "role": user.role,
    }


@router.post("/users/{user_id}/reset-api-token")
async def reset_user_api_token(
    user_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.api_token = generate_api_token()
    db.commit()
    return {"api_token": user.api_token}


@router.get("/credit-usage")
async def get_credit_usage(
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    rows = (
        db.query(
            CreditUsage.user_id,
            CreditUsage.node_type,
            func.sum(CreditUsage.credits).label("total_credits"),
            func.count(CreditUsage.id).label("call_count"),
        )
        .group_by(CreditUsage.user_id, CreditUsage.node_type)
        .all()
    )

    user_cache: Dict[str, Any] = {}
    result: Dict[str, Any] = {}

    for row in rows:
        uid = str(row.user_id)
        if uid not in user_cache:
            u = db.query(User).filter(User.id == row.user_id).first()
            user_cache[uid] = u.email if u else "unknown"
        if uid not in result:
            result[uid] = {
                "user_id": uid,
                "email": user_cache[uid],
                "breakdown": [],
                "total_credits": 0,
            }
        result[uid]["breakdown"].append({
            "node_type": row.node_type,
            "credits": row.total_credits,
            "calls": row.call_count,
        })
        result[uid]["total_credits"] += row.total_credits

    return sorted(result.values(), key=lambda x: x["total_credits"], reverse=True)


@router.get("/connectors")
async def get_connector_usage(
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    rows = (
        db.query(
            CreditUsage.user_id,
            CreditUsage.node_type,
            CreditUsage.description,
            func.count(CreditUsage.id).label("call_count"),
            func.sum(CreditUsage.credits).label("total_credits"),
        )
        .filter(CreditUsage.node_type.in_(["indianKycNode", "httpNode"]))
        .group_by(CreditUsage.user_id, CreditUsage.node_type, CreditUsage.description)
        .order_by(func.count(CreditUsage.id).desc())
        .all()
    )

    user_cache: Dict[str, str] = {}
    result = []
    for row in rows:
        uid = str(row.user_id)
        if uid not in user_cache:
            u = db.query(User).filter(User.id == row.user_id).first()
            user_cache[uid] = u.email if u else "unknown"
        result.append({
            "user_id": uid,
            "email": user_cache[uid],
            "connector": row.node_type,
            "description": row.description or "",
            "call_count": row.call_count,
            "credits_used": row.total_credits,
        })
    return result


@router.get("/platform-settings")
async def get_platform_settings(
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    s = _get_or_create_platform(db)
    return {
        "openai": {
            "api_key_set": bool(s.openai_api_key),
            "api_key_masked": _mask(s.openai_api_key),
            "model": s.openai_model or "gpt-4o",
        },
        "anthropic": {
            "api_key_set": bool(s.anthropic_api_key),
            "api_key_masked": _mask(s.anthropic_api_key),
            "model": s.anthropic_model or "claude-sonnet-4-6",
        },
        "gemini": {
            "api_key_set": bool(s.gemini_api_key),
            "api_key_masked": _mask(s.gemini_api_key),
            "model": s.gemini_model or "gemini-1.5-pro",
        },
    }


@router.put("/platform-settings")
async def update_platform_settings(
    data: PlatformSettingUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    s = _get_or_create_platform(db)

    if data.clear_openai_api_key:
        s.openai_api_key = None
    elif data.openai_api_key is not None:
        s.openai_api_key = data.openai_api_key or None
    if data.openai_model is not None:
        s.openai_model = data.openai_model or "gpt-4o"

    if data.clear_anthropic_api_key:
        s.anthropic_api_key = None
    elif data.anthropic_api_key is not None:
        s.anthropic_api_key = data.anthropic_api_key or None
    if data.anthropic_model is not None:
        s.anthropic_model = data.anthropic_model or "claude-sonnet-4-6"

    if data.clear_gemini_api_key:
        s.gemini_api_key = None
    elif data.gemini_api_key is not None:
        s.gemini_api_key = data.gemini_api_key or None
    if data.gemini_model is not None:
        s.gemini_model = data.gemini_model or "gemini-1.5-pro"

    db.commit()
    db.refresh(s)
    return {
        "openai": {
            "api_key_set": bool(s.openai_api_key),
            "api_key_masked": _mask(s.openai_api_key),
            "model": s.openai_model,
        },
        "anthropic": {
            "api_key_set": bool(s.anthropic_api_key),
            "api_key_masked": _mask(s.anthropic_api_key),
            "model": s.anthropic_model,
        },
        "gemini": {
            "api_key_set": bool(s.gemini_api_key),
            "api_key_masked": _mask(s.gemini_api_key),
            "model": s.gemini_model,
        },
    }


@router.get("/workflows")
async def admin_list_workflows(
    db: Session = Depends(get_db),
    _=Depends(get_admin_user),
):
    workflows = db.query(Workflow).order_by(Workflow.created_at.desc()).limit(500).all()
    user_cache: Dict[str, str] = {}
    result = []
    for wf in workflows:
        owner_email = "unassigned"
        if wf.user_id:
            uid = str(wf.user_id)
            if uid not in user_cache:
                u = db.query(User).filter(User.id == wf.user_id).first()
                user_cache[uid] = u.email if u else "deleted"
            owner_email = user_cache[uid]

        exec_count = (
            db.query(func.count(WorkflowExecution.id))
            .filter(WorkflowExecution.workflow_id == wf.id)
            .scalar() or 0
        )
        result.append({
            "id": str(wf.id),
            "name": wf.name,
            "status": wf.status,
            "owner_email": owner_email,
            "owner_id": str(wf.user_id) if wf.user_id else None,
            "execution_count": exec_count,
            "node_count": len(wf.graph_data.get("nodes", [])) if wf.graph_data else 0,
            "created_at": wf.created_at.isoformat() if wf.created_at else None,
            "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
        })
    return result
