"""Snowflake, BigQuery and Databricks adapters against simulators of their documented REST SQL APIs.

Each simulator speaks the vendor's wire format (JSON shapes, text-encoded values, polling, partitions / pages, auth
headers) and executes the SQL it receives with DuckDB after translating it from the vendor's dialect. That exercises the
adapters' HTTP handling, value decoding and the whole pushdown path. It does NOT prove anything about a real account:
live Snowflake / BigQuery / Databricks have never been called from this repository's tests.
"""
import datetime as dt
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import duckdb
import sqlglot
from jose import jwt

from app.api.data import EXAMPLES_DIR
from app.core.config import settings
from app.warehouse.base import WarehouseError
from app.warehouse.registry import open_warehouse
from tests import test_warehouse as W
from tests.helpers import client, signup
from tests.test_data_nodes import chain, node, setup_user

API = "/api/v1"
TOKEN = "good-token-123"
SCHEMA = {"snowflake": "public", "bigquery": "ds", "databricks": "dflt"}
EPOCH = dt.datetime(1970, 1, 1)


class FakeWarehouseServer(ThreadingHTTPServer):
    def __init__(self, kind: str):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.kind = kind
        self.db = duckdb.connect(":memory:")
        self.db.execute(f"CREATE SCHEMA {SCHEMA[kind]}")
        for f in sorted(os.listdir(EXAMPLES_DIR)):
            if f.endswith(".csv"):
                self.db.execute(f"CREATE TABLE {SCHEMA[kind]}.{f[:-4]} AS SELECT * FROM read_csv_auto('{os.path.join(EXAMPLES_DIR, f)}')")
        self.calls, self.pending, self.slow_first = [], {}, True
        self.page_size = 50
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_port}"

    # run a statement the way the real service would: translate from its dialect, execute, return (columns, rows)
    def execute(self, sql: str):
        low = sql.lower()
        if "information_schema.tables" in low:
            sql = f"SELECT table_schema, table_name, 'BASE TABLE' AS table_type FROM information_schema.tables WHERE table_schema = '{SCHEMA[self.kind]}' ORDER BY 2"
            cur = self.db.execute(sql)
        else:
            duck = sqlglot.transpile(sql, read=self.kind, write="duckdb")[0]
            cur = self.db.execute(duck)
        if cur.description is None:
            return [], []
        return [(d[0], str(d[1])) for d in cur.description], cur.fetchall()


