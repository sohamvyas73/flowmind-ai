from sqlalchemy import Column, String, Integer, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.core.database import Base


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    api_token = Column(String(64), unique=True, nullable=False, index=True)
    credits_total = Column(Integer, default=100, nullable=False)
    credits_used = Column(Integer, default=0, nullable=False)
    # New users start inactive; admin must approve
    is_active = Column(Boolean, default=False, nullable=False)

    # Per-user model config (overrides platform defaults when set)
    openai_api_key = Column(String(255), nullable=True)
    openai_model = Column(String(100), nullable=True)
    anthropic_api_key = Column(String(255), nullable=True)
    anthropic_model = Column(String(100), nullable=True)
    gemini_api_key = Column(String(255), nullable=True)
    gemini_model = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreditUsage(Base):
    __tablename__ = "credit_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workflow_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    node_type = Column(String(100), nullable=False)
    credits = Column(Integer, nullable=False, default=0)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlatformSetting(Base):
    """Single-row table holding admin-configured platform-wide defaults."""
    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True, default=1)
    openai_api_key = Column(String(255), nullable=True)
    openai_model = Column(String(100), default="gpt-4o")
    anthropic_api_key = Column(String(255), nullable=True)
    anthropic_model = Column(String(100), default="claude-sonnet-4-6")
    gemini_api_key = Column(String(255), nullable=True)
    gemini_model = Column(String(100), default="gemini-1.5-pro")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
