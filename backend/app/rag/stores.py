"""Vector store adapters: pgvector (your existing PostgreSQL), Qdrant, Weaviate, Chroma.

The three server stores are driven over their plain REST APIs with the same SSRF-safe HTTP helper as the rest of the
platform, so there are no heavyweight client libraries and no client/server version lock-step. Every adapter exposes
the same small contract and returns cosine *similarity* scores in [0, 1] (higher is closer).
"""
import asyncio
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import httpx
from sqlalchemy import text as sql

from app.core.url_safety import UnsafeURLError, safe_request

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,62}$")
_NS = uuid.UUID("6f1c0a52-0d7e-4d0b-9a3e-5a2e4f6f1a11")


class StoreError(Exception):
    """A user-facing vector-store failure."""


@dataclass
class Point:
    id: str                       # uuid string
    vector: List[float]
    text: str
    source: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    id: str
    text: str
    score: float
    source: str
    meta: Dict[str, Any]


def point_id(collection: str, source: str, chunk_index: int, content_hash: str) -> str:
    """Deterministic id: re-indexing identical content overwrites instead of duplicating."""
    return str(uuid.uuid5(_NS, f"{collection}|{source}|{chunk_index}|{content_hash}"))


def _check(name: str) -> str:
    if not _NAME.match(name):
        raise StoreError("Invalid collection name")
    return name


class VectorStore(ABC):
    type: str

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """Return {"ok": bool, "message": str, "version": Optional[str]}."""

    @abstractmethod
    async def ensure_collection(self, name: str, dim: int) -> None: ...

    @abstractmethod
    async def upsert(self, name: str, points: List[Point]) -> None: ...

    @abstractmethod
    async def delete_source(self, name: str, source: str) -> None: ...

    @abstractmethod
    async def search(self, name: str, vector: List[float], top_k: int, min_score: float = 0.0) -> List[Hit]: ...

    @abstractmethod
    async def count(self, name: str) -> int: ...

    @abstractmethod
    async def drop(self, name: str) -> None: ...


# ── pgvector (the existing PostgreSQL) ──────────────────────────────────────────

