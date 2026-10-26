import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.core.secrets import EncryptedString


class Connection(Base):
    """Saved, encrypted credentials for an external system."""
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_connection_user_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)
    config = Column(EncryptedString, nullable=False)          # encrypted JSON (includes secrets)
    access_mode = Column(String(20), nullable=False, default="read_only")  # read_only | read_write
    # Hosts allowed to resolve to private addresses. Settable by admins only.
    host_allowlist = Column(JSON, nullable=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_test_ok = Column(Boolean, nullable=True)
    last_test_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
