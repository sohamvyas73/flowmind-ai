import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class LineageEvent(Base):
    """An OpenLineage RunEvent produced by a run of a pipeline (kept as the standard JSON, ready to export)."""
    __tablename__ = "lineage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    execution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(20), nullable=False)       # START | COMPLETE | FAIL
    event_time = Column(DateTime, nullable=False, index=True)
    job_name = Column(String(300), nullable=False)
    payload = Column(JSON, nullable=False)                # the OpenLineage RunEvent
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