class PgVectorStore(VectorStore):
    type = "pgvector"

    def __init__(self, engine):
        self.engine = engine

    def _tbl(self, name: str) -> str:
        return "rag_c_" + _check(name)[3:] if name.startswith("fm_") else "rag_c_" + _check(name)

    async def _run(self, fn):
        try:
            return await asyncio.to_thread(fn)
        except StoreError:
            raise
        except Exception as e:
            raise StoreError(_pg_message(e))

    async def health(self):
        def _h():
            if self.engine.dialect.name != "postgresql":
                return {"ok": False, "message": "pgvector needs the application database to be PostgreSQL", "version": None}
            with self.engine.begin() as c:
                v = c.execute(sql("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
                if v is None:
                    try:
                        c.execute(sql("CREATE EXTENSION IF NOT EXISTS vector"))
                    except Exception:
                        return {"ok": False, "version": None, "message":
                                "The 'vector' extension is not installed in this database. Install pgvector on the server "
                                "(apt install postgresql-16-pgvector, or use the pgvector Docker image) and run "
                                "CREATE EXTENSION vector; as a superuser."}
                    v = c.execute(sql("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
            return {"ok": True, "message": f"pgvector {v} is available in your PostgreSQL", "version": v}
        try:
            return await asyncio.to_thread(_h)
        except Exception as e:
            return {"ok": False, "message": _pg_message(e), "version": None}

    async def ensure_collection(self, name, dim):
        t = self._tbl(name)

        def _e():
            with self.engine.begin() as c:
                c.execute(sql(f"CREATE TABLE IF NOT EXISTS {t} (id uuid PRIMARY KEY, source text NOT NULL, "
                              f"body text NOT NULL, meta jsonb NOT NULL DEFAULT '{{}}', embedding vector({int(dim)}) NOT NULL)"))
                c.execute(sql(f"CREATE INDEX IF NOT EXISTS {t}_src ON {t} (source)"))
                c.execute(sql(f"CREATE INDEX IF NOT EXISTS {t}_hnsw ON {t} USING hnsw (embedding vector_cosine_ops)"))
        await self._run(_e)

    async def upsert(self, name, points):
        t = self._tbl(name)

        def _u():
            with self.engine.begin() as c:
                for p in points:
                    c.execute(sql(
                        f"INSERT INTO {t} (id, source, body, meta, embedding) VALUES "
                        f"(CAST(:id AS uuid), :s, :b, CAST(:m AS jsonb), CAST(:v AS vector)) "
                        f"ON CONFLICT (id) DO UPDATE SET source=EXCLUDED.source, body=EXCLUDED.body, "
                        f"meta=EXCLUDED.meta, embedding=EXCLUDED.embedding"),
                        {"id": p.id, "s": p.source, "b": p.text, "m": json.dumps(p.meta), "v": _vec(p.vector)})
        await self._run(_u)

    async def delete_source(self, name, source):
        t = self._tbl(name)

        def _d():
            with self.engine.begin() as c:
                c.execute(sql(f"DELETE FROM {t} WHERE source = :s"), {"s": source})
        await self._run(_d)

    async def search(self, name, vector, top_k, min_score=0.0):
        t = self._tbl(name)

        def _s():
            with self.engine.begin() as c:
                rows = c.execute(sql(
                    f"SELECT id, source, body, meta, 1 - (embedding <=> CAST(:v AS vector)) AS score FROM {t} "
                    f"ORDER BY embedding <=> CAST(:v AS vector) LIMIT :k"), {"v": _vec(vector), "k": int(top_k)}).all()
            return [Hit(str(r[0]), r[2], float(r[4]), r[1], r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"))
                    for r in rows if float(r[4]) >= min_score]
        return await self._run(_s)

    async def count(self, name):
        t = self._tbl(name)

        def _c():
            with self.engine.begin() as c:
                return int(c.execute(sql(f"SELECT count(*) FROM {t}")).scalar() or 0)
        return await self._run(_c)

    async def drop(self, name):
        t = self._tbl(name)

        def _d():
            with self.engine.begin() as c:
                c.execute(sql(f"DROP TABLE IF EXISTS {t}"))
        await self._run(_d)


def _vec(v: List[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _pg_message(e: Exception) -> str:
    m = str(getattr(e, "orig", e)).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return m[:240]


# ── REST stores ─────────────────────────────────────────────────────────────────

class _RestStore(VectorStore):
    def __init__(self, url: str, api_key: Optional[str] = None, allow_hosts: Iterable[str] = ()):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key
        self.allow_hosts = list(allow_hosts)
        if not self.url.startswith(("http://", "https://")):
            raise StoreError("The server URL must start with http:// or https://")

    def _headers(self) -> Dict[str, str]:
        return {}

    async def _req(self, method: str, path: str, *, json_body: Any = None, ok: Iterable[int] = (200,), quiet: bool = False):
        try:
            r = await safe_request(method, self.url + path, timeout=30, allow_hosts=self.allow_hosts,
                                   headers=self._headers(), **({"json": json_body} if json_body is not None else {}))
        except UnsafeURLError as e:
            raise StoreError(str(e))
        except httpx.HTTPError as e:
            raise StoreError(f"Could not reach {self.type} at {self.url}: {type(e).__name__}")
        if r.status_code not in tuple(ok) and not (quiet and r.status_code < 500):
            raise StoreError(f"{self.type} returned HTTP {r.status_code}: {r.text[:200]}")
        return r

    async def _timed_health(self, path: str, version_of) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            r = await self._req("GET", path, ok=(200, 204))
        except StoreError as e:
            return {"ok": False, "message": str(e), "version": None}
        ver = None
        try:
            ver = version_of(r)
        except Exception:
            pass
        ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "message": f"Connected to {self.type}{' ' + str(ver) if ver else ''} ({ms} ms)", "version": ver}


class QdrantStore(_RestStore):
    type = "qdrant"

    def _headers(self):
        return {"api-key": self.api_key} if self.api_key else {}

    async def health(self):
        return await self._timed_health("/", lambda r: r.json().get("version"))

    async def ensure_collection(self, name, dim):
        name = _check(name)
        r = await self._req("GET", f"/collections/{name}", ok=(200, 404))
        if r.status_code == 404:
            await self._req("PUT", f"/collections/{name}", json_body={"vectors": {"size": int(dim), "distance": "Cosine"}})

    async def upsert(self, name, points):
        for i in range(0, len(points), 100):
            batch = points[i:i + 100]
            await self._req("PUT", f"/collections/{_check(name)}/points?wait=true", json_body={"points": [
                {"id": p.id, "vector": p.vector, "payload": {"text": p.text, "source": p.source, "meta": p.meta}}
                for p in batch]})

    async def delete_source(self, name, source):
        await self._req("POST", f"/collections/{_check(name)}/points/delete?wait=true", json_body={
            "filter": {"must": [{"key": "source", "match": {"value": source}}]}})

    async def search(self, name, vector, top_k, min_score=0.0):
        body: Dict[str, Any] = {"vector": vector, "limit": int(top_k), "with_payload": True}
        if min_score > 0:
            body["score_threshold"] = min_score
        r = await self._req("POST", f"/collections/{_check(name)}/points/search", json_body=body)
        return [Hit(str(h["id"]), h["payload"].get("text", ""), float(h["score"]), h["payload"].get("source", ""),
                    h["payload"].get("meta") or {}) for h in r.json().get("result", [])]

    async def count(self, name):
        r = await self._req("POST", f"/collections/{_check(name)}/points/count", json_body={"exact": True})
        return int(r.json()["result"]["count"])

    async def drop(self, name):
        await self._req("DELETE", f"/collections/{_check(name)}", ok=(200, 404))


class WeaviateStore(_RestStore):
    type = "weaviate"

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    @staticmethod
    def _cls(name: str) -> str:
        n = _check(name)
        return n[0].upper() + n[1:]                      # Weaviate class names must start with a capital

    async def health(self):
        return await self._timed_health("/v1/meta", lambda r: r.json().get("version"))

    async def ensure_collection(self, name, dim):
        c = self._cls(name)
        r = await self._req("GET", f"/v1/schema/{c}", ok=(200, 404))
        if r.status_code == 404:
            await self._req("POST", "/v1/schema", json_body={
                "class": c, "vectorizer": "none", "vectorIndexConfig": {"distance": "cosine"},
                "properties": [
                    {"name": "text", "dataType": ["text"], "indexFilterable": False, "indexSearchable": False},
                    {"name": "source", "dataType": ["text"], "tokenization": "field"},
                    {"name": "metaJson", "dataType": ["text"], "indexFilterable": False, "indexSearchable": False},
                ]})

    async def upsert(self, name, points):
        c = self._cls(name)
        for i in range(0, len(points), 100):
            objs = [{"class": c, "id": p.id, "vector": p.vector,
                     "properties": {"text": p.text, "source": p.source, "metaJson": json.dumps(p.meta)}}
                    for p in points[i:i + 100]]
            r = await self._req("POST", "/v1/batch/objects", json_body={"objects": objs})
            for o in r.json():
                errs = (o.get("result") or {}).get("errors")
                if errs:
                    raise StoreError("weaviate rejected an object: " + json.dumps(errs)[:200])

    async def delete_source(self, name, source):
        await self._req("DELETE", "/v1/batch/objects", json_body={"match": {
            "class": self._cls(name), "where": {"path": ["source"], "operator": "Equal", "valueText": source}}})

    async def _gql(self, query: str) -> Dict[str, Any]:
        r = await self._req("POST", "/v1/graphql", json_body={"query": query})
        data = r.json()
        if data.get("errors"):
            raise StoreError("weaviate query failed: " + json.dumps(data["errors"])[:200])
        return data["data"]

    async def search(self, name, vector, top_k, min_score=0.0):
        c = self._cls(name)
        q = ("{ Get { %s(nearVector: {vector: %s}, limit: %d) { text source metaJson _additional { id distance } } } }"
             % (c, json.dumps(vector), int(top_k)))
        rows = (await self._gql(q))["Get"][c] or []
        hits = []
        for o in rows:
            score = 1.0 - float(o["_additional"]["distance"])
            if score >= min_score:
                hits.append(Hit(o["_additional"]["id"], o["text"], score, o["source"], json.loads(o.get("metaJson") or "{}")))
        return hits

    async def count(self, name):
        c = self._cls(name)
        d = await self._gql("{ Aggregate { %s { meta { count } } } }" % c)
        return int(d["Aggregate"][c][0]["meta"]["count"])

    async def drop(self, name):
        await self._req("DELETE", f"/v1/schema/{self._cls(name)}", ok=(200, 404))


class ChromaStore(_RestStore):
    """Chroma over REST. Servers 0.5.x–0.6.x expose /api/v1; 0.7+ and 1.x expose /api/v2 (auto-detected)."""
    type = "chroma"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._base: Optional[str] = None
        self._ids: Dict[str, str] = {}

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def _prefix(self) -> str:
        if self._base is None:
            r = await self._req("GET", "/api/v2/heartbeat", ok=(200,), quiet=True)
            if r.status_code == 200:
                self._base = "/api/v2/tenants/default_tenant/databases/default_database"
            else:
                await self._req("GET", "/api/v1/heartbeat")
                self._base = "/api/v1"
        return self._base

    async def health(self):
        try:
            base = await self._prefix()
        except StoreError as e:
            return {"ok": False, "message": str(e), "version": None}
        v = None
        try:
            r = await self._req("GET", "/api/v2/version" if "v2" in base else "/api/v1/version", ok=(200,))
            v = r.text.strip().strip('"')
        except StoreError:
            pass
        return {"ok": True, "message": f"Connected to chroma {v or ''} (API {'v2' if 'v2' in base else 'v1'})".replace("  ", " "), "version": v}

    async def _coll(self, name: str, create: bool = False, dim: int = 0) -> str:
        _check(name)
        if name in self._ids:
            return self._ids[name]
        base = await self._prefix()
        if create:
            r = await self._req("POST", f"{base}/collections", json_body={
                "name": name, "get_or_create": True, "metadata": {"hnsw:space": "cosine"}})
        else:
            r = await self._req("GET", f"{base}/collections/{name}", ok=(200, 404, 500), quiet=False)
        if r.status_code != 200:
            raise StoreError("Collection not found in Chroma")
        self._ids[name] = r.json()["id"]
        return self._ids[name]

    async def ensure_collection(self, name, dim):
        await self._coll(name, create=True, dim=dim)

    async def upsert(self, name, points):
        cid, base = await self._coll(name), await self._prefix()
        for i in range(0, len(points), 100):
            b = points[i:i + 100]
            await self._req("POST", f"{base}/collections/{cid}/upsert", ok=(200, 201), json_body={
                "ids": [p.id for p in b], "embeddings": [p.vector for p in b], "documents": [p.text for p in b],
                "metadatas": [{"source": p.source, "metaJson": json.dumps(p.meta)} for p in b]})

    async def delete_source(self, name, source):
        cid, base = await self._coll(name), await self._prefix()
        await self._req("POST", f"{base}/collections/{cid}/delete", ok=(200, 201), json_body={"where": {"source": source}})

    async def search(self, name, vector, top_k, min_score=0.0):
        cid, base = await self._coll(name), await self._prefix()
        n = max(1, min(int(top_k), max(await self.count(name), 1)))
        r = await self._req("POST", f"{base}/collections/{cid}/query", ok=(200, 201), json_body={
            "query_embeddings": [vector], "n_results": n, "include": ["documents", "metadatas", "distances"]})
        d = r.json()
        hits = []
        for i, doc, m, dist in zip(d["ids"][0], d["documents"][0], d["metadatas"][0], d["distances"][0]):
            score = 1.0 - float(dist)
            if score >= min_score:
                hits.append(Hit(i, doc, score, (m or {}).get("source", ""), json.loads((m or {}).get("metaJson") or "{}")))
        return hits

    async def count(self, name):
        cid, base = await self._coll(name), await self._prefix()
        r = await self._req("GET", f"{base}/collections/{cid}/count")
        return int(r.json())

    async def drop(self, name):
        base = await self._prefix()
        await self._req("DELETE", f"{base}/collections/{_check(name)}", ok=(200, 404, 500), quiet=True)
        self._ids.pop(name, None)


REST_STORES = {"qdrant": QdrantStore, "weaviate": WeaviateStore, "chroma": ChromaStore}
