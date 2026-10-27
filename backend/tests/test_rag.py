"""Phase 4: explicit retrieval setup, vector stores, indexing, retrieval nodes.

Server stores are exercised against real containers when their URLs are provided:
    RAG_TEST_QDRANT_URL=http://127.0.0.1:6333  RAG_TEST_WEAVIATE_URL=http://127.0.0.1:8080
    RAG_TEST_CHROMA_URL=http://127.0.0.1:8001  TEST_DATABASE_URL=postgresql://...   (pgvector needs PostgreSQL)
"""
import asyncio
import io
import os
import uuid
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import httpx

from app.core.database import engine
from app.rag.chunking import ExtractError, chunk_text, extract_text
from app.rag.embedders import EmbedError, GeminiEmbedder, LocalHashEmbedder, OpenAIEmbedder, get_embedder
from app.rag.embedders import test_embedder as probe_embedder
from app.rag.stores import PgVectorStore, StoreError, point_id
from tests.helpers import admin_headers, client, create_workflow, credits_used, signup
from tests.test_data_nodes import chain, node

API = "/api/v1"
IS_PG = engine.dialect.name == "postgresql"
SERVERS = {k: os.environ.get(f"RAG_TEST_{k.upper()}_URL") for k in ("qdrant", "weaviate", "chroma")}


def run(coro):
    return asyncio.run(coro)


def vec(texts, dim=128):
    return run(LocalHashEmbedder("hash-v1", dim).embed(texts))


def put_settings(h, store="pgvector", conn=None, provider="local_hash", model="hash-v1", dim=128, key=None):
    body = {"embed_provider": provider, "embed_model": model, "embed_dim": dim, "embed_api_key": key,
            "store_type": store, "connection_id": conn}
    return client.put(f"{API}/rag/settings", json=body, headers=h)


def execute(h, graph):
    wid = create_workflow(h, graph)
    r = client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def trace_result(ex, node_id):
    return next(s for s in ex["execution_trace"] if s["node_id"] == node_id)["result"]


def index_node(**kw):
    return node("idx", "indexDocsNode", label="Index help centre", collection="help", source="files", **kw)


def retrieve_node(**kw):
    return node("ret", "retrieveNode", label="Find passages", collection="help", query="refund approved processed original payment method", topK=3, **kw)


# ── pure units ──────────────────────────────────────────────────────────────────

class ChunkingTests(TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text("Hello world.", 200, 20), ["Hello world."])

    def test_chunks_respect_size_and_cover_the_text(self):
        text = "\n\n".join(f"Paragraph {i}. " + "word " * 30 for i in range(20))
        chunks = chunk_text(text, 300, 60)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 300 for c in chunks))
        joined = " ".join(chunks)
        for i in range(20):
            self.assertIn(f"Paragraph {i}.", joined)

    def test_overlap_repeats_a_tail(self):
        units = [f"Sentence number {i} is here." for i in range(12)]
        chunks = chunk_text("\n\n".join(units), 120, 50)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(any(u in chunks[0] and u in chunks[1] for u in units))

    def test_a_single_huge_word_is_hard_split(self):
        chunks = chunk_text("x" * 1000, 300, 0)
        self.assertTrue(all(len(c) <= 300 for c in chunks))
        self.assertEqual(sum(len(c) for c in chunks), 1000)

    def test_bad_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            chunk_text("abc", 50, 0)
        with self.assertRaises(ValueError):
            chunk_text("abc" * 100, 200, 150)

    def test_extract_text_formats(self):
        self.assertEqual(extract_text("md", "# Hi".encode()), "# Hi")
        with self.assertRaises(ExtractError):
            extract_text("docx", b"x")
        with self.assertRaises(ExtractError):
            extract_text("pdf", b"not a pdf")

    def test_extract_text_from_a_real_pdf(self):
        from pypdf import PdfWriter
        w = PdfWriter()
        w.add_blank_page(200, 200)
        buf = io.BytesIO()
        w.write(buf)
        with self.assertRaises(ExtractError) as cm:                  # a page with no text is reported, not silently indexed
            extract_text("pdf", buf.getvalue())
        self.assertIn("No text found", str(cm.exception))


