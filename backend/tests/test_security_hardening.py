import asyncio
import time
from uuid import UUID
from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.ratelimit import limiter
from app.core.secrets import (
    extract_graph_secrets, inject_graph_secrets, redact, SECRET_SENTINEL, encrypt, decrypt,
)
from app.core.url_safety import validate_outbound_url, UnsafeURLError
from app.main import app
from app.core.database import SessionLocal, engine
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution
from app.services import code_sandbox
from app.services.workflow_executor import NodeExecutor

client = TestClient(app)
_n = 0


def _signup(activate=True, credits=None):
    global _n
    _n += 1
    limiter.reset()
    email = f"user{_n}_{int(time.time()*1000)}@example.com"
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    body = r.json()
    db = SessionLocal()
    u = db.query(User).filter(User.email == email).first()
    if activate:
        u.is_active = True
    if credits is not None:
        u.credits_total = credits
    db.commit()
    db.close()
    return email, body, {"Authorization": f"Bearer {body['access_token']}"}


GRAPH = {
    "nodes": [
        {"id": "in", "type": "inputNode", "position": {"x": 0, "y": 0}, "data": {}},
        {"id": "http", "type": "httpNode", "position": {"x": 1, "y": 0},
         "data": {"url": "https://example.com", "authType": "bearer", "authValue": "SUPERSECRET",
                  "headers": [{"key": "X-Api-Key", "value": "HDRSECRET"}, {"key": "Accept", "value": "json"}]}},
        {"id": "kyc", "type": "indianKycNode", "position": {"x": 2, "y": 0}, "data": {"apiKey": "KYCSECRET"}},
    ],
    "edges": [],
}


class SecretsTests(TestCase):
    def test_extract_and_inject_roundtrip(self):
        clean, secrets = extract_graph_secrets(GRAPH)
        self.assertNotIn("SUPERSECRET", str(clean))
        self.assertNotIn("HDRSECRET", str(clean))
        self.assertNotIn("KYCSECRET", str(clean))
        self.assertIn("Accept", str(clean))  # non-secret headers untouched
        self.assertEqual(len(secrets), 3)
        restored = inject_graph_secrets(clean, secrets)
        self.assertEqual(restored["nodes"][1]["data"]["authValue"], "SUPERSECRET")
        self.assertEqual(restored["nodes"][2]["data"]["apiKey"], "KYCSECRET")

    def test_sentinel_keeps_existing_secret(self):
        clean, secrets = extract_graph_secrets(GRAPH)
        clean2, secrets2 = extract_graph_secrets(clean, secrets)
        self.assertEqual(secrets, secrets2)
        self.assertEqual(clean, clean2)

    def test_encrypt_roundtrip_and_legacy_plaintext(self):
        enc = encrypt("sk-test-123")
        self.assertNotIn("sk-test-123", enc)
        self.assertEqual(decrypt(enc), "sk-test-123")
        self.assertEqual(decrypt("legacy-plain"), "legacy-plain")

    def test_redact(self):
        out = redact({"apiKey": "x", "kyc": {"raw_response": {"a": 1}, "document_number": "ABCDE1234F", "verified": True},
                      "_token_usage": {"total_tokens": 10}, "list": [{"authorization": "Bearer z"}]})
        self.assertEqual(out["apiKey"], "[REDACTED]")
        self.assertEqual(out["kyc"]["document_number"], "[REDACTED]")
        self.assertTrue(out["kyc"]["verified"])
        self.assertEqual(out["_token_usage"]["total_tokens"], 10)  # usage stats stay visible
        self.assertEqual(out["list"][0]["authorization"], "[REDACTED]")


