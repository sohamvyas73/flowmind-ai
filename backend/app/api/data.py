import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.data.dataset import DatasetRef
from app.models.data import DataFile, Dataset
from app.models.user import User
from app.services import dataset_service as ds
from app.services.dataset_service import DataError
from app.storage.local import storage, tenant_key

logger = logging.getLogger(__name__)
router = APIRouter()

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "data")


class FileInfo(BaseModel):
    id: UUID
    name: str
    format: str
    size_bytes: int
    row_count: Optional[int] = None
    columns: Optional[list] = None
    created_at: datetime


class DatasetInfo(BaseModel):
    id: UUID
    name: Optional[str] = None
    size_bytes: int
    row_count: Optional[int] = None
    columns: Optional[list] = None
    sql: Optional[str] = None
    execution_id: Optional[UUID] = None
    created_at: datetime
    expires_at: Optional[datetime] = None


class Usage(BaseModel):
    used_bytes: int
    limit_bytes: int
    files: int
    datasets: int
    max_upload_bytes: int


def _fail(e: DataError, code: int = 400):
    raise HTTPException(status_code=code, detail=str(e))


# ── files ──────────────────────────────────────────────────────────────────────

@router.get("/usage", response_model=Usage)
async def usage(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return Usage(
        used_bytes=ds.storage_used_bytes(db, user.id), limit_bytes=settings.MAX_STORAGE_MB_PER_USER * ds.MB,
        files=db.query(DataFile).filter(DataFile.user_id == user.id).count(),
        datasets=db.query(Dataset).filter(Dataset.user_id == user.id).count(),
        max_upload_bytes=settings.MAX_UPLOAD_MB * ds.MB,
    )


@router.get("/files", response_model=List[FileInfo])
async def list_files(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(DataFile).filter(DataFile.user_id == user.id).order_by(DataFile.created_at.desc()).all()


@router.post("/files", response_model=FileInfo, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    try:
        return await ds.save_upload(user.id, file.filename or "upload", file.file)
    except DataError as e:
        _fail(e, 413 if "limit" in str(e).lower() else 422)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        ds.delete_file(db, user.id, file_id)
    except DataError as e:
        _fail(e, 404)
    return None


@router.get("/files/{file_id}/preview", response_model=DatasetRef)
async def preview_file(
    file_id: UUID, limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    try:
        f = ds.get_file(db, user.id, file_id=str(file_id))
        path, fmt = storage.path_for(f.storage_key), f.format
        tmp = storage.path_for(tenant_key(user.id, "uploads", f"{uuid.uuid4()}.probe.parquet"))
        info = await ds.sample_of(path, fmt, limit, tmp)
        return ds.file_ref(f, info["sample"], limit)
    except DataError as e:
        _fail(e, 404)
    except Exception as e:
        from app.engine.duckdb_engine import EngineError
        if isinstance(e, EngineError):
            _fail(DataError(str(e)), 422)
        raise


@router.post("/examples", response_model=List[FileInfo])
async def install_examples(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Copy the bundled example CSVs into the user's files (skips ones they already have)."""
    have = {f.name for f in db.query(DataFile).filter(DataFile.user_id == user.id).all()}
    created: List[DataFile] = []
    for name in sorted(os.listdir(EXAMPLES_DIR)):
        if not name.endswith(".csv") or name in have:
            continue
        with open(os.path.join(EXAMPLES_DIR, name), "rb") as fh:
            try:
                created.append(await ds.save_upload(user.id, name, fh))
            except DataError as e:
                _fail(e, 413 if "limit" in str(e).lower() else 422)
    return created


# ── datasets (pipeline outputs) ────────────────────────────────────────────────

@router.get("/datasets", response_model=List[DatasetInfo])
async def list_datasets(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return (
        db.query(Dataset).filter(Dataset.user_id == user.id, Dataset.execution_id != None)  # noqa: E711
        .order_by(Dataset.created_at.desc()).limit(limit).all()
    )


@router.get("/datasets/{dataset_id}/preview", response_model=DatasetRef)
async def preview_dataset(
    dataset_id: UUID, limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    try:
        d = ds.get_dataset(db, user.id, dataset_id)
        tmp = storage.path_for(tenant_key(user.id, "datasets", f"{uuid.uuid4()}.probe.parquet"))
        info = await ds.sample_of(storage.path_for(d.storage_key), "parquet", limit, tmp)
        return ds.dataset_ref(d, info["sample"], limit)
    except DataError as e:
        _fail(e, 404)


@router.get("/datasets/{dataset_id}/download")
async def download_dataset(
    dataset_id: UUID, background: BackgroundTasks, format: str = Query("csv", pattern="^(csv|parquet)$"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    try:
        d = ds.get_dataset(db, user.id, dataset_id)
    except DataError as e:
        _fail(e, 404)
    src = storage.path_for(d.storage_key)
    base = (ds.clean_filename(d.name or "dataset").rsplit(".", 1)[0] or "dataset").replace(" ", "_")
    if format == "parquet":
        return FileResponse(src, media_type="application/octet-stream", filename=f"{base}.parquet")

    tmpdir = tempfile.mkdtemp(prefix="fm_dl_")
    out = os.path.join(tmpdir, f"{base}.csv")

    def _to_csv() -> None:
        import pyarrow.csv as pacsv
        import pyarrow.parquet as pq
        pacsv.write_csv(pq.read_table(src), out)

    await asyncio.to_thread(_to_csv)
    background.add_task(shutil.rmtree, tmpdir, True)
    return FileResponse(out, media_type="text/csv", filename=f"{base}.csv")


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(dataset_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    d = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == user.id).first()
    if d is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    ds.delete_dataset_row(db, d)
    db.commit()
    return None
