"""Retrieval service: explicit setup, collections, incremental indexing and search.

Nothing here has a default. If the user has not completed Retrieval Setup (and both tests passed), every entry point
refuses with a message that says what to do.
"""
import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings as app_settings
from app.core.database import SessionLocal, engine
from app.models.connection import Connection
from app.models.rag import RagCollection, RagDocument, RagSettings
from app.rag.chunking import chunk_text
from app.rag.embedders import EmbedError, Embedder, get_embedder, test_embedder
from app.rag.stores import REST_STORES, PgVectorStore, Point, StoreError, VectorStore, point_id

NOT_SET_UP = ("Retrieval is not set up yet. Open the Retrieval page, choose an embedding model and a vector store, "
              "and run the connection tests. Nothing is chosen for you.")
_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,98}$")
MAX_CHUNKS_PER_RUN = 20_000
EMBED_BATCH = 64


class RagError(Exception):
    """A user-facing retrieval problem (setup missing, mismatch, bad settings)."""


def _run(fn):
    return asyncio.to_thread(fn)


# ── settings ────────────────────────────────────────────────────────────────────

def load_settings(user_id) -> Optional[RagSettings]:
    with SessionLocal() as db:
        s = db.query(RagSettings).filter(RagSettings.user_id == user_id).first()
        if s:
            db.expunge(s)
        return s


def require_ready(user_id) -> RagSettings:
    s = load_settings(user_id)
    if s is None:
        raise RagError(NOT_SET_UP)
    if not s.ready:
        bad = []
        if not s.embed_ok:
            bad.append(f"embedding model ({s.embed_message or 'not tested'})")
        if not s.store_ok:
            bad.append(f"vector store ({s.store_message or 'not tested'})")
        raise RagError("Retrieval setup is incomplete: " + "; ".join(bad) + ". Fix it on the Retrieval page and re-run the tests.")
    return s


def build_embedder(s: RagSettings) -> Embedder:
    try:
        return get_embedder(s.embed_provider, s.embed_model, s.embed_dim, s.embed_api_key)
    except EmbedError as e:
        raise RagError(str(e))


def build_store(s: RagSettings) -> VectorStore:
    if s.store_type == "pgvector":
        return PgVectorStore(engine)
    cls = REST_STORES.get(s.store_type)
    if cls is None:
        raise RagError(f"Unknown vector store '{s.store_type}'")
    with SessionLocal() as db:
        c = db.query(Connection).filter(Connection.id == s.connection_id, Connection.user_id == s.user_id).first()
        if c is None:
            raise RagError("The saved connection for your vector store no longer exists. Pick one on the Retrieval page.")
        if c.type != s.store_type:
            raise RagError(f"The connection '{c.name}' is a {c.type} connection, not {s.store_type}")
        cfg, allow = json.loads(c.config or "{}"), list(c.host_allowlist or [])
    try:
        return cls(cfg.get("url", ""), cfg.get("api_key"), allow)
    except StoreError as e:
        raise RagError(str(e))


async def save_and_test(user_id, *, embed_provider: str, embed_model: str, embed_dim: int, embed_api_key: Optional[str],
                        store_type: str, connection_id: Optional[uuid.UUID]) -> RagSettings:
    """Persist the user's explicit choice, then run both tests. `ready` is true only if both pass."""
    if store_type not in ("pgvector", *REST_STORES):
        raise RagError("Choose a vector store: pgvector, qdrant, weaviate or chroma")
    if store_type != "pgvector" and connection_id is None:
        raise RagError(f"Choose a saved {store_type} connection (create one on the Connections page first)")

    def _save():
        with SessionLocal() as db:
            s = db.query(RagSettings).filter(RagSettings.user_id == user_id).first()
            key = embed_api_key
            if s is not None and key in (None, "", "********") and s.embed_provider == embed_provider:
                key = s.embed_api_key                       # keep the stored key when the form left it blank
            if s is None:
                s = RagSettings(user_id=user_id)
                db.add(s)
            s.embed_provider, s.embed_model, s.embed_dim, s.embed_api_key = embed_provider, embed_model.strip(), int(embed_dim), key or None
            s.store_type, s.connection_id = store_type, (connection_id if store_type != "pgvector" else None)
            s.embed_ok = s.store_ok = False
            s.embed_message = s.store_message = None
            db.commit()
            db.refresh(s)
            db.expunge(s)
            return s
    s = await _run(_save)

    try:
        emb = build_embedder(s)
        embed_ok, embed_msg = True, await test_embedder(emb)
    except (EmbedError, RagError) as e:
        embed_ok, embed_msg = False, str(e)
    try:
        h = await build_store(s).health()
        store_ok, store_msg = bool(h["ok"]), h["message"]
    except (StoreError, RagError) as e:
        store_ok, store_msg = False, str(e)

    def _record():
        with SessionLocal() as db:
            row = db.query(RagSettings).filter(RagSettings.user_id == user_id).first()
            row.embed_ok, row.embed_message, row.store_ok, row.store_message = embed_ok, embed_msg, store_ok, store_msg
            row.tested_at = datetime.utcnow()
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row
    return await _run(_record)