class EmbedderTests(TestCase):
    def test_hash_embedder_is_deterministic_normalised_and_matches_words(self):
        a, b, c = vec(["refunds take five business days", "refunds take five business days", "office closed on sundays"])
        self.assertEqual(a, b)
        self.assertAlmostEqual(sum(x * x for x in a), 1.0, places=5)
        dot = lambda u, v: sum(x * y for x, y in zip(u, v))
        q = vec(["how long do refunds take"])[0]
        self.assertGreater(dot(q, a), dot(q, c))

    def test_dimension_bounds_and_unknown_provider(self):
        with self.assertRaises(EmbedError):
            get_embedder("local_hash", "m", 4)
        with self.assertRaises(EmbedError):
            get_embedder("nope", "m", 128)
        with self.assertRaises(EmbedError):
            get_embedder("openai", "", 128)

    def test_hosted_providers_need_a_key(self):
        with self.assertRaises(EmbedError):
            run(OpenAIEmbedder("text-embedding-3-small", 64, None).embed(["x"]))

    def test_openai_request_and_response_shape(self):
        seen = {}

        async def fake(method, url, **kw):
            seen.update(url=url, body=kw["json"], headers=kw["headers"])
            return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})
        with patch("app.rag.embedders.safe_request", fake):
            out = run(OpenAIEmbedder("text-embedding-3-small", 2, "sk-test").embed(["a", "b"]))
        self.assertEqual(out, [[1.0, 0.0], [0.0, 1.0]])                  # re-ordered by index
        self.assertEqual(seen["body"]["dimensions"], 2)
        self.assertTrue(seen["url"].endswith("/v1/embeddings"))
        self.assertEqual(seen["headers"]["Authorization"], "Bearer sk-test")

    def test_gemini_request_and_normalisation(self):
        seen = {}

        async def fake(method, url, **kw):
            seen.update(url=url, body=kw["json"], headers=kw["headers"])
            return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}]})
        with patch("app.rag.embedders.safe_request", fake):
            out = run(GeminiEmbedder("gemini-embedding-001", 2, "g-key").embed(["hi"], query=True))
        self.assertAlmostEqual(out[0][0], 0.6)
        self.assertEqual(seen["body"]["requests"][0]["taskType"], "RETRIEVAL_QUERY")
        self.assertEqual(seen["headers"]["x-goog-api-key"], "g-key")
        self.assertNotIn("g-key", seen["url"])                           # the key never travels in the URL

    def test_provider_errors_do_not_leak_the_key(self):
        async def fake(method, url, **kw):
            return httpx.Response(401, text="bad key sk-secret-123")
        with patch("app.rag.embedders.safe_request", fake):
            with self.assertRaises(EmbedError) as cm:
                run(OpenAIEmbedder("m", 64, "sk-secret-123").embed(["x"]))
        self.assertNotIn("sk-secret-123", str(cm.exception))
        self.assertIn("401", str(cm.exception))

    def test_fastembed_reports_a_clear_install_hint_when_missing(self):
        with patch.dict("sys.modules", {"fastembed": None}):
            with self.assertRaises(EmbedError) as cm:
                run(probe_embedder(get_embedder("fastembed", "BAAI/bge-small-en-v1.5", 384)))
        self.assertIn("pip install fastembed", str(cm.exception))

    def test_point_ids_are_stable_and_content_sensitive(self):
        self.assertEqual(point_id("c", "a.md", 0, "h1"), point_id("c", "a.md", 0, "h1"))
        self.assertNotEqual(point_id("c", "a.md", 0, "h1"), point_id("c", "a.md", 0, "h2"))


# ── explicit setup: nothing works until the user has chosen and tested ───────────

