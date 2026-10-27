"""Embedding providers. Each turns text into vectors; a collection is bound to one provider+model+dimension."""
import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.url_safety import UnsafeURLError, safe_request


class EmbedError(Exception):
    """A user-facing embedding failure."""


@dataclass(frozen=True)
class EmbedderInfo:
    provider: str
    label: str
    description: str
    needs_key: bool
    models: List[Dict[str, Any]]          # [{"model", "dim", "note"}]
    local: bool
    semantic: bool
    verified_here: bool                   # exercised end-to-end in this repo's test-suite


class Embedder(ABC):
    provider: str

    def __init__(self, model: str, dim: int, api_key: Optional[str] = None):
        self.model, self.dim, self.api_key = model, dim, api_key

    @abstractmethod
    async def embed(self, texts: List[str], *, query: bool = False) -> List[List[float]]: ...


_TOKEN = re.compile(r"[a-z0-9]+")


class LocalHashEmbedder(Embedder):
    """Deterministic feature-hashing embedder: no model, no download, no network.

    It matches on *shared words* (and word pairs), not meaning, so it is a learning / offline / test option.
    """
    provider = "local_hash"

    def _vec(self, text: str) -> List[float]:
        toks = _TOKEN.findall(text.lower())
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        v = [0.0] * self.dim
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed(self, texts, *, query=False):
        return [self._vec(t) for t in texts]


class FastEmbedEmbedder(Embedder):
    """Real semantic model run locally via the optional `fastembed` package (downloads the model once)."""
    provider = "fastembed"
    _cache: Dict[str, Any] = {}

    def _model(self):
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise EmbedError("The 'fastembed' package is not installed on the server. Run: pip install fastembed")
        if self.model not in self._cache:
            try:
                self._cache[self.model] = TextEmbedding(model_name=self.model)
            except Exception as e:
                raise EmbedError(f"Could not load model '{self.model}': {str(e)[:200]}")
        return self._cache[self.model]

    async def embed(self, texts, *, query=False):
        def _run():
            m = self._model()
            return [list(map(float, v)) for v in m.embed(texts)]
        out = await asyncio.to_thread(_run)
        if out and len(out[0]) != self.dim:
            raise EmbedError(f"Model produced {len(out[0])}-dimension vectors, expected {self.dim}")
        return out


class _HostedEmbedder(Embedder):
    BATCH = 64

    def _need_key(self) -> str:
        if not self.api_key:
            raise EmbedError(f"An API key is required for {self.provider}")
        return self.api_key

    async def _post(self, url: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = await safe_request("POST", url, timeout=60, headers=headers, json=body)
        except (UnsafeURLError, httpx.HTTPError) as e:
            raise EmbedError(f"Could not reach {self.provider}: {type(e).__name__}")
        if r.status_code >= 400:
            msg = r.text[:200].replace(self.api_key or "\0", "***")
            raise EmbedError(f"{self.provider} returned HTTP {r.status_code}: {msg}")
        return r.json()


class OpenAIEmbedder(_HostedEmbedder):
    provider = "openai"

    async def embed(self, texts, *, query=False):
        key, out = self._need_key(), []
        for i in range(0, len(texts), self.BATCH):
            body: Dict[str, Any] = {"model": self.model, "input": texts[i:i + self.BATCH]}
            if self.model.startswith("text-embedding-3"):
                body["dimensions"] = self.dim
            data = await self._post("https://api.openai.com/v1/embeddings", {"Authorization": f"Bearer {key}"}, body)
            out += [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        return out


class GeminiEmbedder(_HostedEmbedder):
    provider = "gemini"

    async def embed(self, texts, *, query=False):
        key, out = self._need_key(), []
        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        for i in range(0, len(texts), self.BATCH):
            reqs = [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]},
                     "taskType": task, "outputDimensionality": self.dim} for t in texts[i:i + self.BATCH]]
            data = await self._post(url, {"x-goog-api-key": key}, {"requests": reqs})
            vecs = [e["values"] for e in data["embeddings"]]
            # truncated (Matryoshka) vectors are not unit length; normalise for cosine search
            out += [[x / (math.sqrt(sum(y * y for y in v)) or 1.0) for x in v] for v in vecs]
        return out


_CLASSES = {c.provider: c for c in (LocalHashEmbedder, FastEmbedEmbedder, OpenAIEmbedder, GeminiEmbedder)}

CATALOG: List[EmbedderInfo] = [
    EmbedderInfo("local_hash", "Local — word hashing (no model)",
                 "Runs inside FlowMind. Matches shared words, not meaning. Great for learning, offline use and tests.",
                 needs_key=False, local=True, semantic=False, verified_here=True,
                 models=[{"model": "hash-v1", "dim": 384, "note": "dimension is adjustable (64–2048)"}]),
    EmbedderInfo("fastembed", "Local — FastEmbed (real model, optional install)",
                 "A real semantic model that runs on your server's CPU. Needs `pip install fastembed` and a one-time model download.",
                 needs_key=False, local=True, semantic=True, verified_here=False,
                 models=[{"model": "BAAI/bge-small-en-v1.5", "dim": 384, "note": "fast, English"},
                         {"model": "BAAI/bge-base-en-v1.5", "dim": 768, "note": "more accurate"},
                         {"model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "dim": 384,
                          "note": "multilingual"}]),
    EmbedderInfo("openai", "OpenAI (hosted)", "Hosted embeddings. Sends your text to OpenAI. Needs your API key.",
                 needs_key=True, local=False, semantic=True, verified_here=False,
                 models=[{"model": "text-embedding-3-small", "dim": 1536, "note": "cheap, good default"},
                         {"model": "text-embedding-3-large", "dim": 3072, "note": "most accurate"}]),
    EmbedderInfo("gemini", "Google Gemini (hosted)", "Hosted embeddings. Sends your text to Google. Needs your API key.",
                 needs_key=True, local=False, semantic=True, verified_here=False,
                 models=[{"model": "gemini-embedding-001", "dim": 768, "note": "dimension adjustable (128–3072)"}]),
]


def get_embedder(provider: str, model: str, dim: int, api_key: Optional[str] = None) -> Embedder:
    cls = _CLASSES.get(provider)
    if cls is None:
        raise EmbedError(f"Unknown embedding provider '{provider}'")
    if not (16 <= int(dim) <= 4096):
        raise EmbedError("Dimension must be between 16 and 4096")
    if not (model or "").strip():
        raise EmbedError("Choose an embedding model")
    return cls(model.strip(), int(dim), api_key)


async def test_embedder(e: Embedder) -> str:
    """Embed two probes; confirm the dimension and that the vectors are usable."""
    vecs = await e.embed(["FlowMind connection test", "second probe"], query=False)
    if len(vecs) != 2 or len(vecs[0]) != e.dim:
        raise EmbedError(f"Expected {e.dim}-dimension vectors, got {len(vecs[0]) if vecs else 0}")
    if not any(abs(x) > 0 for x in vecs[0]):
        raise EmbedError("The embedder returned an all-zero vector")
    return f"OK — {e.model}, {e.dim} dimensions"