async def retest(user_id) -> RagSettings:
    s = load_settings(user_id)
    if s is None:
        raise RagError(NOT_SET_UP)
    return await save_and_test(user_id, embed_provider=s.embed_provider, embed_model=s.embed_model, embed_dim=s.embed_dim,
                               embed_api_key=None, store_type=s.store_type, connection_id=s.connection_id)


def clear_settings(user_id) -> None:
    with SessionLocal() as db:
        db.query(RagSettings).filter(RagSettings.user_id == user_id).delete()
        db.commit()


# ── collections ─────────────────────────────────────────────────────────────────

def clean_collection_name(name: str) -> str:
    name = (name or "").strip()
    if not _COLLECTION_NAME.match(name):
        raise RagError("Collection name: 1–100 characters, letters, numbers, spaces, dots, dashes or underscores")
    return name


def _bound_collection(db, s: RagSettings, name: str, create: bool) -> Tuple[Optional[RagCollection], bool]:
    c = db.query(RagCollection).filter(RagCollection.user_id == s.user_id, RagCollection.name == name).first()
    if c is None:
        if not create:
            return None, False
        c = RagCollection(user_id=s.user_id, name=name, store_type=s.store_type, connection_id=s.connection_id,
                          embed_signature=s.embed_signature, dim=s.embed_dim)
        db.add(c)
        db.flush()
        return c, True
    if c.store_type != s.store_type or c.connection_id != s.connection_id or c.embed_signature != s.embed_signature:
        raise RagError(
            f"Collection '{name}' was built with {c.store_type} + {c.embed_signature}, but your setup is now "
            f"{s.store_type} + {s.embed_signature}. Switch your setup back, or delete the collection and index it again.")
    return c, False


def list_collections(user_id) -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        out = []
        for c in db.query(RagCollection).filter(RagCollection.user_id == user_id).order_by(RagCollection.created_at.desc()).all():
            docs = db.query(RagDocument).filter(RagDocument.collection_id == c.id).all()
            out.append({"id": str(c.id), "name": c.name, "store_type": c.store_type, "embedding": c.embed_signature,
                        "documents": len(docs), "chunks": sum(d.chunk_count for d in docs),
                        "sources": sorted(d.source for d in docs)[:50], "updated_at": c.updated_at})
        return out


async def delete_collection(user_id, name: str) -> bool:
    def _find():
        with SessionLocal() as db:
            c = db.query(RagCollection).filter(RagCollection.user_id == user_id, RagCollection.name == name).first()
            if c:
                db.expunge(c)
            return c
    c = await _run(_find)
    if c is None:
        return False
    s = load_settings(user_id)
    if s and s.store_type == c.store_type and s.connection_id == c.connection_id:
        try:
            await build_store(s).drop(c.physical_name)
        except (StoreError, RagError):
            pass                                            # the store may be down; still remove our record

    def _del():
        with SessionLocal() as db:
            db.query(RagDocument).filter(RagDocument.collection_id == c.id).delete()
            db.query(RagCollection).filter(RagCollection.id == c.id).delete()
            db.commit()
    await _run(_del)
    return True


# ── indexing ────────────────────────────────────────────────────────────────────

def _hash(text: str, size: int, overlap: int) -> str:
    return hashlib.sha256(f"{size}|{overlap}|{text}".encode()).hexdigest()