class ExplicitSetupTests(TestCase):
    def test_there_is_no_default_setup(self):
        _, _, h = signup(credits=50)
        s = client.get(f"{API}/rag/settings", headers=h).json()
        self.assertFalse(s["configured"])
        self.assertFalse(s["ready"])
        r = client.post(f"{API}/rag/query", json={"collection": "help", "query": "refund"}, headers=h)
        self.assertEqual(r.status_code, 422)
        self.assertIn("not set up", r.json()["detail"])
        r = client.post(f"{API}/rag/index", json={"collection": "help"}, headers=h)
        self.assertEqual(r.status_code, 422)
        self.assertIn("not set up", r.json()["detail"])

    def test_nodes_refuse_to_run_and_are_not_billed(self):
        email, _, h = signup(credits=50)
        client.post(f"{API}/rag/samples", headers=h)
        ex = execute(h, chain(index_node()))
        self.assertEqual(ex["status"], "failed")
        self.assertIn("not set up", trace_result(ex, "idx")["error"])
        self.assertEqual(credits_used(email), 0)
        ex = execute(h, chain(retrieve_node()))
        self.assertEqual(ex["status"], "failed")
        self.assertIn("not set up", trace_result(ex, "ret")["error"])

    def test_choosing_a_server_store_requires_a_connection(self):
        _, _, h = signup()
        r = put_settings(h, store="qdrant")
        self.assertEqual(r.status_code, 422)
        self.assertIn("connection", r.json()["detail"])

    def test_unknown_store_is_rejected(self):
        _, _, h = signup()
        self.assertEqual(put_settings(h, store="pinecone").status_code, 422)

    def test_hosted_embedding_without_a_key_is_not_ready(self):
        _, _, h = signup()
        s = put_settings(h, provider="openai", model="text-embedding-3-small", dim=64).json()
        self.assertFalse(s["embed_ok"])
        self.assertFalse(s["ready"])
        self.assertIn("API key", s["embed_message"])

    def test_embedding_key_is_stored_encrypted_and_never_returned(self):
        _, _, h = signup()
        s = put_settings(h, provider="openai", model="text-embedding-3-small", dim=64, key="sk-live-abc").json()
        self.assertTrue(s["has_embed_key"])
        self.assertNotIn("sk-live-abc", str(client.get(f"{API}/rag/settings", headers=h).json()))
        from app.core.database import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            raw = db.execute(text("SELECT embed_api_key FROM rag_settings")).scalars().all()
        self.assertTrue(raw)
        self.assertTrue(all("sk-live-abc" not in (r or "") for r in raw))

    @skipUnless(not IS_PG, "this case checks the non-PostgreSQL message")
    def test_pgvector_needs_postgresql(self):
        _, _, h = signup()
        s = put_settings(h).json()
        self.assertTrue(s["embed_ok"])
        self.assertFalse(s["store_ok"])
        self.assertIn("PostgreSQL", s["store_message"])

    def test_catalog_lists_every_supported_option(self):
        _, _, h = signup()
        c = client.get(f"{API}/rag/catalog", headers=h).json()
        self.assertEqual([s["type"] for s in c["stores"]], ["pgvector", "qdrant", "weaviate", "chroma"])
        self.assertEqual([e["provider"] for e in c["embedders"]], ["local_hash", "fastembed", "openai", "gemini"])
        self.assertTrue(all(s["docker"] for s in c["stores"] if s["needs_docker"]))

    def test_documents_are_validated_on_upload(self):
        _, _, h = signup()
        bad = client.post(f"{API}/rag/files", files={"file": ("notes.docx", b"x")}, headers=h)
        self.assertEqual(bad.status_code, 422)
        empty = client.post(f"{API}/rag/files", files={"file": ("empty.txt", b"   \n")}, headers=h)
        self.assertEqual(empty.status_code, 422)
        ok = client.post(f"{API}/rag/files", files={"file": ("a.md", b"# Title\n\nSome text here.")}, headers=h)
        self.assertEqual(ok.status_code, 201, ok.text)
        again = client.post(f"{API}/rag/files", files={"file": ("a.md", b"# Title\n\nNew text.")}, headers=h)
        self.assertEqual(again.status_code, 201)
        self.assertEqual(len(client.get(f"{API}/rag/files", headers=h).json()), 1)       # same name replaces

    def test_documents_are_private_to_their_owner(self):
        _, _, h1 = signup()
        _, _, h2 = signup()
        client.post(f"{API}/rag/samples", headers=h1)
        self.assertEqual(client.get(f"{API}/rag/files", headers=h2).json(), [])
        fid = client.get(f"{API}/rag/files", headers=h1).json()[0]["id"]
        self.assertEqual(client.delete(f"{API}/rag/files/{fid}", headers=h2).status_code, 404)


# ── end-to-end against a real store ─────────────────────────────────────────────

