import os
from unittest import TestCase, skipUnless
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.database import SessionLocal, engine
from app.core.secrets import SECRET_SENTINEL
from app.data.dataset import Column, build_dataset
from tests.helpers import admin_headers, client, signup

API = "/api/v1/connections"
IS_PG = engine.dialect.name == "postgresql"


def _pg_config(**over):
    u = urlparse(os.environ.get("TEST_DATABASE_URL", "postgresql://u@127.0.0.1:5432/d"))
    cfg = {"host": u.hostname, "port": u.port or 5432, "database": u.path.lstrip("/"),
           "user": u.username, "password": u.password or "", "sslmode": "disable"}
    cfg.update(over)
    return cfg


def _create(h, name="db", type_="postgres", config=None, **kw):
    return client.post(API, json={"name": name, "type": type_, "config": config or _pg_config(), **kw}, headers=h)


class ConnectionCrudTests(TestCase):
    def test_types_expose_field_specs(self):
        _, _, h = signup()
        types = {t["type"]: t for t in client.get(f"{API}/types", headers=h).json()}
        self.assertEqual(set(types), {"postgres", "http_api", "qdrant", "weaviate", "chroma", "mlflow", "ml_endpoint", "redshift", "clickhouse", "snowflake", "bigquery", "databricks"})
        pw = next(f for f in types["postgres"]["fields"] if f["name"] == "password")
        self.assertTrue(pw["secret"])

    def test_secrets_masked_encrypted_and_preserved(self):
        _, _, h = signup()
        r = _create(h, config=_pg_config(password="hunter2-very-secret"))
        self.assertEqual(r.status_code, 201, r.text)
        conn = r.json()
        self.assertEqual(conn["config"]["password"], SECRET_SENTINEL)
        self.assertNotIn("hunter2", str(conn))
        with engine.connect() as c:
            raw = c.execute(text("SELECT config FROM connections WHERE id=:i"), {"i": conn["id"].replace("-", "")}).scalar()
        self.assertTrue(raw.startswith("enc:v1:"))
        self.assertNotIn("hunter2", raw)

        # editing without re-sending the secret must keep it
        patched = client.patch(f"{API}/{conn['id']}", json={"config": {**conn["config"], "database": "other"}}, headers=h).json()
        self.assertEqual(patched["config"]["database"], "other")
        self.assertEqual(patched["config"]["password"], SECRET_SENTINEL)
        from app.models.connection import Connection
        from app.api.connections import _config
        from uuid import UUID
        db = SessionLocal()
        stored = _config(db.query(Connection).filter(Connection.id == UUID(conn["id"])).first())
        db.close()
        self.assertEqual(stored["password"], "hunter2-very-secret")

    def test_validation_and_duplicates(self):
        _, _, h = signup()
        self.assertEqual(_create(h, config={"host": "x"}).status_code, 422)                      # missing database/user
        self.assertEqual(_create(h, type_="mysql").status_code, 422)
        self.assertEqual(_create(h, config=_pg_config(sslmode="bogus")).status_code, 422)
        self.assertEqual(_create(h, name="same").status_code, 201)
        self.assertEqual(_create(h, name="same").status_code, 409)

    def test_isolation_between_users_and_admin_visibility(self):
        _, _, h1 = signup()
        _, _, h2 = signup()
        cid = _create(h1).json()["id"]
        self.assertEqual(client.get(f"{API}/{cid}", headers=h2).status_code, 404)
        self.assertEqual(client.delete(f"{API}/{cid}", headers=h2).status_code, 404)
        self.assertNotIn(cid, [c["id"] for c in client.get(API, headers=h2).json()])
        admin_all = client.get(API, params={"all": "true"}, headers=admin_headers()).json()
        self.assertIn(cid, [c["id"] for c in admin_all])
        self.assertEqual(client.delete(f"{API}/{cid}", headers=h1).status_code, 204)

    def test_only_admin_can_set_host_allowlist(self):
        _, _, h = signup()
        self.assertEqual(_create(h, host_allowlist=["10.0.0.5"]).status_code, 403)
        cid = _create(h, name="plain").json()["id"]
        self.assertEqual(client.patch(f"{API}/{cid}", json={"host_allowlist": ["10.0.0.5"]}, headers=h).status_code, 403)
        ok = client.patch(f"{API}/{cid}", json={"host_allowlist": ["10.0.0.5", " DB.Internal ", "bad host/x"]}, headers=admin_headers())
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["host_allowlist"], ["10.0.0.5", "db.internal"])

    def test_private_host_is_blocked_until_admin_allowlists(self):
        _, _, h = signup()
        cid = _create(h, config=_pg_config(host="127.0.0.1")).json()["id"]
        r = client.post(f"{API}/{cid}/test", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("allow-list", r.json()["message"])
        self.assertEqual(client.get(f"{API}/{cid}/discover", headers=h).status_code, 400)

    def test_http_api_connection_blocks_private_and_masks_token(self):
        _, _, h = signup()
        r = _create(h, name="api", type_="http_api",
                    config={"base_url": "http://169.254.169.254", "auth_type": "bearer", "token": "tok-123"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["config"]["token"], SECRET_SENTINEL)
        t = client.post(f"{API}/{r.json()['id']}/test", headers=h).json()
        self.assertFalse(t["ok"])
        self.assertIn("private", t["message"].lower())

    def test_test_result_is_recorded(self):
        _, _, h = signup()
        cid = _create(h, config=_pg_config(host="127.0.0.1")).json()["id"]
        client.post(f"{API}/{cid}/test", headers=h)
        c = client.get(f"{API}/{cid}", headers=h).json()
        self.assertFalse(c["last_test_ok"])
        self.assertIsNotNone(c["last_tested_at"])
        # changing config resets the result
        client.patch(f"{API}/{cid}", json={"config": {**c["config"], "port": 5999}}, headers=h)
        self.assertIsNone(client.get(f"{API}/{cid}", headers=h).json()["last_tested_at"])


@skipUnless(IS_PG, "needs a live PostgreSQL (set TEST_DATABASE_URL)")
class PostgresConnectorLiveTests(TestCase):
    @classmethod
    def setUpClass(cls):
        with engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS fm_people"))
            c.execute(text("CREATE TABLE fm_people (id serial primary key, name text, email text, age int, notes text)"))
            c.execute(text("INSERT INTO fm_people (name, email, age, notes) VALUES ('Ann','ann@example.com',31,'x'), ('Bob',NULL,40,'y')"))

    def _conn(self, h, **kw):
        cid = _create(h, name=f"live{id(kw)}{len(kw)}", config=_pg_config(**kw)).json()["id"]
        client.patch(f"{API}/{cid}", json={"host_allowlist": ["127.0.0.1"]}, headers=admin_headers())
        return cid

    def test_allowlisted_private_host_connects_read_only(self):
        _, _, h = signup()
        cid = self._conn(h)
        r = client.post(f"{API}/{cid}/test", headers=h).json()
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["details"]["read_only_session"])
        self.assertIsNotNone(r["latency_ms"])

    def test_discover_and_preview_with_pii_redaction(self):
        _, _, h = signup()
        cid = self._conn(h)
        tables = client.get(f"{API}/{cid}/discover", headers=h).json()["tables"]
        self.assertIn({"schema": "public", "name": "fm_people", "type": "table"}, tables)

        ds = client.get(f"{API}/{cid}/preview", params={"schema": "public", "table": "fm_people"}, headers=h).json()
        self.assertEqual([c["name"] for c in ds["columns"]], ["id", "name", "email", "age", "notes"])
        email = next(c for c in ds["columns"] if c["name"] == "email")
        self.assertIn("pii", email["tags"])
        self.assertEqual(ds["sample"][0]["email"], "[REDACTED]")          # PII never leaves in samples
        self.assertIsNone(ds["sample"][1]["email"])                        # nulls stay null
        self.assertEqual(ds["sample"][0]["name"], "Ann")
        self.assertEqual(ds["location"]["table"], "fm_people")
        self.assertTrue(ds["row_count_is_estimate"])
        self.assertEqual(ds["lineage"][0]["operation"], "read")

    def test_preview_rejects_unknown_tables_and_injection(self):
        _, _, h = signup()
        cid = self._conn(h)
        for tbl in ("nope", 'fm_people"; DROP TABLE fm_people; --'):
            r = client.get(f"{API}/{cid}/preview", params={"schema": "public", "table": tbl}, headers=h)
            self.assertEqual(r.status_code, 400)
        with engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM fm_people")).scalar(), 2)

    def test_read_only_session_blocks_writes(self):
        import asyncio
        from app.connectors.postgres import PostgresConnector
        import psycopg2

        async def go():
            conn = await PostgresConnector()._connect(_pg_config(), "read_only", ["127.0.0.1"])
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO fm_people (name) VALUES ('hacker')")
            finally:
                conn.close()

        with self.assertRaises(psycopg2.errors.ReadOnlySqlTransaction):
            asyncio.run(go())

    def test_bad_credentials_give_a_clean_message(self):
        _, _, h = signup()
        cid = self._conn(h, password="wrong-password", user="nobody")
        r = client.post(f"{API}/{cid}/test", headers=h).json()
        self.assertFalse(r["ok"])
        self.assertNotIn("wrong-password", r["message"])


class DatasetRefTests(TestCase):
    def test_pii_tagging_redaction_caps_and_stats(self):
        cols = [Column(name="id", type="int"), Column(name="Email"), Column(name="phone_number"),
                Column(name="notes"), Column(name="aadhaar_no")]
        rows = [{"id": i, "Email": f"u{i}@x.com", "phone_number": "999", "notes": "n" * 500, "aadhaar_no": None}
                for i in range(300)]
        ds = build_dataset(cols, rows, row_count=300, sample_limit=50)
        self.assertEqual(ds.pii_columns(), ["Email", "phone_number", "aadhaar_no"])
        self.assertEqual(len(ds.sample), 50)
        self.assertEqual(ds.sample[0]["Email"], "[REDACTED]")
        self.assertIsNone(ds.sample[0]["aadhaar_no"])
        self.assertLess(len(ds.sample[0]["notes"]), 250)                     # cell truncated
        self.assertEqual(next(s for s in ds.stats if s.name == "id").distinct_in_sample, 50)
        self.assertEqual(len(build_dataset(cols, rows, sample_limit=10_000).sample), 300)  # hard cap is 1000
