from sqlalchemy import Column, String, JSON, DateTime, Enum as SQLEnum, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum
from app.core.database import Base
from app.core.secrets import EncryptedString

class WorkflowStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"

class ExecutionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    graph_data = Column(JSON, nullable=False)
    # Encrypted JSON map of node secrets (API keys / auth headers) kept out of graph_data
    secrets = Column(EncryptedString, nullable=True)
    status = Column(SQLEnum(WorkflowStatus), default=WorkflowStatus.DRAFT)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = Column(String(50), default="1.0.0")

class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(SQLEnum(ExecutionStatus), default=ExecutionStatus.PENDING)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    execution_trace = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    # manual | api | schedule | background
    triggered_by = Column(String(20), nullable=False, default="manual", server_default="manual")
    schedule_id = Column(UUID(as_uuid=True), nullable=True)
    # Who is billed (and whose API keys are used): the caller, which may differ from the workflow owner (admins)
    billed_user_id = Column(UUID(as_uuid=True), nullable=True)
    # Credits reserved up front and not yet settled (0 once settled; makes settlement idempotent)
    reserved_credits = Column(Integer, nullable=False, default=0, server_default="0")
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
