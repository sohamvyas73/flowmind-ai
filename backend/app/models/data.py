import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class DataFile(Base):
    """A file the user uploaded (CSV / TSV / JSON / JSONL / Parquet). Kept until the user deletes it."""
    __tablename__ = "data_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    format = Column(String(20), nullable=False)             # csv | tsv | json | jsonl | parquet
    storage_key = Column(String(500), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    row_count = Column(BigInteger, nullable=True)
    columns = Column(JSON, nullable=True)                   # [{"name","type"}]
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Dataset(Base):
    """A table materialised by a pipeline node, stored as Parquet. Expires (see DATASET_RETENTION_DAYS)."""
    __tablename__ = "datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    storage_key = Column(String(500), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    row_count = Column(BigInteger, nullable=True)
    columns = Column(JSON, nullable=True)
    execution_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    node_id = Column(String(100), nullable=True)
    sql = Column(String, nullable=True)                     # the SQL that produced it (for learning / "open as SQL")
    lineage = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True, index=True)