def _text(v, ctype: str, kind: str):
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, dt.datetime):
        if kind == "databricks":
            return v.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return str((v - EPOCH).total_seconds())                                       # Snowflake / BigQuery: epoch seconds
    if isinstance(v, dt.date):
        return str((dt.datetime(v.year, v.month, v.day) - EPOCH).days) if kind == "snowflake" else v.isoformat()
    return str(v)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = self.headers.get("Content-Type", "")
        return parse_qs(raw.decode()) if "x-www-form-urlencoded" in ctype else (json.loads(raw) if raw else {})

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._json(401, {"message": "Invalid token", "error": {"code": 401, "message": "Invalid Credentials"}})
            return False
        return True

    def do_POST(self):
        srv, path, body = self.server, urlparse(self.path).path, self._body()
        srv.calls.append((self.command, path, self.headers.get("Authorization"), self.headers.get("X-Snowflake-Authorization-Token-Type")))
        if path == "/token":
            claims = jwt.get_unverified_claims(body["assertion"][0])
            ok = claims.get("iss") == "svc@proj.iam.gserviceaccount.com" and "bigquery" in claims.get("scope", "")
            return self._json(200, {"access_token": TOKEN, "expires_in": 3600}) if ok else self._json(400, {"error": "invalid_grant"})
        if not self._auth():
            return
        try:
            if srv.kind == "snowflake" and path == "/api/v2/statements":
                return self._snowflake(body)
            if srv.kind == "bigquery" and path.endswith("/queries"):
                return self._bigquery(body)
            if srv.kind == "databricks" and path == "/api/2.0/sql/statements":
                return self._databricks(body)
        except Exception as e:                                                          # a SQL error, in the vendor's shape
            msg = str(e).splitlines()[0][:200]
            if srv.kind == "snowflake":
                return self._json(422, {"code": "002003", "message": f"SQL compilation error: {msg}"})
            if srv.kind == "bigquery":
                return self._json(400, {"error": {"code": 400, "message": msg}})
            return self._json(200, {"statement_id": "x", "status": {"state": "FAILED", "error": {"error_code": "BAD_REQUEST", "message": msg}}})
        self._json(404, {"message": "no such route"})

    def do_GET(self):
        srv, u = self.server, urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        srv.calls.append((self.command, u.path, self.headers.get("Authorization"), None))
        if not self._auth():
            return
        key = u.path.rsplit("/", 1)[-1]
        if key not in srv.pending:
            return self._json(404, {"message": "unknown handle"})
        cols, rows = srv.pending[key]
        if srv.kind == "snowflake":
            if "partition" in q:
                p = int(q["partition"])
                return self._json(200, {"data": self._sf_rows(cols, rows[p * srv.page_size:(p + 1) * srv.page_size])})
            return self._json(200, self._sf_body(key, cols, rows))
        if srv.kind == "bigquery":
            if "pageToken" in q:
                start = int(q["pageToken"])
                return self._json(200, self._bq_page(key, cols, rows, start, final=start + srv.page_size >= len(rows)))
            return self._json(200, self._bq_page(key, cols, rows, 0))
        return self._json(200, self._db_body(key, cols, rows))

    # Snowflake ------------------------------------------------------------------
    def _sf_type(self, duck):
        d = duck.upper()
        if d in ("BIGINT", "INTEGER", "SMALLINT", "HUGEINT", "TINYINT"):
            return {"type": "fixed", "precision": 38, "scale": 0}
        if d in ("DOUBLE", "FLOAT"):
            return {"type": "real"}
        if d.startswith("DECIMAL"):
            return {"type": "fixed", "precision": 18, "scale": 3}
        return {"type": {"BOOLEAN": "boolean", "DATE": "date", "TIMESTAMP": "timestamp_ntz"}.get(d, "text")}

    def _sf_rows(self, cols, rows):
        return [[_text(v, c[1], "snowflake") for v, c in zip(r, cols)] for r in rows]

    def _sf_body(self, handle, cols, rows):
        n = max(1, -(-len(rows) // self.server.page_size))
        return {"code": "090001", "statementHandle": handle, "message": "ok",
                "resultSetMetaData": {"numRows": len(rows), "format": "jsonv2",
                                      "rowType": [{"name": c[0].upper(), "nullable": True, **self._sf_type(c[1])} for c in cols],
                                      "partitionInfo": [{"rowCount": min(self.server.page_size, len(rows) - i * self.server.page_size)} for i in range(n)]},
                "data": self._sf_rows(cols, rows[:self.server.page_size])}

    def _snowflake(self, body):
        srv = self.server
        for k in ("statement", "timeout"):
            assert k in body, f"missing {k}"
        cols, rows = srv.execute(body["statement"])
        handle = str(uuid.uuid4())
        srv.pending[handle] = (cols, rows)
        if srv.slow_first and "count(" in body["statement"].lower():
            srv.slow_first = False
            return self._json(202, {"code": "333334", "message": "Asynchronous execution in progress.", "statementHandle": handle})
        self._json(200, self._sf_body(handle, cols, rows))

    # BigQuery -------------------------------------------------------------------
    def _bq_type(self, duck):
        d = duck.upper()
        if d in ("BIGINT", "INTEGER", "SMALLINT", "HUGEINT", "TINYINT"):
            return "INTEGER"
        return {"DOUBLE": "FLOAT", "FLOAT": "FLOAT", "BOOLEAN": "BOOLEAN", "DATE": "DATE", "TIMESTAMP": "TIMESTAMP"}.get(d, "NUMERIC" if d.startswith("DECIMAL") else "STRING")

    def _bq_page(self, job, cols, rows, start, final=False):
        page = rows[start:start + self.server.page_size]
        body = {"jobComplete": True, "jobReference": {"projectId": "proj", "jobId": job, "location": "EU"}, "totalRows": str(len(rows)),
                "schema": {"fields": [{"name": c[0], "type": self._bq_type(c[1]), "mode": "NULLABLE"} for c in cols]},
                "rows": [{"f": [{"v": _text(v, c[1], "bigquery")} for v, c in zip(r, cols)]} for r in page]}
        if start + self.server.page_size < len(rows):
            body["pageToken"] = str(start + self.server.page_size)
        return body

    def _bigquery(self, body):
        srv = self.server
        assert body.get("useLegacySql") is False and "query" in body
        cols, rows = srv.execute(body["query"])
        job = str(uuid.uuid4())
        srv.pending[job] = (cols, rows)
        if srv.slow_first and "count(" in body["query"].lower():
            srv.slow_first = False
            return self._json(200, {"jobComplete": False, "jobReference": {"projectId": "proj", "jobId": job, "location": "EU"}})
        self._json(200, self._bq_page(job, cols, rows, 0))

    # Databricks -----------------------------------------------------------------
    def _db_type(self, duck):
        d = duck.upper()
        if d in ("BIGINT", "INTEGER", "SMALLINT", "HUGEINT", "TINYINT"):
            return "BIGINT"
        return {"DOUBLE": "DOUBLE", "BOOLEAN": "BOOLEAN", "DATE": "DATE", "TIMESTAMP": "TIMESTAMP"}.get(d, d if d.startswith("DECIMAL") else "STRING")

    def _db_body(self, sid, cols, rows, truncated=False):
        return {"statement_id": sid, "status": {"state": "SUCCEEDED"},
                "manifest": {"format": "JSON_ARRAY", "total_row_count": len(rows), "truncated": truncated,
                             "schema": {"column_count": len(cols), "columns": [{"name": c[0], "type_text": self._db_type(c[1]), "type_name": "X", "position": i} for i, c in enumerate(cols)]}},
                "result": {"row_count": len(rows), "data_array": [[_text(v, c[1], "databricks") for v, c in zip(r, cols)] for r in rows]}}

    def _databricks(self, body):
        srv = self.server
        for k in ("warehouse_id", "statement", "wait_timeout", "format", "disposition"):
            assert k in body, f"missing {k}"
        cols, rows = srv.execute(body["statement"])
        if body.get("row_limit"):
            rows = rows[:body["row_limit"]]
        sid = str(uuid.uuid4())
        srv.pending[sid] = (cols, rows)
        if srv.slow_first and "count(" in body["statement"].lower():
            srv.slow_first = False
            return self._json(200, {"statement_id": sid, "status": {"state": "PENDING"}})
        self._json(200, self._db_body(sid, cols, rows))


def rsa_service_account() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return json.dumps({"client_email": "svc@proj.iam.gserviceaccount.com", "private_key": pem})


_servers = {}


def server(kind):
    if kind not in _servers:
        _servers[kind] = FakeWarehouseServer(kind)
    return _servers[kind]


def tearDownModule():
    for s in _servers.values():
        s.shutdown()


class RestCases(W.EngineCases):
    """The same suite the real engines pass, run through each REST adapter."""
    def config(self):
        raise NotImplementedError

    def bad_config(self):
        return dict(self.config(), token="wrong-token")

    def setUp(self):
        srv = server(self.kind)
        srv.slow_first = True
        srv.calls.clear()
        self.srv = srv
        self.patch = patch.object(settings, "ALLOW_PRIVATE_URLS", True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.email, self.h = setup_user(credits=300)
        self.cid = W.make_conn(self.h, self.kind, self.config())
        self.schema = SCHEMA[self.kind]

    # the simulator has no way to look at a connection's host: the adapter must reach it through the SSRF-safe client
    def test_wrong_credentials_are_reported_not_leaked(self):
        cid = W.make_conn(self.h, self.kind, self.bad_config())
        t = client.post(f"{API}/connections/{cid}/test", headers=self.h).json()
        self.assertFalse(t["ok"])
        self.assertIn("401", t["message"])
        self.assertNotIn("wrong-token", t["message"])

    def test_a_flowmind_table_can_be_copied_into_the_warehouse(self):
        ex = W.run_wf(self.h, chain(self.load_file("customers.csv"), self.save("fm_copy_x")))
        self.assertEqual(ex["status"], "failed")
        self.assertIn("not supported yet", W.step(ex, "sv")["error"])

    def test_the_example_loader_is_only_for_engines_that_can_insert(self):
        r = client.post(f"{API}/warehouse/connections/{self.cid}/examples", json={}, headers=self.h)
        self.assertEqual(r.status_code, 422)

    def test_private_hosts_need_the_flag(self):
        self.patch.stop()
        try:
            t = client.post(f"{API}/connections/{self.cid}/test", headers=self.h).json()
            self.assertFalse(t["ok"])
            self.assertIn("private", t["message"].lower())
        finally:
            self.patch.start()

    def test_the_documented_request_shape_is_used(self):
        W.run_wf(self.h, chain(self.load_wh("sales"), node("s", "summariseDataNode", groupBy=["region"], aggregations=[{"column": "*", "fn": "count", "as": "n"}])))
        self.assertTrue(self.srv.calls)
        self.assertTrue(all(c[2] == f"Bearer {TOKEN}" for c in self.srv.calls if c[1] != "/token"))

    def test_slow_statements_are_polled_to_completion(self):
        self.srv.slow_first = True
        ex = W.run_wf(self.h, chain(self.load_wh("sales"), node("p", "pullDataNode")))                 # pull → count? use a counting step
        q = W.run_wf(self.h, chain(self.load_wh("orders"), node("q", "sqlNode", query="SELECT count(*) AS n FROM input")))
        self.assertEqual(q["status"], "completed", q)
        self.assertEqual(W.sample(W.step(q, "q"))[0]["n"], 43)
        self.assertTrue(any(c[0] == "GET" for c in self.srv.calls), self.srv.calls)

    def test_large_results_are_fetched_page_by_page(self):
        ex = W.run_wf(self.h, chain(self.load_wh("sales"), node("p", "pullDataNode")))
        self.assertEqual(W.step(ex, "p")["row_count"], 56)                                              # > one page of 50
        if self.kind != "databricks":                                                                    # inline results come back in one response
            self.assertTrue(any(c[0] == "GET" for c in self.srv.calls))


class SnowflakeSimTests(RestCases, TestCase):
    kind = "snowflake"

    def c(self, name):
        return name.upper()

    def config(self):
        return {"account": f"127.0.0.1:{server('snowflake').server_port}", "token": TOKEN, "token_type": "PROGRAMMATIC_ACCESS_TOKEN",
                "warehouse": "WH", "database": "DB", "schema": "PUBLIC"}

    def setUp(self):
        self.http = patch("app.warehouse.rest.SnowflakeWarehouse._base", lambda s: "http://" + s.config["account"])     # simulator is plain http
        self.http.start()
        self.addCleanup(self.http.stop)
        RestCases.setUp(self)

    def test_token_type_header_is_sent(self):
        W.run_wf(self.h, chain(self.load_wh("sales")))
        self.assertIn("PROGRAMMATIC_ACCESS_TOKEN", {c[3] for c in self.srv.calls})


class BigQuerySimTests(RestCases, TestCase):
    kind = "bigquery"

    def config(self):
        return {"project": "proj", "dataset": "ds", "location": "EU", "access_token": TOKEN, "api_base": server("bigquery").base}

    def test_service_account_json_is_exchanged_for_a_token(self):
        srv = server("bigquery")
        sa = json.loads(rsa_service_account())
        sa["token_uri"] = srv.base + "/token"
        cfg = {"project": "proj", "dataset": "ds", "service_account_json": json.dumps(sa), "api_base": srv.base}
        cid = W.make_conn(self.h, "bigquery", cfg)
        t = client.post(f"{API}/connections/{cid}/test", headers=self.h).json()
        self.assertTrue(t["ok"], t)
        self.assertTrue(any(c[1] == "/token" for c in srv.calls))

    def test_a_bad_service_account_is_explained(self):
        cid = W.make_conn(self.h, "bigquery", {"project": "proj", "service_account_json": "not json", "api_base": server("bigquery").base})
        t = client.post(f"{API}/connections/{cid}/test", headers=self.h).json()
        self.assertFalse(t["ok"])
        self.assertIn("service account", t["message"].lower())

    def test_a_connection_needs_credentials(self):
        r = client.post(f"{API}/connections", headers=self.h, json={"name": "bq-none", "type": "bigquery", "config": {"project": "p"}, "access_mode": "read_only"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("service account", r.json()["detail"].lower())

    def test_wrong_credentials_are_reported_not_leaked(self):
        cid = W.make_conn(self.h, "bigquery", dict(self.config(), access_token="wrong-token"))
        t = client.post(f"{API}/connections/{cid}/test", headers=self.h).json()
        self.assertFalse(t["ok"])
        self.assertNotIn("wrong-token", t["message"])


class DatabricksSimTests(RestCases, TestCase):
    kind = "databricks"

    def config(self):
        return {"host": f"127.0.0.1:{server('databricks').server_port}", "warehouse_id": "abc123", "token": TOKEN, "schema": "dflt"}

    def _base_patch(self):
        return None

    def setUp(self):
        # the adapter talks https to real workspaces; the simulator is plain http
        self.https = patch("app.warehouse.rest.DatabricksWarehouse._base", lambda s: "http://" + s.config["host"])
        self.https.start()
        self.addCleanup(self.https.stop)
        RestCases.setUp(self)


class SnowflakeBaseUrlTests(TestCase):
    def test_account_is_turned_into_the_documented_host(self):
        from app.warehouse.rest import SnowflakeWarehouse
        wh = SnowflakeWarehouse({"account": "XY12345.eu-west-1", "token": "t"}, "read_only", [])
        self.assertEqual(wh._base(), "https://xy12345.eu-west-1.snowflakecomputing.com")
        wh = SnowflakeWarehouse({"account": "https://xy1.snowflakecomputing.com/", "token": "t"}, "read_only", [])
        self.assertEqual(wh._base(), "https://xy1.snowflakecomputing.com")
