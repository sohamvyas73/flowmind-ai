import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.core.secrets import EncryptedString


class JobState:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    DEAD = "dead_lettered"

    TERMINAL = (SUCCEEDED, CANCELLED, DEAD)


class Job(Base):
    """A unit of background work. Claimed with a time-limited lease (SELECT … FOR UPDATE SKIP LOCKED)."""
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(String(50), nullable=False, index=True)
    state = Column(String(20), nullable=False, default=JobState.QUEUED, index=True)
    # Where it may run: "hosted" now; "runner:<id>" / "pushdown" in later phases
    target = Column(String(50), nullable=False, default="hosted", index=True)
    priority = Column(Integer, nullable=False, default=0)
    # Encrypted JSON (may contain user input data); scrubbed once the job is terminal
    payload = Column(EncryptedString, nullable=True)
    capabilities = Column(JSON, nullable=True)

    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    group_key = Column(String(100), nullable=True, index=True)  # e.g. "schedule:<id>" for overlap control

    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    run_after = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    lease_expires_at = Column(DateTime, nullable=True)
    locked_by = Column(String(100), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)

    last_error = Column(Text, nullable=True)
    result_meta = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
