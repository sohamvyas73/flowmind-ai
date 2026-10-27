import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.rag import RagFile, RagSettings
from app.models.user import User
from app.rag import service as rag
from app.rag.catalog import catalog
from app.rag.chunking import ExtractError, extract_text
from app.services import rag_nodes
from app.services.dataset_service import DataError, check_quota, clean_filename
from app.storage.local import StorageError, storage, tenant_key

router = APIRouter()

DOC_FORMATS = {".txt": "txt", ".md": "md", ".markdown": "md", ".pdf": "pdf"}
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "docs")
MAX_FILES_PER_USER = 200


class SettingsIn(BaseModel):
    embed_provider: str
    embed_model: str
    embed_dim: int = Field(ge=16, le=4096)
    embed_api_key: Optional[str] = None
    store_type: str
    connection_id: Optional[UUID] = None


class SettingsOut(BaseModel):
    configured: bool
    ready: bool = False
    embed_provider: Optional[str] = None
    embed_model: Optional[str] = None
    embed_dim: Optional[int] = None
    has_embed_key: bool = False
    store_type: Optional[str] = None
    connection_id: Optional[UUID] = None
    embed_ok: bool = False
    store_ok: bool = False
    embed_message: Optional[str] = None
    store_message: Optional[str] = None
    tested_at: Optional[datetime] = None


def _out(s: Optional[RagSettings]) -> SettingsOut:
    if s is None:
        return SettingsOut(configured=False)
    return SettingsOut(
        configured=True, ready=s.ready, embed_provider=s.embed_provider, embed_model=s.embed_model, embed_dim=s.embed_dim,
        has_embed_key=bool(s.embed_api_key), store_type=s.store_type, connection_id=s.connection_id, embed_ok=s.embed_ok,
        store_ok=s.store_ok, embed_message=s.embed_message, store_message=s.store_message, tested_at=s.tested_at)


def _fail(e: Exception, code: int = 400):
    raise HTTPException(status_code=code, detail=str(e))


@router.get("/catalog")
async def get_catalog(_: User = Depends(get_current_user)):
    return catalog()


@router.get("/settings", response_model=SettingsOut)
async def get_settings(user: User = Depends(get_current_user)):
    return _out(await asyncio.to_thread(rag.load_settings, user.id))


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsIn, user: User = Depends(get_current_user)):
    try:
        return _out(await rag.save_and_test(
            user.id, embed_provider=body.embed_provider, embed_model=body.embed_model, embed_dim=body.embed_dim,
            embed_api_key=body.embed_api_key, store_type=body.store_type, connection_id=body.connection_id))
    except rag.RagError as e:
        _fail(e, 422)


@router.post("/settings/test", response_model=SettingsOut)
async def test_settings(user: User = Depends(get_current_user)):
    try:
        return _out(await rag.retest(user.id))
    except rag.RagError as e:
        _fail(e, 409)


@router.delete("/settings", status_code=status.HTTP_204_NO_CONTENT)
async def delete_settings(user: User = Depends(get_current_user)):
    await asyncio.to_thread(rag.clear_settings, user.id)
    return None


# ── documents ──────────────────────────────────────────────────────────────────

class FileOut(BaseModel):
    id: UUID
    name: str
    format: str
    size_bytes: int
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/files", response_model=List[FileOut])
async def list_files(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(RagFile).filter(RagFile.user_id == user.id).order_by(RagFile.created_at.desc()).all()


async def _store_doc(user: User, name: str, stream) -> RagFile:
    name = clean_filename(name)
    ext = os.path.splitext(name)[1].lower()
    if ext not in DOC_FORMATS:
        raise DataError("Documents must be .txt, .md or .pdf")
    fmt = DOC_FORMATS[ext]
    fid = uuid.uuid4()
    key = tenant_key(user.id, "docs", f"{fid}.{fmt}")

    def _count():
        from app.core.database import SessionLocal
        with SessionLocal() as db:
            check_quota(db, user.id, 1)
            return db.query(RagFile).filter(RagFile.user_id == user.id).count()
    if await asyncio.to_thread(_count) >= MAX_FILES_PER_USER:
        raise DataError(f"Document limit reached ({MAX_FILES_PER_USER})")
    try:
        size = await asyncio.to_thread(storage.save_stream, key, stream, settings.MAX_UPLOAD_MB * 1024 * 1024)
    except StorageError as e:
        raise DataError(str(e))
    try:
        with open(storage.path_for(key), "rb") as f:
            text = extract_text(fmt, f.read())
        if not text.strip():
            raise ExtractError("The document is empty")
    except ExtractError as e:
        storage.delete(key)
        raise DataError(str(e))

    def _rec():
        from app.core.database import SessionLocal
        with SessionLocal() as db:
            existing = db.query(RagFile).filter(RagFile.user_id == user.id, RagFile.name == name).first()
            if existing:                                  # same name = replace, so re-uploading an edited file updates it
                storage.delete(existing.storage_key)
                db.delete(existing)
                db.flush()
            row = RagFile(id=fid, user_id=user.id, name=name, format=fmt, storage_key=key, size_bytes=size)
            db.add(row)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row
    return await asyncio.to_thread(_rec)


@router.post("/files", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_doc(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    try:
        return await _store_doc(user, file.filename or "document.txt", file.file)
    except DataError as e:
        _fail(e, 422)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(file_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(RagFile).filter(RagFile.id == file_id, RagFile.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    storage.delete(row.storage_key)
    db.delete(row)
    db.commit()
    return None


@router.post("/samples", response_model=List[FileOut])
async def install_sample_docs(user: User = Depends(get_current_user)):
    """Install the example 'Acme Co. help centre' documents used by the guide and the sample workflows."""
    out = []
    for name in sorted(os.listdir(SAMPLES_DIR)):
        with open(os.path.join(SAMPLES_DIR, name), "rb") as f:
            try:
                out.append(await _store_doc(user, name, f))
            except DataError as e:
                _fail(e, 422)
    return out


# ── collections, indexing, search ──────────────────────────────────────────────

class IndexIn(BaseModel):
    collection: str
    file_names: List[str] = []
    chunk_size: int = 800
    overlap: int = 100


class QueryIn(BaseModel):
    collection: str
    query: str
    top_k: int = 4
    min_score: float = 0.0


@router.get("/collections")
async def list_collections(user: User = Depends(get_current_user)):
    return await asyncio.to_thread(rag.list_collections, user.id)


@router.delete("/collections/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(name: str, user: User = Depends(get_current_user)):
    if not await rag.delete_collection(user.id, name):
        raise HTTPException(status_code=404, detail="Collection not found")
    return None


@router.post("/index")
async def index_files(body: IndexIn, user: User = Depends(get_current_user)):
    """Index uploaded documents from the Retrieval page (the Index node does the same inside a workflow)."""
    res = await rag_nodes.run_index(
        {"collection": body.collection, "source": "files", "fileNames": body.file_names,
         "chunkSize": body.chunk_size, "overlap": body.overlap}, {"_user_id": user.id})
    if "error" in res:
        _fail(Exception(res["error"]), 422)
    return res


@router.post("/query")
async def query(body: QueryIn, user: User = Depends(get_current_user)):
    try:
        return {"query": body.query, "passages": await rag.search(
            user.id, body.collection, body.query, top_k=body.top_k, min_score=body.min_score)}
    except rag.RagError as e:
        _fail(e, 422)
