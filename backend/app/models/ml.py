import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class MlFeedbackBatch(Base):
    """One Feedback Capture: how a model's predictions compared with what really happened.

    Only aggregates are stored (never the rows), so feedback tracking cannot become a second copy of customer data.
    """
    __tablename__ = "ml_feedback_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    model_name = Column(String(255), nullable=False, index=True)
    task_type = Column(String(20), nullable=False)             # classification | regression
    rows = Column(Integer, nullable=False)
    metric = Column(String(20), nullable=False)                 # accuracy | mae
    value = Column(Float, nullable=False)
    details = Column(JSON, nullable=True)                       # per-class counts, rmse, ...
    execution_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
