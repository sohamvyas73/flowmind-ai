"""Files and datasets: ownership checks, quotas, introspection and DatasetRef construction."""
import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, BinaryIO, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.data.dataset import Column, DatasetLocation, DatasetRef, LineageEdge, build_dataset
from app.engine.duckdb_engine import EngineError, EngineInput, run_sql
from app.models.data import DataFile, Dataset
from app.services import profile as profile_service
from app.storage.local import StorageError, storage, tenant_key

ALLOWED_FORMATS = {".csv": "csv", ".tsv": "tsv", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl", ".parquet": "parquet"}
_BAD_NAME = re.compile(r"[^A-Za-z0-9._ -]")
MB = 1024 * 1024


class DataError(Exception):
    """User-facing data problem (bad file, over quota, not found)."""


def clean_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = _BAD_NAME.sub("_", base)[:200]
    return base or "upload"


def detect_format(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_FORMATS:
        raise DataError(f"Unsupported file type '{ext or filename}'. Use CSV, TSV, JSON, JSONL or Parquet.")
    return ALLOWED_FORMATS[ext]


# ── quotas ─────────────────────────────────────────────────────────────────────

def storage_used_bytes(db: Session, user_id: Any) -> int:
    files = db.query(func.coalesce(func.sum(DataFile.size_bytes), 0)).filter(DataFile.user_id == user_id).scalar()
    sets = db.query(func.coalesce(func.sum(Dataset.size_bytes), 0)).filter(Dataset.user_id == user_id).scalar()
    return int(files or 0) + int(sets or 0)


def check_quota(db: Session, user_id: Any, incoming_bytes: int = 0) -> None:
    limit = settings.MAX_STORAGE_MB_PER_USER * MB
    if storage_used_bytes(db, user_id) + incoming_bytes > limit:
        raise DataError(
            f"Storage limit reached ({settings.MAX_STORAGE_MB_PER_USER} MB). Delete files or old datasets to free space."
        )


# ── lookups (always scoped to the owner) ────────────────────────────────────────

def get_file(db: Session, user_id: Any, file_id: Optional[str] = None, name: Optional[str] = None) -> DataFile:
    q = db.query(DataFile).filter(DataFile.user_id == user_id)
    if file_id:
        try:
            f = q.filter(DataFile.id == uuid.UUID(str(file_id))).first()
        except ValueError:
            f = None
    elif name:
        f = q.filter(DataFile.name == name).order_by(DataFile.created_at.desc()).first()
    else:
        raise DataError("No file selected")
    if f is None:
        raise DataError(f"File '{name or file_id}' not found. Upload it on the Data page first.")
    return f


def get_dataset(db: Session, user_id: Any, dataset_id: Any) -> Dataset:
    try:
        d = db.query(Dataset).filter(Dataset.user_id == user_id, Dataset.id == uuid.UUID(str(dataset_id))).first()
    except ValueError:
        d = None
    if d is None:
        raise DataError("Dataset not found (it may have expired)")
    if not storage.exists(d.storage_key):
        raise DataError("Dataset data is no longer available (expired). Re-run the pipeline.")
    return d


# ── DatasetRef ──────────────────────────────────────────────────────────────────

def make_ref(
    columns: List[Dict[str, str]], sample: List[Dict[str, Any]], *, row_count: Optional[int], size_bytes: Optional[int],
    dataset_id: Optional[uuid.UUID] = None, kind: str = "table", produced_by: Optional[str] = None,
    lineage: Optional[List[LineageEdge]] = None, path: Optional[str] = None, sample_limit: int = 100,
) -> DatasetRef:
    ref = build_dataset(
        [Column(name=c["name"], type=c.get("type", "unknown")) for c in columns], sample,
        kind=kind, location=DatasetLocation(path=path), row_count=row_count, size_bytes=size_bytes,
        lineage=lineage, sample_limit=sample_limit,
    )
    if dataset_id:
        ref.id = dataset_id
    ref.produced_by = produced_by
    return ref


def file_ref(f: DataFile, sample: List[Dict[str, Any]], limit: int = 100) -> DatasetRef:
    return make_ref(
        f.columns or [], sample, row_count=f.row_count, size_bytes=f.size_bytes, dataset_id=f.id, kind="file",
        path=f"file:{f.name}", lineage=[LineageEdge(source=f"file:{f.name}", operation="read")], sample_limit=limit,
    )


def dataset_ref(d: Dataset, sample: List[Dict[str, Any]], limit: int = 100) -> DatasetRef:
    return make_ref(
        d.columns or [], sample, row_count=d.row_count, size_bytes=d.size_bytes, dataset_id=d.id,
        produced_by=d.node_id, path=f"dataset:{d.id}", lineage=[LineageEdge(**e) for e in (d.lineage or [])],
        sample_limit=limit,
    )


# ── uploads ─────────────────────────────────────────────────────────────────────

async def save_upload(user_id: Any, filename: str, stream: BinaryIO) -> DataFile:
    """Store an uploaded file, validate it by actually parsing it, and record it."""
    name = clean_filename(filename)
    fmt = detect_format(name)
    file_id = uuid.uuid4()
    key = tenant_key(user_id, "uploads", f"{file_id}.{fmt}")

    def _precheck():
        with SessionLocal() as db:
            check_quota(db, user_id, 1)        # refuse early when the account is already full
    await asyncio.to_thread(_precheck)

    try:
        size = await asyncio.to_thread(storage.save_stream, key, stream, settings.MAX_UPLOAD_MB * MB)
    except StorageError as e:
        raise DataError(str(e))
    if size == 0:
        storage.delete(key)
        raise DataError("The file is empty")

    # Parse it now so a bad file fails on upload, not in the middle of a pipeline
    probe_out = storage.path_for(tenant_key(user_id, "uploads", f"{file_id}.probe.parquet"))
    try:
        res = await run_sql(
            [EngineInput("f", storage.path_for(key), fmt)], "SELECT * FROM f LIMIT 100", probe_out, sample_rows=0,
        )
    except EngineError as e:
        storage.delete(key)
        raise DataError(f"Could not read this file as {fmt.upper()}: {e}")
    finally:
        storage.delete(tenant_key(user_id, "uploads", f"{file_id}.probe.parquet"))

    def _record() -> DataFile:
        with SessionLocal() as db:
            try:
                check_quota(db, user_id, size)
            except DataError:
                storage.delete(key)
                raise
            f = DataFile(
                id=file_id, user_id=user_id, name=name, format=fmt, storage_key=key,
                size_bytes=size, row_count=res.scanned_rows, columns=res.columns,
            )
            db.add(f)
            db.commit()
            db.refresh(f)
            db.expunge(f)
            return f
    return await asyncio.to_thread(_record)


def delete_file(db: Session, user_id: Any, file_id: Any) -> None:
    f = get_file(db, user_id, file_id=str(file_id))
    storage.delete(f.storage_key)
    db.delete(f)
    db.commit()


def delete_dataset_row(db: Session, d: Dataset) -> None:
    storage.delete(d.storage_key)
    db.delete(d)


async def sample_of(path: str, fmt: str, limit: int, tmp_out: str) -> Dict[str, Any]:
    res = await run_sql([EngineInput("t", path, fmt)], f"SELECT * FROM t LIMIT {int(limit)}", tmp_out, sample_rows=limit)
    try:
        os.unlink(tmp_out)
    except OSError:
        pass
    return {"columns": res.columns, "sample": res.sample, "total_rows": res.scanned_rows}


# ── retention ───────────────────────────────────────────────────────────────────

def purge_expired_datasets() -> int:
    now = datetime.utcnow()
    with SessionLocal() as db:
        rows = db.query(Dataset).filter(Dataset.expires_at != None, Dataset.expires_at < now).all()  # noqa: E711
        for d in rows:
            delete_dataset_row(db, d)
        db.commit()
        return len(rows)


def default_expiry(dry_run: bool) -> Optional[datetime]:
    if dry_run:
        return datetime.utcnow() + timedelta(days=1)
    days = settings.DATASET_RETENTION_DAYS
    return datetime.utcnow() + timedelta(days=days) if days > 0 else None


async def profile_data(user_id: Any, path: str, fmt: str, columns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Column statistics + suggested checks. Personal-data columns (by name or by value) never expose min/max/values."""
    out_dir = storage.path_for(tenant_key(user_id, "tmp"))
    os.makedirs(out_dir, exist_ok=True)
    probe = os.path.join(out_dir, f"{uuid.uuid4()}.s.parquet")
    info = await sample_of(path, fmt, 100, probe)
    ref = make_ref(columns or info["columns"], info["sample"], row_count=info["total_rows"], size_bytes=None)
    try:
        return await profile_service.profile(path, fmt, columns or info["columns"], out_dir, pii=set(ref.pii_columns()))
    except EngineError as e:
        raise DataError(str(e))