class RetrievalFlow:
    """Shared flow; subclasses decide how the store is chosen."""

    def choose_store(self):
        """Return (headers, store, connection_id)."""
        raise NotImplementedError

    def setUp(self):
        self.h, self.store, self.conn = self.choose_store()
        client.post(f"{API}/rag/samples", headers=self.h)

    def tearDown(self):
        for c in client.get(f"{API}/rag/collections", headers=self.h).json():
            client.delete(f"{API}/rag/collections/{c['name']}", headers=self.h)

    def ready(self):
        r = put_settings(self.h, self.store, self.conn)
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        self.assertTrue(s["ready"], s)
        self.assertTrue(s["embed_ok"] and s["store_ok"])

    def test_full_lifecycle(self):
        self.ready()
        idx = client.post(f"{API}/rag/index", json={"collection": "help", "chunk_size": 400, "overlap": 50}, headers=self.h)
        self.assertEqual(idx.status_code, 200, idx.text)
        first = idx.json()
        self.assertEqual((first["added"], first["updated"], first["unchanged"]), (3, 0, 0))
        self.assertEqual(first["total_chunks"], first["chunks"])

        q = client.post(f"{API}/rag/query", json={"collection": "help", "query": "how many days until a refund is processed", "top_k": 2}, headers=self.h)
        self.assertEqual(q.status_code, 200, q.text)
        top = q.json()["passages"]
        self.assertEqual(top[0]["source"], "acme-refund-policy.md")
        self.assertIn("5 business days", top[0]["text"])
        self.assertGreater(top[0]["score"], top[-1]["score"] - 1e-9)

        again = client.post(f"{API}/rag/index", json={"collection": "help", "chunk_size": 400, "overlap": 50}, headers=self.h).json()
        self.assertEqual((again["added"], again["updated"], again["unchanged"], again["chunks"]), (0, 0, 3, 0))
        self.assertEqual(again["total_chunks"], first["total_chunks"])

        client.post(f"{API}/rag/files", files={"file": ("acme-shipping.md", b"# Shipping\n\nExpress delivery now takes 24 hours exactly.")}, headers=self.h)
        edited = client.post(f"{API}/rag/index", json={"collection": "help", "chunk_size": 400, "overlap": 50}, headers=self.h).json()
        self.assertEqual((edited["updated"], edited["unchanged"]), (1, 2))
        old = client.post(f"{API}/rag/query", json={"collection": "help", "query": "express shipping 1 to 2 business days costs 12 dollars", "top_k": 6}, headers=self.h).json()["passages"]
        self.assertFalse(any("12 dollars" in p["text"] for p in old))               # the stale chunks were replaced
        new = client.post(f"{API}/rag/query", json={"collection": "help", "query": "express delivery 24 hours", "top_k": 1}, headers=self.h).json()["passages"]
        self.assertIn("24 hours", new[0]["text"])

        cols = client.get(f"{API}/rag/collections", headers=self.h).json()
        self.assertEqual((cols[0]["name"], cols[0]["documents"], cols[0]["store_type"]), ("help", 3, self.store))

    def test_min_score_filters_and_unknown_collection_is_explained(self):
        self.ready()
        client.post(f"{API}/rag/index", json={"collection": "help"}, headers=self.h)
        none = client.post(f"{API}/rag/query", json={"collection": "help", "query": "zebra xylophone quantum", "min_score": 0.9}, headers=self.h).json()
        self.assertEqual(none["passages"], [])
        r = client.post(f"{API}/rag/query", json={"collection": "ghost", "query": "x"}, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertIn("does not exist", r.json()["detail"])

    def test_index_and_retrieve_nodes_in_a_workflow(self):
        self.ready()
        ex = execute(self.h, chain(index_node(), retrieve_node()))
        self.assertEqual(ex["status"], "completed", ex)
        idx = trace_result(ex, "idx")
        self.assertEqual(idx["added"], 3)
        ret = trace_result(ex, "ret")
        self.assertEqual(ret["passages"][0]["source"], "acme-refund-policy.md")
        self.assertTrue(ret["context"].startswith("[1] (acme-refund-policy.md)"))
        again = execute(self.h, chain(index_node(), retrieve_node()))
        self.assertEqual(trace_result(again, "idx")["unchanged"], 3)                 # re-running a pipeline is safe

    def test_nodes_are_billed_only_when_they_do_work(self):
        self.ready()
        email = None
        db_user = client.get(f"{API}/auth/me", headers=self.h).json()
        before = db_user["credits_used"]
        execute(self.h, chain(index_node(), retrieve_node()))
        after = client.get(f"{API}/auth/me", headers=self.h).json()["credits_used"]
        if db_user.get("role") != "admin":
            self.assertEqual(after - before, 2 + 1)

    def test_changing_the_embedding_does_not_silently_mix_vectors(self):
        self.ready()
        client.post(f"{API}/rag/index", json={"collection": "help"}, headers=self.h)
        r = put_settings(self.h, self.store, self.conn, dim=64)
        self.assertTrue(r.json()["ready"])
        q = client.post(f"{API}/rag/query", json={"collection": "help", "query": "refund"}, headers=self.h)
        self.assertEqual(q.status_code, 422)
        self.assertIn("delete the collection", q.json()["detail"])
        self.assertEqual(client.delete(f"{API}/rag/collections/help", headers=self.h).status_code, 204)

    def test_rag_answer_is_grounded_and_cites_sources(self):
        self.ready()
        client.post(f"{API}/rag/index", json={"collection": "help"}, headers=self.h)
        seen = {}

        class FakeLLM:
            def invoke(self, messages):
                seen["messages"] = messages
                return MagicMock(content="Refunds take 5 business days [1].", response_metadata={
                    "usage_metadata": {"prompt_token_count": 300, "candidates_token_count": 20, "total_token_count": 320}})
        ask = node("ask", "ragAnswerNode", label="Answer", collection="help", question="refund approved processed original payment method", topK=2)
        with patch("app.services.workflow_executor.NodeExecutor._get_llm", return_value=FakeLLM()):
            ex = execute(self.h, chain(ask))
        res = trace_result(ex, "ask")
        self.assertEqual(ex["status"], "completed", ex)
        self.assertTrue(res["grounded"])
        self.assertIn("[1]", res["answer"])
        self.assertEqual(res["citations"][0]["source"], "acme-refund-policy.md")
        prompt = str(seen["messages"])
        self.assertIn("ONLY the numbered passages", prompt)
        self.assertIn("5 business days", prompt)

    def test_rag_answer_refuses_without_calling_the_model_when_nothing_matches(self):
        self.ready()
        client.post(f"{API}/rag/index", json={"collection": "help"}, headers=self.h)
        ask = node("ask", "ragAnswerNode", label="Answer", collection="help", question="zebra xylophone quantum", minScore=0.95)
        llm = MagicMock()
        with patch("app.services.workflow_executor.NodeExecutor._get_llm", return_value=llm):
            res = trace_result(execute(self.h, chain(ask)), "ask")
        self.assertFalse(res["grounded"])
        self.assertIn("could not find", res["answer"])
        llm.invoke.assert_not_called()


@skipUnless(IS_PG, "pgvector runs inside the application's PostgreSQL (set TEST_DATABASE_URL)")
class PgVectorTests(RetrievalFlow, TestCase):
    def choose_store(self):
        _, _, h = signup(credits=200)
        return h, "pgvector", None

    def test_pgvector_store_adapter_directly(self):
        s = PgVectorStore(engine)
        self.assertTrue(run(s.health())["ok"])
        name = "fm_" + uuid.uuid4().hex[:20]
        from app.rag.stores import Point
        run(s.ensure_collection(name, 128))
        v = vec(["alpha beta gamma", "delta epsilon"])
        run(s.upsert(name, [Point(str(uuid.uuid4()), v[0], "alpha beta gamma", "a", {"k": 1}), Point(str(uuid.uuid4()), v[1], "delta epsilon", "b")]))
        hits = run(s.search(name, vec(["alpha gamma"])[0], 2))
        self.assertEqual(hits[0].source, "a")
        self.assertEqual(hits[0].meta, {"k": 1})
        self.assertEqual(run(s.count(name)), 2)
        run(s.drop(name))
        with self.assertRaises(StoreError):
            run(s.count(name))

    def test_collection_names_cannot_inject_sql(self):
        s = PgVectorStore(engine)
        with self.assertRaises(StoreError):
            run(s.count("fm_x; DROP TABLE users;--"))


def _server_case(kind):
    url = SERVERS[kind]

    @skipUnless(url, f"set RAG_TEST_{kind.upper()}_URL to a running {kind} server")
    class _Case(RetrievalFlow, TestCase):
        def choose_store(self):
            h = admin_headers()                                             # only admins may allow-list a local host
            host = urlparse(url).hostname
            r = client.post(f"{API}/connections", headers=h, json={
                "name": f"{kind}-{uuid.uuid4().hex[:6]}", "type": kind, "config": {"url": url}, "host_allowlist": [host]})
            self.assertEqual(r.status_code, 201, r.text)
            cid = r.json()["id"]
            t = client.post(f"{API}/connections/{cid}/test", headers=h).json()
            self.assertTrue(t["ok"], t)
            self.addCleanup(lambda: client.delete(f"{API}/connections/{cid}", headers=h))
            return h, kind, cid

        def test_private_server_is_blocked_without_the_admin_allow_list(self):
            _, _, h = signup()
            r = client.post(f"{API}/connections", headers=h, json={"name": f"x-{kind}", "type": kind, "config": {"url": url}})
            cid = r.json()["id"]
            t = client.post(f"{API}/connections/{cid}/test", headers=h).json()
            self.assertFalse(t["ok"])

    _Case.__name__ = f"{kind.capitalize()}ServerTests"
    return _Case


QdrantServerTests = _server_case("qdrant")
WeaviateServerTests = _server_case("weaviate")
ChromaServerTests = _server_case("chroma")
