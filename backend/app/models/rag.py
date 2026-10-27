import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.core.secrets import EncryptedString


class RagSettings(Base):
    """A user's explicit retrieval setup. There is no default row: no row means 'not set up'."""
    __tablename__ = "rag_settings"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    embed_provider = Column(String(30), nullable=False)     # local_hash | fastembed | openai | gemini
    embed_model = Column(String(100), nullable=False)
    embed_dim = Column(Integer, nullable=False)
    embed_api_key = Column(EncryptedString, nullable=True)
    store_type = Column(String(20), nullable=False)         # pgvector | qdrant | weaviate | chroma
    connection_id = Column(UUID(as_uuid=True), nullable=True)   # required unless pgvector
    embed_ok = Column(Boolean, nullable=False, default=False)
    store_ok = Column(Boolean, nullable=False, default=False)
    embed_message = Column(Text, nullable=True)
    store_message = Column(Text, nullable=True)
    tested_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def ready(self) -> bool:
        return bool(self.embed_ok and self.store_ok)

    @property
    def embed_signature(self) -> str:
        return f"{self.embed_provider}:{self.embed_model}:{self.embed_dim}"


class RagCollection(Base):
    __tablename__ = "rag_collections"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_rag_collection_user_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    store_type = Column(String(20), nullable=False)
    connection_id = Column(UUID(as_uuid=True), nullable=True)
    embed_signature = Column(String(200), nullable=False)
    dim = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def physical_name(self) -> str:
        return f"fm_{self.id.hex[:20]}"


class RagDocument(Base):
    """One indexed source inside a collection; the content hash makes re-indexing incremental."""
    __tablename__ = "rag_documents"
    __table_args__ = (UniqueConstraint("collection_id", "source", name="uq_rag_doc_source"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source = Column(String(500), nullable=False)
    content_hash = Column(String(64), nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class RagFile(Base):
    """An uploaded text document (.txt .md .pdf) available to Index nodes."""
    __tablename__ = "rag_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    format = Column(String(10), nullable=False)
    storage_key = Column(String(500), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