class AuthApiTests(TestCase):
    def test_token_returned_once_and_stored_hashed(self):
        email, body, headers = _signup()
        token = body["api_token"]
        self.assertEqual(len(token), 64)
        db = SessionLocal()
        u = db.query(User).filter(User.email == email).first()
        self.assertIsNone(u.api_token)
        self.assertNotEqual(u.api_token_hash, token)
        db.close()
        me = client.get("/api/v1/auth/me", headers=headers).json()
        self.assertNotIn("api_token", me)
        self.assertEqual(me["api_token_prefix"], token[:8])
        # the static token still authenticates
        r = client.get("/api/v1/workflows/workflows", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)

    def test_rotate_invalidates_old_token(self):
        _, body, headers = _signup()
        old = body["api_token"]
        new = client.post("/api/v1/auth/refresh-api-token", headers=headers).json()["api_token"]
        self.assertNotEqual(old, new)
        self.assertEqual(client.get("/api/v1/workflows/workflows", headers={"Authorization": f"Bearer {old}"}).status_code, 401)
        self.assertEqual(client.get("/api/v1/workflows/workflows", headers={"Authorization": f"Bearer {new}"}).status_code, 200)

    def test_inactive_user_can_login_but_gets_403(self):
        email, _, _ = _signup(activate=False)
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
        self.assertEqual(r.status_code, 200)
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.assertEqual(client.get("/api/v1/auth/me", headers=h).status_code, 200)
        self.assertEqual(client.get("/api/v1/workflows/workflows", headers=h).status_code, 403)

    def test_login_rate_limited(self):
        email, _, _ = _signup()
        limiter.reset()
        codes = [client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass"}).status_code
                 for _ in range(settings.AUTH_RATE_LIMIT_PER_MIN + 2)]
        self.assertEqual(codes[0], 401)
        self.assertEqual(codes[-1], 429)
        limiter.reset()

    def test_jwt_honours_configured_expiry(self):
        from app.core.auth import create_access_token
        from jose import jwt
        with patch.object(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 5):
            tok = create_access_token({"sub": "x"})
        exp = jwt.decode(tok, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])["exp"]
        self.assertLess(exp - time.time(), 5 * 60 + 5)

    def test_api_token_ttl(self):
        email, body, _ = _signup()
        db = SessionLocal()
        u = db.query(User).filter(User.email == email).first()
        u.api_token_created_at = datetime.utcnow() - timedelta(days=40)
        db.commit(); db.close()
        h = {"Authorization": f"Bearer {body['api_token']}"}
        with patch.object(settings, "API_TOKEN_TTL_DAYS", 30):
            self.assertEqual(client.get("/api/v1/workflows/workflows", headers=h).status_code, 401)
        self.assertEqual(client.get("/api/v1/workflows/workflows", headers=h).status_code, 200)


def _wf_payload(graph=None, name="wf"):
    g = graph or GRAPH
    return {"name": name, "graph_data": g}


class WorkflowSecretsApiTests(TestCase):
    def test_secrets_never_returned_or_stored_in_graph(self):
        _, _, h = _signup()
        graph = {"nodes": [dict(n, position=n.get("position", {"x": 0, "y": 0})) for n in GRAPH["nodes"]], "edges": []}
        r = client.post("/api/v1/workflows/workflows", json=_wf_payload(graph), headers=h)
        self.assertEqual(r.status_code, 201, r.text)
        wf = r.json()
        self.assertNotIn("SUPERSECRET", str(wf))
        self.assertEqual(wf["graph_data"]["nodes"][1]["data"]["authValue"], SECRET_SENTINEL)
        db = SessionLocal()
        raw = db.execute(text("SELECT graph_data, secrets FROM workflows WHERE id=:i"), {"i": wf["id"].replace("-", "")}).fetchone()
        db.close()
        self.assertNotIn("SUPERSECRET", str(raw[0]))
        self.assertNotIn("SUPERSECRET", str(raw[1]))  # vault is encrypted
        self.assertTrue(raw[1].startswith("enc:v1:"))
        # saving the sentinel back must not wipe the secret
        r2 = client.put(f"/api/v1/workflows/workflows/{wf['id']}", json={"graph_data": wf["graph_data"]}, headers=h)
        self.assertEqual(r2.status_code, 200, r2.text)
        db = SessionLocal()
        w = db.query(Workflow).filter(Workflow.id == UUID(wf["id"])).first()
        from app.core.secrets import load_secrets
        self.assertIn("SUPERSECRET", load_secrets(w.secrets).values())
        db.close()


