"""Retrieval nodes: Index documents and Retrieve passages (RAG Answer lives in the executor because it calls the LLM)."""
import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import pyarrow.parquet as pq

from app.core.database import SessionLocal
from app.models.rag import RagFile
from app.rag import service as rag
from app.rag.chunking import ExtractError, extract_text
from app.services import dataset_service as ds
from app.services import data_nodes
from app.storage.local import storage

RAG_NODE_TYPES = {"indexDocsNode", "retrieveNode", "ragAnswerNode"}
MAX_TEXT_ROWS = 5000


def _user_id(context: Dict[str, Any]):
    uid = context.get("_user_id")
    if not uid:
        raise rag.RagError("Retrieval nodes can only run for a signed-in user")
    return uid


def _flat(previous: Any) -> Dict[str, Any]:
    if not isinstance(previous, dict):
        return {}
    if isinstance(previous.get("inputs"), dict):
        return previous["inputs"]
    if isinstance(previous.get("transformed"), dict):
        return previous["transformed"]
    return previous


def render(template: str, previous: Any) -> str:
    data = _flat(previous)

    def sub(m: "re.Match[str]") -> str:
        val: Any = data
        for part in m.group(1).strip().split("."):
            val = val.get(part) if isinstance(val, dict) else None
        return "" if val is None else str(val)
    return re.sub(r"\{\{([^}]+)\}\}", sub, template or "").strip()


def _num(v: Any, default: float, lo: float, hi: float, what: str) -> float:
    try:
        x = float(v if v not in (None, "") else default)
    except (TypeError, ValueError):
        raise rag.RagError(f"{what} must be a number")
    return max(lo, min(hi, x))


def _load_files(user_id, names: List[str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    with SessionLocal() as db:
        q = db.query(RagFile).filter(RagFile.user_id == user_id)
        rows = q.all()
        if names:
            wanted = {n.strip() for n in names if n.strip()}
            missing = wanted - {r.name for r in rows}
            if missing:
                raise rag.RagError("Document(s) not found: " + ", ".join(sorted(missing)) + ". Upload them on the Retrieval page.")
            rows = [r for r in rows if r.name in wanted]
        if not rows:
            raise rag.RagError("You have not uploaded any documents yet. Upload .txt, .md or .pdf files on the Retrieval page.")
        for r in rows:
            try:
                with open(storage.path_for(r.storage_key), "rb") as f:
                    out.append((r.name, extract_text(r.format, f.read())))
            except ExtractError as e:
                raise rag.RagError(f"{r.name}: {e}")
    return out


def _load_dataset_text(user_id, upstream, text_col: str, source_col: Optional[str]) -> List[Tuple[str, str]]:
    cols = [c["name"] for c in upstream.columns]
    if text_col not in cols:
        raise rag.RagError(f"Text column '{text_col}' was not found. Available columns: {', '.join(cols[:15])}")
    if source_col and source_col not in cols:
        raise rag.RagError(f"Source column '{source_col}' was not found. Available columns: {', '.join(cols[:15])}")
    with SessionLocal() as db:
        path = storage.path_for(ds.get_dataset(db, user_id, upstream.dataset_id).storage_key)
    table = pq.read_table(path, columns=[text_col] + ([source_col] if source_col else []))
    texts = table.column(text_col).to_pylist()[:MAX_TEXT_ROWS]
    srcs = table.column(source_col).to_pylist()[:MAX_TEXT_ROWS] if source_col else [None] * len(texts)
    return [(str(s) if s not in (None, "") else f"row-{i + 1}", str(t)) for i, (s, t) in enumerate(zip(srcs, texts)) if t]


async def run_index(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        uid = _user_id(context)
        await asyncio.to_thread(rag.require_ready, uid)          # setup problems are reported before anything else
        collection = node_data.get("collection") or ""
        size = int(_num(node_data.get("chunkSize"), 800, 100, 4000, "Chunk size"))
        overlap = int(_num(node_data.get("overlap"), 100, 0, 1000, "Overlap"))
        if node_data.get("source", "files") == "dataset":
            ups = data_nodes._upstreams(context)
            if not ups:
                return {"error": "Connect a data node (Load Data, Clean, …) before this node, or switch the source to uploaded documents."}
            text_col = (node_data.get("textColumn") or "").strip()
            if not text_col:
                raise rag.RagError("Choose the column that holds the text")
            docs = await asyncio.to_thread(_load_dataset_text, uid, ups[0], text_col, (node_data.get("sourceColumn") or "").strip() or None)
        else:
            names = [n for n in (node_data.get("fileNames") or []) if n]
            docs = await asyncio.to_thread(_load_files, uid, names)
        stats = await rag.index_documents(uid, collection, docs, chunk_size=size, overlap=overlap,
                                          remove_missing=bool(node_data.get("removeMissing")))
        return {**stats, "documents": len(docs), "note": "Unchanged documents were skipped; re-running is safe."}
    except rag.RagError as e:
        return {"error": str(e)}


async def retrieve_passages(node_data: Dict[str, Any], context: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
    uid = _user_id(context)
    return await rag.search(
        uid, node_data.get("collection") or "", query,
        top_k=int(_num(node_data.get("topK"), 4, 1, 50, "Number of passages")),
        min_score=_num(node_data.get("minScore"), 0.0, 0.0, 1.0, "Minimum score"))


async def run_retrieve(node_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        query = render(node_data.get("query") or "", context.get("previous_output"))
        if not query:
            return {"error": "The search question is empty. Write it in the node, e.g. {{question}}, and make sure the field exists upstream."}
        passages = await retrieve_passages(node_data, context, query)
        return {
            "query": query, "count": len(passages), "passages": passages,
            "context": "\n\n".join(f"[{i + 1}] ({p['source']}) {p['text']}" for i, p in enumerate(passages)),
            "top_score": passages[0]["score"] if passages else None,
        }
    except rag.RagError as e:
        return {"error": str(e)}
