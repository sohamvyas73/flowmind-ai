from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User, PlatformSetting
from app.core.config import settings

router = APIRouter()


class UserConfigUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    # Pass None explicitly to clear a field; omit to leave unchanged
    clear_openai_api_key: bool = False
    clear_anthropic_api_key: bool = False
    clear_gemini_api_key: bool = False


def _mask(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "****"


def _get_platform(db: Session) -> Optional[PlatformSetting]:
    return db.query(PlatformSetting).filter(PlatformSetting.id == 1).first()


def _build_config_response(user: User, platform: Optional[PlatformSetting]) -> Dict[str, Any]:
    p = platform

    def effective(user_key, user_model, platform_key, platform_model, env_key, env_model):
        api_key = user_key or (p and p.__dict__.get(platform_key)) or getattr(settings, env_key, None)
        model = user_model or (p and p.__dict__.get(platform_model)) or getattr(settings, env_model, None)
        return api_key, model

    oai_key, oai_model = effective(
        user.openai_api_key, user.openai_model,
        "openai_api_key", "openai_model",
        "OPENAI_API_KEY", "OPENAI_MODEL",
    )
    ant_key, ant_model = effective(
        user.anthropic_api_key, user.anthropic_model,
        "anthropic_api_key", "anthropic_model",
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    )
    gem_key, gem_model = effective(
        user.gemini_api_key, user.gemini_model,
        "gemini_api_key", "gemini_model",
        "GEMINI_API_KEY", "GEMINI_MODEL",
    )

    return {
        "openai": {
            "api_key_set": bool(user.openai_api_key),
            "api_key_masked": _mask(user.openai_api_key),
            "model": user.openai_model,
            "effective_key_masked": _mask(oai_key),
            "effective_model": oai_model or "gpt-4o",
            "source": "user" if user.openai_api_key else ("platform" if (p and p.openai_api_key) else "env"),
        },
        "anthropic": {
            "api_key_set": bool(user.anthropic_api_key),
            "api_key_masked": _mask(user.anthropic_api_key),
            "model": user.anthropic_model,
            "effective_key_masked": _mask(ant_key),
            "effective_model": ant_model or "claude-sonnet-4-6",
            "source": "user" if user.anthropic_api_key else ("platform" if (p and p.anthropic_api_key) else "env"),
        },
        "gemini": {
            "api_key_set": bool(user.gemini_api_key),
            "api_key_masked": _mask(user.gemini_api_key),
            "model": user.gemini_model,
            "effective_key_masked": _mask(gem_key),
            "effective_model": gem_model or "gemini-1.5-pro",
            "source": "user" if user.gemini_api_key else ("platform" if (p and p.gemini_api_key) else "env"),
        },
    }


@router.get("/me")
async def get_my_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    platform = _get_platform(db)
    return _build_config_response(current_user, platform)


@router.put("/me")
async def update_my_config(
    data: UserConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if data.clear_openai_api_key:
        user.openai_api_key = None
    elif data.openai_api_key is not None:
        user.openai_api_key = data.openai_api_key or None

    if data.openai_model is not None:
        user.openai_model = data.openai_model or None

    if data.clear_anthropic_api_key:
        user.anthropic_api_key = None
    elif data.anthropic_api_key is not None:
        user.anthropic_api_key = data.anthropic_api_key or None

    if data.anthropic_model is not None:
        user.anthropic_model = data.anthropic_model or None

    if data.clear_gemini_api_key:
        user.gemini_api_key = None
    elif data.gemini_api_key is not None:
        user.gemini_api_key = data.gemini_api_key or None

    if data.gemini_model is not None:
        user.gemini_model = data.gemini_model or None

    db.commit()
    db.refresh(user)
    platform = _get_platform(db)
    return _build_config_response(user, platform)
