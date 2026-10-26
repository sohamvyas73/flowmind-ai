import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.core.secrets import EncryptedString


class Schedule(Base):
    """Cron trigger for a workflow."""
    __tablename__ = "schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workflow_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False, default="Schedule")
    cron = Column(String(100), nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")
    input_data = Column(EncryptedString, nullable=True)  # encrypted JSON
    enabled = Column(Boolean, nullable=False, default=True)
    next_run_at = Column(DateTime, nullable=True, index=True)  # naive UTC
    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(String(100), nullable=True)
    last_execution_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