async def index_documents(user_id, collection: str, docs: List[Tuple[str, str]], *, chunk_size: int = 800,
                          overlap: int = 100, remove_missing: bool = False) -> Dict[str, Any]:
    """Index (source, text) pairs. Unchanged documents are skipped, changed ones replaced, optionally stale ones removed."""
    s = require_ready(user_id)
    collection = clean_collection_name(collection)
    if not docs:
        raise RagError("There are no documents to index")
    try:
        prepared = [(src, text, chunk_text(text, chunk_size, overlap)) for src, text in docs if (text or "").strip()]
    except ValueError as e:
        raise RagError(str(e))
    if sum(len(c) for _, _, c in prepared) > MAX_CHUNKS_PER_RUN:
        raise RagError(f"That is more than {MAX_CHUNKS_PER_RUN:,} chunks in one run. Index fewer documents or use a larger chunk size.")

    def _prep():
        with SessionLocal() as db:
            c, created = _bound_collection(db, s, collection, create=True)
            existing = {d.source: d.content_hash for d in db.query(RagDocument).filter(RagDocument.collection_id == c.id).all()}
            db.commit()
            db.refresh(c)
            db.expunge(c)
            return c, created, existing
    coll, created, existing = await _run(_prep)

    store, emb = build_store(s), build_embedder(s)
    try:
        await store.ensure_collection(coll.physical_name, coll.dim)
        stats = {"collection": collection, "created": created, "added": 0, "updated": 0, "unchanged": 0, "removed": 0, "chunks": 0}
        seen = set()
        for src, text, chunks in prepared:
            seen.add(src)
            h = _hash(text, chunk_size, overlap)
            if existing.get(src) == h:
                stats["unchanged"] += 1
                continue
            if src in existing:
                await store.delete_source(coll.physical_name, src)
            vectors: List[List[float]] = []
            for i in range(0, len(chunks), EMBED_BATCH):
                vectors += await emb.embed(chunks[i:i + EMBED_BATCH], query=False)
            await store.upsert(coll.physical_name, [
                Point(point_id(collection, src, i, h), v, c, src, {"chunk": i, "chunks": len(chunks)})
                for i, (c, v) in enumerate(zip(chunks, vectors))])
            existing_before = src in existing
            await _run(lambda src=src, h=h, n=len(chunks): _record_doc(coll.id, src, h, n))
            stats["updated" if existing_before else "added"] += 1
            stats["chunks"] += len(chunks)
        if remove_missing:
            for src in set(existing) - seen:
                await store.delete_source(coll.physical_name, src)
                await _run(lambda src=src: _forget_doc(coll.id, src))
                stats["removed"] += 1
        stats["total_chunks"] = await store.count(coll.physical_name)
        return stats
    except (StoreError, EmbedError) as e:
        raise RagError(str(e))


def _record_doc(collection_id, source: str, h: str, n: int) -> None:
    with SessionLocal() as db:
        d = db.query(RagDocument).filter(RagDocument.collection_id == collection_id, RagDocument.source == source).first()
        if d is None:
            d = RagDocument(collection_id=collection_id, source=source, content_hash=h, chunk_count=n)
            db.add(d)
        else:
            d.content_hash, d.chunk_count = h, n
        db.query(RagCollection).filter(RagCollection.id == collection_id).update({"updated_at": datetime.utcnow()})
        db.commit()


def _forget_doc(collection_id, source: str) -> None:
    with SessionLocal() as db:
        db.query(RagDocument).filter(RagDocument.collection_id == collection_id, RagDocument.source == source).delete()
        db.commit()


# ── search ──────────────────────────────────────────────────────────────────────

async def search(user_id, collection: str, query: str, *, top_k: int = 4, min_score: float = 0.0) -> List[Dict[str, Any]]:
    s = require_ready(user_id)
    if not (query or "").strip():
        raise RagError("The search question is empty")
    top_k = max(1, min(int(top_k), 50))

    def _find():
        with SessionLocal() as db:
            c, _ = _bound_collection(db, s, collection, create=False)
            if c is None:
                raise RagError(f"Collection '{collection}' does not exist. Index some documents into it first.")
            db.expunge(c)
            return c
    coll = await _run(_find)
    try:
        [qv] = await build_embedder(s).embed([query], query=True)
        hits = await build_store(s).search(coll.physical_name, qv, top_k, float(min_score))
    except (StoreError, EmbedError) as e:
        raise RagError(str(e))
    return [{"text": h.text, "score": round(h.score, 4), "source": h.source, "chunk": h.meta.get("chunk")} for h in hits]