class CreditsAndExecutionTests(TestCase):
    SIMPLE = {
        "nodes": [
            {"id": "in", "type": "inputNode", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "t", "type": "transformNode", "position": {"x": 1, "y": 0}, "data": {}},
            {"id": "out", "type": "outputNode", "position": {"x": 2, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "t"},
            {"id": "e2", "source": "t", "target": "out"},
        ],
    }

    def _create(self, h):
        return client.post("/api/v1/workflows/workflows", json=_wf_payload(self.SIMPLE), headers=h).json()["id"]

    def _used(self, email):
        db = SessionLocal()
        used = db.query(User).filter(User.email == email).first().credits_used
        db.close()
        return used

    def test_insufficient_credits_blocks_before_running(self):
        email, _, h = _signup(credits=0)
        wid = self._create(h)
        r = client.post(f"/api/v1/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
        self.assertEqual(r.status_code, 402)
        db = SessionLocal()
        self.assertEqual(db.query(WorkflowExecution).filter(WorkflowExecution.workflow_id == UUID(wid)).count(), 0)
        db.close()
        self.assertEqual(self._used(email), 0)

    def test_run_charges_actual_not_estimate_and_never_exceeds_total(self):
        email, _, h = _signup(credits=1)
        wid = self._create(h)
        r = client.post(f"/api/v1/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {"a": 1}}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "completed")
        self.assertEqual(self._used(email), 1)  # transform = 1 credit
        # balance exhausted -> next run is refused up front
        r2 = client.post(f"/api/v1/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
        self.assertEqual(r2.status_code, 402)
        self.assertEqual(self._used(email), 1)

    def test_reservation_refunded_when_executor_crashes(self):
        email, _, h = _signup(credits=10)
        wid = self._create(h)
        with patch("app.services.run_service.workflow_executor.execute_workflow", side_effect=RuntimeError("boom")):
            r = client.post(f"/api/v1/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
        self.assertEqual(r.json()["status"], "failed")
        self.assertEqual(self._used(email), 0)

    def test_trigger_returns_live_output_but_persists_redacted(self):
        email, body, h = _signup(credits=10)
        wid = self._create(h)
        fake = {"status": "completed", "execution_trace": [], "final_output": {"apiKey": "live-value", "ok": 1}}
        with patch("app.services.run_service.workflow_executor.execute_workflow", return_value=fake):
            r = client.post(f"/api/v1/workflows/workflows/{wid}/trigger", json={"x": 1}, headers=h)
        self.assertEqual(r.json()["output"]["apiKey"], "live-value")
        ex = client.get(f"/api/v1/workflows/executions/{r.json()['execution_id']}", headers=h).json()
        self.assertEqual(ex["output_data"]["apiKey"], "[REDACTED]")


class SSRFTests(IsolatedAsyncioTestCase):
    async def test_blocks_internal_targets(self):
        for url in [
            "http://127.0.0.1:8000/x", "http://localhost/x", "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
            "http://0.0.0.0/", "file:///etc/passwd", "gopher://example.com/", "ftp://example.com/",
        ]:
            with self.assertRaises(UnsafeURLError, msg=url):
                await validate_outbound_url(url)

    async def test_allows_public_ip_literal_and_dev_override(self):
        await validate_outbound_url("https://8.8.8.8/")
        with patch.object(settings, "ALLOW_PRIVATE_URLS", True):
            await validate_outbound_url("http://127.0.0.1:8000/")

    async def test_http_node_refuses_private_url(self):
        res = await NodeExecutor().execute_http_node(
            {"method": "GET", "url": "http://169.254.169.254/latest/meta-data"},
            {"current_node_id": "h", "previous_output": {}},
        )
        self.assertIn("blocked", res["error"])

    async def test_kyc_custom_endpoint_refuses_private_url(self):
        res = await NodeExecutor().execute_indian_kyc_node(
            {"provider": "custom", "customEndpoint": "http://127.0.0.1:5432/", "documentField": "n"},
            {"current_node_id": "k", "previous_output": {"n": "ABCDE1234F"}},
        )
        self.assertIn("blocked", res["error"])

    async def test_redirect_to_private_is_blocked(self):
        import httpx
        from app.core import url_safety

        def handler(request):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

        real = httpx.AsyncClient
        with patch.object(url_safety.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            with self.assertRaises(UnsafeURLError):
                await url_safety.safe_request("GET", "https://8.8.8.8/")


class SandboxTests(IsolatedAsyncioTestCase):
    async def test_runs_and_returns_output(self):
        out = await code_sandbox.run_code("output = {'v': input_data['a'] * 2}", {"a": 21}, 5)
        self.assertEqual(out, {"v": 42})

    async def test_infinite_loop_is_killed(self):
        t0 = time.time()
        with self.assertRaises(asyncio.TimeoutError):
            await code_sandbox.run_code("while True:\n    pass", {}, 1)
        self.assertLess(time.time() - t0, 4)

    async def test_no_environment_or_imports(self):
        with self.assertRaises(code_sandbox.SandboxError):
            await code_sandbox.run_code("import os\noutput = dict(os.environ)", {}, 5)
        with self.assertRaises(code_sandbox.SandboxError):
            await code_sandbox.run_code("output = ().__class__.__bases__[0].__subclasses__()[0].__name__ if False else __import__('os')", {}, 5)

    async def test_introspection_primitives_removed(self):
        with self.assertRaises(code_sandbox.SandboxError):
            await code_sandbox.run_code("output = getattr(input_data, '__class__')", {}, 5)

    async def test_memory_bomb_is_contained(self):
        with self.assertRaises(code_sandbox.SandboxError):
            await code_sandbox.run_code("output = len('x' * (2 * 1024 ** 3))", {}, 10)

    async def test_error_is_reported(self):
        with self.assertRaises(code_sandbox.SandboxError):
            await code_sandbox.run_code("output = 1/0", {}, 5)


def _resp(content):
    r = MagicMock()
    r.content = content
    r.usage_metadata = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    return r


class FailClosedTests(IsolatedAsyncioTestCase):
    async def _decide(self, content, threshold=0.8):
        llm = MagicMock()
        llm.invoke.return_value = _resp(content)
        ex = NodeExecutor()
        with patch.object(NodeExecutor, "_get_llm", return_value=llm):
            return await ex.execute_decision_node({"threshold": threshold}, {"current_node_id": "d", "previous_output": {"a": 1}})

    async def test_clean_approval(self):
        r = await self._decide('{"decision": "approved", "confidence": 0.95, "reasoning": "ok"}')
        self.assertEqual(r["decision"], "approved")
        self.assertEqual(r["_active_handles"], ["approved"])

    async def test_not_approved_prose_does_not_approve(self):
        r = await self._decide("This should NOT be approved because the document looks forged. approved? no.")
        self.assertEqual(r["decision"], "rejected")
        self.assertTrue(r["malformed_output"])

    async def test_unknown_label_rejected(self):
        r = await self._decide('{"decision": "maybe", "confidence": 0.9}')
        self.assertEqual(r["decision"], "rejected")
        self.assertEqual(r["_active_handles"], ["rejected"])

    async def test_low_confidence_approval_downgraded(self):
        r = await self._decide('{"decision": "approved", "confidence": 0.3}', threshold=0.8)
        self.assertEqual(r["decision"], "rejected")

    async def test_fenced_json_parses(self):
        r = await self._decide('```json\n{"decision": "approved", "confidence": 0.9}\n```')
        self.assertEqual(r["decision"], "approved")

    async def _verify(self, content):
        llm = MagicMock()
        llm.invoke.return_value = _resp(content)
        with patch.object(NodeExecutor, "_get_llm", return_value=llm):
            return await NodeExecutor().execute_verification_node({"verificationType": "consistency"}, {"current_node_id": "v", "previous_output": {}})

    async def test_verification_reflects_model_verdict(self):
        r = await self._verify('{"result": "fail", "confidence": 0.7, "issues": ["mismatch"]}')
        self.assertEqual(r["result"], "fail")
        self.assertEqual(r["confidence"], 0.7)
        self.assertEqual(r["issues"], ["mismatch"])
        ok = await self._verify('{"result": "pass", "confidence": 0.99}')
        self.assertEqual(ok["result"], "pass")

    async def test_verification_malformed_fails_closed(self):
        r = await self._verify("Looks fine to me!")
        self.assertEqual(r["result"], "fail")


class MaintenanceTests(TestCase):
    def test_migrate_legacy_secrets(self):
        from app.core import maintenance
        db = SessionLocal()
        email = f"legacy{time.time_ns()}@example.com"
        db.execute(text(
            "INSERT INTO users (id, email, hashed_password, role, api_token, credits_total, credits_used, is_active, openai_api_key, created_at, updated_at) "
            "VALUES (:id, :e, 'x', 'USER', :t, 100, 0, true, 'sk-legacy-plain', :n, :n)"
        ), {"id": "a" * 32, "e": email, "t": "f" * 64, "n": datetime.utcnow()})
        wf_id = "b" * 32
        import json
        db.execute(text("INSERT INTO workflows (id, name, graph_data, status, created_at, updated_at, version) VALUES (:i, 'legacy', :g, 'DRAFT', :n, :n, '1')"),
                   {"i": wf_id, "g": json.dumps({"nodes": [{"id": "k", "type": "indianKycNode", "data": {"apiKey": "OLDKEY"}}], "edges": []}), "n": datetime.utcnow()})
        db.commit(); db.close()

        maintenance.migrate_secrets()

        with engine.connect() as c:
            row = c.execute(text("SELECT api_token, api_token_hash, openai_api_key FROM users WHERE email=:e"), {"e": email}).fetchone()
            wf = c.execute(text("SELECT graph_data, secrets FROM workflows WHERE id=:i"), {"i": wf_id}).fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(len(row[1]), 64)
        self.assertTrue(row[2].startswith("enc:v1:"))
        self.assertNotIn("OLDKEY", str(wf[0]))
        self.assertTrue(wf[1].startswith("enc:v1:"))
        # the legacy token keeps working after hashing
        r = client.get("/api/v1/workflows/workflows", headers={"Authorization": f"Bearer {'f' * 64}"})
        self.assertEqual(r.status_code, 200)

    def test_retention_purges_only_old_executions(self):
        from app.core import maintenance
        db = SessionLocal()
        import uuid
        wid = uuid.uuid4()
        old, new = uuid.uuid4(), uuid.uuid4()
        db.add(WorkflowExecution(id=old, workflow_id=wid, started_at=datetime.utcnow() - timedelta(days=60)))
        db.add(WorkflowExecution(id=new, workflow_id=wid, started_at=datetime.utcnow()))
        db.commit(); db.close()
        n = maintenance.purge_old_executions()
        self.assertGreaterEqual(n, 1)
        db = SessionLocal()
        self.assertIsNone(db.query(WorkflowExecution).filter(WorkflowExecution.id == old).first())
        self.assertIsNotNone(db.query(WorkflowExecution).filter(WorkflowExecution.id == new).first())
        db.close()
