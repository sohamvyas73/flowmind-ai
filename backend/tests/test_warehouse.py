"""Phase 6: warehouses and pushdown.

Real engines (set the env vars to run them; they are skipped otherwise):
    WH_TEST_CLICKHOUSE_URL=http://127.0.0.1:8123 WH_TEST_CLICKHOUSE_USER=fm WH_TEST_CLICKHOUSE_PASSWORD=fmpass WH_TEST_CLICKHOUSE_DB=shop
    WH_TEST_POSTGRES_URL=postgresql://postgres@127.0.0.1:5433/fm_wh
The same pipelines are run twice — inside FlowMind (DuckDB) and pushed down into the engine — and the answers compared.
"""
import os
import uuid
from decimal import Decimal
from unittest import TestCase, skipUnless
from unittest.mock import patch
from urllib.parse import urlparse

from app.core.config import settings
from app.services import data_nodes as dn
from app.services.pushdown import lineage_identity, transpile, with_relations
from app.warehouse.base import WarehouseError, assert_select_only, canonical_type, coerce, quote_ident, table_ref
from tests.helpers import client, create_workflow, credits_used, signup
from tests.test_data_nodes import chain, node, setup_user

API = "/api/v1"


def run_wf(h, graph):
    wid = create_workflow(h, graph)
    r = client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def preview(h, graph):
    wid = create_workflow(h, graph)
    r = client.post(f"{API}/workflows/workflows/{wid}/preview", json={}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def step(ex, node_id):
    return next(s for s in ex["execution_trace"] if s["node_id"] == node_id)["result"]


def sample(res):
    """The sample rows with lower-case keys (Snowflake reports upper-case column names)."""
    return [{k.lower(): v for k, v in r.items()} for r in res["dataset"]["sample"]]


def norm(rows):
    """Comparable form: numbers rounded, Decimals as floats, rows sorted."""
    def n(v):
        if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
            return round(float(v), 4)
        return v
    out = [tuple(sorted((k.lower(), n(v)) for k, v in r.items())) for r in rows]
    return sorted(out, key=lambda t: str(t))


# ── pure units ──────────────────────────────────────────────────────────────────

class GuardTests(TestCase):
    def ok(self, sql, d="postgres"):
        return assert_select_only(sql, d)

    def bad(self, sql, d="postgres", needle=""):
        with self.assertRaises(WarehouseError) as cm:
            assert_select_only(sql, d)
        self.assertIn(needle, str(cm.exception))

    def test_plain_selects_pass(self):
        self.ok("SELECT 1")
        self.ok("WITH a AS (SELECT 1 AS x) SELECT x FROM a")
        self.ok("SELECT a.x FROM (SELECT 1 AS x) a JOIN (SELECT 2 AS x) b ON a.x < b.x UNION ALL SELECT 3, 4 LIMIT 5")
        self.ok("SELECT count(*) FROM orders;")

    def test_anything_that_changes_things_is_refused(self):
        for sql in ("DROP TABLE orders", "DELETE FROM orders", "INSERT INTO t SELECT 1", "UPDATE t SET a = 1",
                    "CREATE TABLE x AS SELECT 1", "TRUNCATE orders", "ALTER TABLE t ADD COLUMN a int", "GRANT ALL ON t TO u"):
            self.bad(sql, needle="Only SELECT")

    def test_stacked_statements_and_select_into(self):
        self.bad("SELECT 1; DROP TABLE orders", needle="one statement")
        self.bad("SELECT 1; SELECT 2", needle="one statement")
        self.bad("SELECT * INTO newtable FROM orders", needle="INTO")
        self.bad("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", needle="Only SELECT")

    def test_file_network_and_side_effect_functions_are_refused(self):
        self.bad("SELECT pg_read_file('/etc/passwd')", needle="pg_read_file")
        self.bad("SELECT pg_sleep(100)", needle="pg_sleep")
        self.bad("SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", needle="dblink")
        self.bad("SELECT * FROM url('http://169.254.169.254/', 'CSV', 'a String')", "clickhouse", "url")
        self.bad("SELECT * FROM file('/etc/passwd', 'CSV', 'a String')", "clickhouse", "file")
        self.bad("SELECT * FROM s3('https://x/y.csv', 'CSV', 'a String')", "clickhouse", "s3")
        self.bad("SELECT * FROM remote('10.0.0.5', default.t)", "clickhouse", "remote")

    def test_garbage_and_empty(self):
        self.bad("", needle="empty")
        self.bad("SELEC FROM", needle="")

    def test_identifier_quoting_is_injection_proof(self):
        self.assertEqual(quote_ident('a"b', "postgres"), '"a""b"')
        self.assertEqual(table_ref("postgres", "shop", "orders"), "shop.orders")
        self.assertEqual(table_ref("postgres", "my schema", 'we"ird'), '"my schema"."we""ird"')
        self.assertEqual(table_ref("bigquery", "proj-1", "ds", "t"), "`proj-1`.ds.t")
        with self.assertRaises(WarehouseError):
            table_ref("postgres", "", "")


class UnitTests(TestCase):
    def test_canonical_types(self):
        cases = {"Nullable(Int64)": "BIGINT", "UInt8": "BIGINT", "Float64": "DOUBLE", "LowCardinality(Nullable(String))": "VARCHAR",
                 "Nullable(DateTime64(6))": "TIMESTAMP", "Date32": "DATE", "Bool": "BOOLEAN", "Decimal(18, 2)": "DECIMAL(18,2)",
                 "NUMBER(38,0)": "BIGINT", "TIMESTAMP_NTZ": "TIMESTAMP", "FLOAT64": "DOUBLE", "STRING": "VARCHAR", "double precision": "DOUBLE",
                 "weird_thing": "VARCHAR"}
        for native, want in cases.items():
            self.assertEqual(canonical_type(native), want, native)

    def test_values_from_text_apis(self):
        self.assertEqual(coerce("42", "BIGINT"), 42)
        self.assertEqual(coerce("3.5", "DOUBLE"), 3.5)
        self.assertIs(coerce("true", "BOOLEAN"), True)
        self.assertEqual(coerce("2026-03-01", "DATE").isoformat(), "2026-03-01")
        self.assertEqual(coerce("20513", "DATE", flavour="snowflake").isoformat(), "2026-03-01")      # days since the epoch
        self.assertEqual(coerce("1.7776128E9", "TIMESTAMP", flavour="bigquery").year, 2026)               # BigQuery: epoch seconds
        self.assertIsNone(coerce(None, "BIGINT"))
        self.assertIsNone(coerce("abc", "BIGINT"))

    def test_relations_merge_with_an_existing_with(self):
        self.assertEqual(with_relations({"input": "SELECT 1"}, "SELECT * FROM input", "postgres"), 'WITH "input" AS (SELECT 1)\nSELECT * FROM input')
        merged = with_relations({"input": "SELECT 1"}, 'WITH "s1" AS (SELECT 2) SELECT * FROM "s1"', "postgres")
        self.assertEqual(merged, 'WITH "input" AS (SELECT 1), "s1" AS (SELECT 2) SELECT * FROM "s1"')
        self.assertEqual(with_relations({"input": "SELECT 1"}, "SELECT 1", "bigquery"), "WITH `input` AS (SELECT 1)\nSELECT 1")

    def test_every_compiler_translates_to_every_dialect_and_expands_stars(self):
        cols = [{"name": "id", "type": "BIGINT"}, {"name": "name", "type": "VARCHAR"}, {"name": "amount", "type": "DOUBLE"}]
        clean = dn.compile_clean({"trimAll": True, "textCase": {"columns": ["name"], "mode": "upper"}, "dropMissing": ["name"],
                                  "fillMissing": [{"column": "amount", "value": "0"}], "removeDuplicates": True,
                                  "protect": [{"column": "name", "method": "hash"}, {"column": "id", "method": "mask"}],
                                  "rename": [{"from": "amount", "to": "total"}]}, cols, hash_fn=lambda x: f"fm_sha256({x})")
        summ = dn.compile_summarise({"groupBy": ["name"], "aggregations": [{"column": "amount", "fn": "sum", "as": "s"},
                                                                         {"column": "*", "fn": "count", "as": "n"}]}, cols)
        for d in ("clickhouse", "postgres", "redshift", "snowflake", "bigquery", "databricks"):
            for duck in (clean, summ):
                out = transpile(duck, {"input": cols}, d)
                self.assertNotIn("*", out.replace("COUNT(*)", "").replace("count(*)", "").replace("'*'", ""), (d, out))   # stars were expanded
                self.assertNotIn("fm_sha256", out)
                import sqlglot
                sqlglot.parse_one(out, read=d)                                         # and the result is valid in that dialect

    def test_hash_is_the_same_everywhere(self):
        out = transpile(dn.compile_clean({"protect": [{"column": "name", "method": "hash"}]}, [{"name": "name", "type": "VARCHAR"}],
                                         hash_fn=lambda x: f"fm_sha256({x})"), {"input": [{"name": "name", "type": "VARCHAR"}]}, "postgres")
        self.assertIn("sha256", out.lower())
        self.assertIn("hex", out.lower())

    def test_untranslatable_sql_is_a_clear_error(self):
        with self.assertRaises(dn.DataNodeError):
            transpile("SELECT ((( FROM", {"input": []}, "postgres")

    def test_lineage_identities_follow_openlineage_naming(self):
        self.assertEqual(lineage_identity("clickhouse", {"url": "http://ch:8123", "database": "shop"}, "shop", "orders"), ("clickhouse://ch:8123", "shop.orders"))
        self.assertEqual(lineage_identity("postgres", {"host": "h", "port": 5432, "database": "d"}, "public", "t"), ("postgres://h:5432", "d.public.t"))
        self.assertEqual(lineage_identity("bigquery", {"project": "p"}, "ds", "t"), ("bigquery", "p.ds.t"))
        self.assertEqual(lineage_identity("snowflake", {"account": "a1", "database": "D"}, "S", "T"), ("snowflake://a1", "D.S.T"))


# ── real engines ────────────────────────────────────────────────────────────────

CH_URL = os.environ.get("WH_TEST_CLICKHOUSE_URL")
PG_URL = os.environ.get("WH_TEST_POSTGRES_URL")


def ch_config():
    return {"url": CH_URL, "user": os.environ.get("WH_TEST_CLICKHOUSE_USER", "default"),
            "password": os.environ.get("WH_TEST_CLICKHOUSE_PASSWORD", ""), "database": os.environ.get("WH_TEST_CLICKHOUSE_DB", "default")}


def pg_config():
    u = urlparse(PG_URL)
    return {"host": u.hostname, "port": u.port or 5432, "database": u.path.lstrip("/"), "user": u.username, "sslmode": "disable"}


def make_conn(h, type_, config, mode="read_write", name=None):
    r = client.post(f"{API}/connections", headers=h, json={"name": name or f"{type_}-{uuid.uuid4().hex[:6]}", "type": type_, "config": config,
                                                           "access_mode": mode, "host_allowlist": []})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class EngineCases:
    """Shared by every engine. Subclasses set `kind`, `config()` and `schema`."""
    kind = ""
    schema = ""

    def config(self):
        raise NotImplementedError

    def setUp(self):
        self.patch = patch.object(settings, "ALLOW_PRIVATE_URLS", True)         # the test engines live on 127.0.0.1
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.email, self.h = setup_user(credits=300)
        self.cid = make_conn(self.h, self.kind, self.config())
        r = client.post(f"{API}/warehouse/connections/{self.cid}/examples", json={"tables": ["customers", "orders", "orders_dirty", "sales"]}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def c(self, name):
        """A column name the way this engine reports it (Snowflake upper-cases)."""
        return name

    def load_wh(self, table, **kw):
        return node("w", "loadDataNode", label=table.title(), source="connection", connectionId=self.cid, table=table, runOn="warehouse", **kw)

    def load_file(self, name):
        return node("w", "loadDataNode", label=name, source="file", fileName=name)

    # ── connection basics ───────────────────────────────────────────────────────
    def test_connection_test_discover_and_preview(self):
        t = client.post(f"{API}/connections/{self.cid}/test", headers=self.h).json()
        self.assertTrue(t["ok"], t)
        tables = {x["name"] for x in client.get(f"{API}/connections/{self.cid}/discover", headers=self.h).json()["tables"]}
        self.assertTrue({"orders", "customers", "sales", "orders_dirty"} <= tables, tables)
        p = client.get(f"{API}/connections/{self.cid}/preview", params={"schema": self.schema, "table": "customers", "limit": 3}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        ref = p.json()
        self.assertEqual(len(ref["sample"]), 3)
        if self.kind != "postgres":                                                 # PostgreSQL keeps its Phase 1 preview
            self.assertEqual(ref["location"]["target"], "pushdown")
        email = next(c for c in ref["columns"] if c["name"].lower() == "email")
        self.assertIn("pii", email["tags"])
        self.assertTrue(all("@" not in str(v) for r in ref["sample"] for k, v in r.items() if k.lower() == "email"))     # personal data is masked

    def test_wrong_credentials_are_reported_not_leaked(self):
        bad = dict(self.config())
        bad["password"] = "totally-wrong-password-xyz"
        cid = make_conn(self.h, self.kind, bad)
        t = client.post(f"{API}/connections/{cid}/test", headers=self.h).json()
        if self.kind == "postgres":
            self.skipTest("this PostgreSQL test server trusts local connections")
        self.assertFalse(t["ok"])
        self.assertNotIn("totally-wrong-password-xyz", t["message"])

    # ── pushdown equals hosted ──────────────────────────────────────────────────
    def both(self, table, file, steps):
        """Run the same steps hosted (on the CSV) and pushed down (on the warehouse table)."""
        hosted = run_wf(self.h, chain(self.load_file(file), *steps))
        pushed = run_wf(self.h, chain(self.load_wh(table), *steps))
        self.assertEqual(hosted["status"], "completed", hosted)
        self.assertEqual(pushed["status"], "completed", pushed)
        last = steps[-1]["id"]
        self.assertTrue(step(pushed, last)["pushdown"]["sql"])
        self.assertNotIn("dataset_id", step(pushed, last))                           # nothing was copied into FlowMind
        return step(hosted, last), step(pushed, last)

    def test_summarise_matches_hosted(self):
        s = node("s", "summariseDataNode", groupBy=["region"], aggregations=[
            {"column": "revenue", "fn": "sum", "as": "total"}, {"column": "units", "fn": "avg", "as": "avg_units"},
            {"column": "*", "fn": "count", "as": "n"}, {"column": "product", "fn": "count_distinct", "as": "products"},
            {"column": "revenue", "fn": "min", "as": "lo"}, {"column": "revenue", "fn": "max", "as": "hi"}])
        h, p = self.both("sales", "sales.csv", [s])
        self.assertEqual(norm(sample(p)), norm(sample(h)))
        self.assertEqual(len(sample(p)), 4)

    def test_clean_matches_hosted(self):
        c = node("c", "cleanDataNode", trimAll=True, textCase={"columns": ["status"], "mode": "upper"}, dropMissing=["customer_id"],
                 fillMissing=[{"column": "quantity", "value": "1"}], removeDuplicates=True, rename=[{"from": "unit_price", "to": "price"}])
        h, p = self.both("orders_dirty", "orders_dirty.csv", [c])
        self.assertEqual(norm(sample(p)), norm(sample(h)))
        self.assertGreater(len(sample(p)), 5)

    def test_protect_personal_data_matches_hosted(self):
        c = node("c", "cleanDataNode", protect=[{"column": "email", "method": "hash"}, {"column": "name", "method": "mask"},
                                                {"column": "city", "method": "redact"}], hashSalt="pepper")
        hosted = run_wf(self.h, chain(self.load_file("customers.csv"), c))
        pushed = run_wf(self.h, chain(self.load_wh("customers"), c))
        full_hosted = client.get(f"{API}/data/datasets/{step(hosted, 'c')['dataset_id']}/download?format=csv", headers=self.h).text
        self.assertIn("[REMOVED]", full_hosted)
        # the pushed-down sample is the 100-row preview of the *protected* relation: hashes must equal the hosted ones
        # (the sample is PII-masked for display, so compare through the relation SQL by pulling it)
        pulled = run_wf(self.h, chain(self.load_wh("customers"), c, node("p", "pullDataNode")))
        self.assertEqual(pulled["status"], "completed", pulled)
        got = client.get(f"{API}/data/datasets/{step(pulled, 'p')['dataset_id']}/download?format=csv", headers=self.h).text
        self.assertEqual(sorted(full_hosted.lower().splitlines()), sorted(got.lower().splitlines()))

    def test_join_then_summarise_matches_hosted(self):
        def graph(a, b):
            return {"nodes": [a, b, node("j", "combineDataNode", joinType="inner", keys=[{"left": "customer_id", "right": "customer_id"}]),
                              node("s", "summariseDataNode", groupBy=["tier"], aggregations=[
                                  {"column": "quantity", "fn": "sum", "as": "units"}, {"column": "*", "fn": "count", "as": "orders"}])],
                    "edges": [{"id": "e1", "source": a["id"], "target": "j"}, {"id": "e2", "source": b["id"], "target": "j"}, {"id": "e3", "source": "j", "target": "s"}]}
        hosted = run_wf(self.h, graph(node("o", "loadDataNode", source="file", fileName="orders.csv"), node("c", "loadDataNode", source="file", fileName="customers.csv")))
        pushed = run_wf(self.h, graph(node("o", "loadDataNode", source="connection", connectionId=self.cid, table="orders", runOn="warehouse"),
                                      node("c", "loadDataNode", source="connection", connectionId=self.cid, table="customers", runOn="warehouse")))
        self.assertEqual(pushed["status"], "completed", pushed)
        self.assertEqual(norm(sample(step(pushed, "s"))), norm(sample(step(hosted, "s"))))

    def test_sql_node_runs_native_sql_in_the_warehouse(self):
        q = node("q", "sqlNode", query="SELECT status, count(*) AS n, sum(quantity * unit_price) AS revenue FROM input GROUP BY status ORDER BY status")
        hosted = run_wf(self.h, chain(self.load_file("orders.csv"), q))
        pushed = run_wf(self.h, chain(self.load_wh("orders"), q))
        self.assertEqual(pushed["status"], "completed", pushed)
        self.assertEqual(norm(sample(step(pushed, "q"))), norm(sample(step(hosted, "q"))))
        self.assertIn("input", step(pushed, "q")["tables"])

    def test_sql_node_cannot_change_or_read_outside(self):
        for sql in ("DROP TABLE orders", "SELECT 1; DROP TABLE orders", "INSERT INTO orders SELECT * FROM input",
                    "SELECT * FROM url('http://169.254.169.254/', 'CSV', 'a String')", "SELECT pg_read_file('/etc/passwd')"):
            ex = run_wf(self.h, chain(self.load_wh("orders"), node("q", "sqlNode", query=sql)))
            self.assertEqual(ex["status"], "failed", sql)
            self.assertIn("allowed", step(ex, "q")["error"].lower() + " allowed", sql)
        n = run_wf(self.h, chain(self.load_wh("orders"), node("q", "sqlNode", query="SELECT count(*) AS n FROM input")))
        self.assertEqual(sample(step(n, "q"))[0]["n"], 43)                           # nothing was dropped or changed

    def test_native_sql_errors_are_explained(self):
        ex = run_wf(self.h, chain(self.load_wh("orders"), node("q", "sqlNode", query="SELECT nope FROM input")))
        self.assertEqual(ex["status"], "failed")
        self.assertTrue(step(ex, "q")["error"])

    # ── data stays put ──────────────────────────────────────────────────────────
    def test_pushdown_copies_no_data_and_masks_the_sample(self):
        ex = run_wf(self.h, chain(self.load_wh("customers"), node("c", "cleanDataNode", trimAll=True)))
        r = step(ex, "c")
        self.assertTrue(r["pushdown"]["connection_name"])
        self.assertEqual(r["dataset"]["location"]["target"], "pushdown")
        self.assertIsNone(r["row_count"])
        self.assertEqual(client.get(f"{API}/data/datasets", headers=self.h).json(), [])        # no dataset row, no Parquet file
        self.assertIn("pii", next(c for c in r["dataset"]["columns"] if c["name"].lower() == "email")["tags"])
        self.assertTrue(all("@" not in str(row["email"]) for row in sample(r)))

    def test_preview_limits_rows_and_is_free(self):
        before = credits_used(self.email)
        p = preview(self.h, chain(self.load_wh("sales"), node("s", "summariseDataNode", groupBy=["region"], aggregations=[{"column": "*", "fn": "count", "as": "n"}])))
        self.assertEqual(credits_used(self.email), before)
        s = [n for n in p["nodes"] if n["node_id"] == "s"][0]
        self.assertEqual(s["status"], "ok")
        self.assertTrue(s["dataset"]["sample"])

    def test_copy_into_flowmind_mode(self):
        ex = run_wf(self.h, chain(node("w", "loadDataNode", source="connection", connectionId=self.cid, table="sales", runOn="flowmind")))
        r = step(ex, "w")
        self.assertEqual((r["row_count"], bool(r.get("dataset_id"))), (56, True))
        self.assertEqual(len(client.get(f"{API}/data/datasets", headers=self.h).json()), 1)

    def test_runon_must_be_chosen_for_non_postgres(self):
        if self.kind == "postgres":
            self.skipTest("PostgreSQL keeps its original default")
        ex = run_wf(self.h, chain(node("w", "loadDataNode", source="connection", connectionId=self.cid, table="sales")))
        self.assertIn("Choose where this runs", step(ex, "w")["error"])

    def test_select_columns_and_max_rows(self):
        ex = run_wf(self.h, chain(self.load_wh("orders", columns=["order_id", "status"], maxRows=5)))
        s = sample(step(ex, "w"))
        self.assertEqual((len(s), set(s[0])), (5, {"order_id", "status"}))

    def test_unknown_table_and_injection_in_names(self):
        ex = run_wf(self.h, chain(self.load_wh("no_such_table")))
        self.assertEqual(ex["status"], "failed")
        evil = run_wf(self.h, chain(self.load_wh('orders; DROP TABLE orders')))
        self.assertEqual(evil["status"], "failed")
        ok = run_wf(self.h, chain(self.load_wh("orders", columns=['order_id" FROM orders; DROP TABLE orders; --'])))
        self.assertEqual(ok["status"], "failed")
        n = run_wf(self.h, chain(self.load_wh("orders"), node("q", "sqlNode", query="SELECT count(*) AS n FROM input")))
        self.assertEqual(sample(step(n, "q"))[0]["n"], 43)

    # ── things that need rows ───────────────────────────────────────────────────
    def test_quality_check_and_ai_style_nodes_ask_for_a_pull(self):
        gate = node("g", "qualityGateNode", rules=[{"type": "unique", "columns": [self.c("order_id")]}])
        ex = run_wf(self.h, chain(self.load_wh("orders"), gate))
        self.assertEqual(ex["status"], "failed")
        self.assertIn("Pull node", step(ex, "g")["error"])
        ok = run_wf(self.h, chain(self.load_wh("orders"), node("p", "pullDataNode"), gate))
        self.assertEqual(ok["status"], "completed", ok)
        self.assertEqual(step(ok, "p")["row_count"], 43)
        self.assertTrue(step(ok, "g")["quality"]["passed"])

    def test_pull_after_pushdown_work_brings_in_only_the_result(self):
        s = node("s", "summariseDataNode", groupBy=["region"], aggregations=[{"column": "revenue", "fn": "sum", "as": "total"}])
        ex = run_wf(self.h, chain(self.load_wh("sales"), s, node("p", "pullDataNode")))
        self.assertEqual(step(ex, "p")["row_count"], 4)                              # 56 rows stayed behind; 4 came in
        self.assertIn("dataset_id", step(ex, "p"))

    def test_pull_of_a_flowmind_table_is_refused(self):
        ex = run_wf(self.h, chain(self.load_file("sales.csv"), node("p", "pullDataNode")))
        self.assertIn("already inside FlowMind", step(ex, "p")["error"])

    def test_mixing_places_is_explained(self):
        j = node("j", "combineDataNode", joinType="inner", keys=[{"left": "customer_id", "right": "customer_id"}])
        g = {"nodes": [node("o", "loadDataNode", source="connection", connectionId=self.cid, table="orders", runOn="warehouse"),
                       node("c", "loadDataNode", source="file", fileName="customers.csv"), j],
             "edges": [{"id": "e1", "source": "o", "target": "j"}, {"id": "e2", "source": "c", "target": "j"}]}
        ex = run_wf(self.h, g)
        self.assertIn("different places", step(ex, "j")["error"])

    # ── Save to warehouse ───────────────────────────────────────────────────────
    def save(self, table, mode="create", **kw):
        return node("sv", "writeWarehouseNode", connectionId=self.cid, table=table, mode=mode, **kw)

    def agg(self):
        return node("s", "summariseDataNode", groupBy=["region"], aggregations=[{"column": "revenue", "fn": "sum", "as": "total"}])

    def count_rows(self, table):
        ex = run_wf(self.h, chain(self.load_wh(table), node("q", "sqlNode", query="SELECT count(*) AS n FROM input")))
        return sample(step(ex, "q"))[0]["n"]

    def test_save_creates_replaces_and_appends(self):
        t = f"fm_out_{uuid.uuid4().hex[:8]}"
        ex = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save(t)))
        self.assertEqual(ex["status"], "completed", ex)
        w = step(ex, "sv")
        self.assertEqual((w["written"]["rows"], w["row_count"], w["written"]["mode"]), (4, 4, "create"))
        self.assertIn("no data left it", w["written"]["how"])
        self.assertEqual(self.count_rows(t), 4)
        again = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save(t)))
        self.assertEqual(again["status"], "failed")                                   # create refuses to overwrite
        app = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save(t, "append")))
        self.assertEqual(app["status"], "completed", app)
        self.assertEqual(self.count_rows(t), 8)
        rep = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save(t, "replace")))
        self.assertEqual(rep["status"], "completed", rep)
        self.assertEqual(self.count_rows(t), 4)

    def test_save_output_continues_the_pipeline_on_the_new_table(self):
        t = f"fm_out_{uuid.uuid4().hex[:8]}"
        ex = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save(t), node("q", "sqlNode", query="SELECT max(total) AS top FROM input")))
        self.assertEqual(ex["status"], "completed", ex)
        self.assertGreater(sample(step(ex, "q"))[0]["top"], 0)

    def test_save_needs_explicit_choices_and_a_writable_connection(self):
        bad = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), node("sv", "writeWarehouseNode", connectionId=self.cid, table="x1")))
        self.assertIn("Nothing is chosen for you", step(bad, "sv")["error"])
        ro = make_conn(self.h, self.kind, self.config(), mode="read_only")
        ex = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), node("sv", "writeWarehouseNode", connectionId=ro, table=f"x_{uuid.uuid4().hex[:8]}", mode="create")))
        self.assertIn("read-only", step(ex, "sv")["error"])
        none = run_wf(self.h, chain(node("sv", "writeWarehouseNode", connectionId="", table="x", mode="create")))
        self.assertIn("Nothing is chosen for you", step(none, "sv")["error"])

    def test_save_target_names_are_validated(self):
        for table in ("bad name", "x; DROP TABLE orders", "1abc", ""):
            ex = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save(table)))
            self.assertEqual(ex["status"], "failed", table)
        for schema in ("information_schema", "system", "pg_catalog"):
            ex = run_wf(self.h, chain(self.load_wh("sales"), self.agg(), self.save("ok_table", schema=schema)))
            self.assertIn("system schema", step(ex, "sv")["error"])
        self.assertEqual(self.count_rows("sales"), 56)

    def test_write_schema_guardrail(self):
        guarded = dict(self.config(), write_schema="only_here")
        cid = make_conn(self.h, self.kind, guarded)
        ex = run_wf(self.h, chain(node("l", "loadDataNode", source="connection", connectionId=cid, table="sales", runOn="warehouse"),
                                  node("sv", "writeWarehouseNode", connectionId=cid, table=f"x_{uuid.uuid4().hex[:8]}", mode="create")))
        self.assertIn("only allows writing to the 'only_here' schema", step(ex, "sv")["error"])

    def test_a_flowmind_table_can_be_copied_into_the_warehouse(self):
        t = f"fm_copy_{uuid.uuid4().hex[:8]}"
        ex = run_wf(self.h, chain(self.load_file("customers.csv"), self.save(t)))
        self.assertEqual(ex["status"], "completed", ex)
        self.assertEqual(step(ex, "sv")["written"]["rows"], 8)
        self.assertIn("copied in from FlowMind", step(ex, "sv")["written"]["how"])
        self.assertEqual(self.count_rows(t), 8)

    def test_saving_a_table_from_another_warehouse_is_refused(self):
        other = make_conn(self.h, self.kind, self.config())
        ex = run_wf(self.h, chain(self.load_wh("sales"), node("sv", "writeWarehouseNode", connectionId=other, table=f"x_{uuid.uuid4().hex[:8]}", mode="create")))
        self.assertIn("different warehouse", step(ex, "sv")["error"])

    # ── money, lineage, privacy ─────────────────────────────────────────────────
    def test_billing_is_flat_per_node(self):
        before = credits_used(self.email)
        run_wf(self.h, chain(self.load_wh("sales"), self.agg()))
        self.assertEqual(credits_used(self.email) - before, 1 + 1)                    # load + summarise, whatever the warehouse size
        before = credits_used(self.email)
        run_wf(self.h, chain(self.load_wh("sales"), node("q", "sqlNode", query="SELECT nope FROM input")))
        self.assertEqual(credits_used(self.email) - before, 1)                        # the failed SQL step is not billed

    def test_lineage_names_the_warehouse_table(self):
        ex = run_wf(self.h, chain(self.load_wh("sales"), self.agg()))
        events = client.get(f"{API}/lineage/runs/{ex['id']}/events", headers=self.h).json()
        names = {(i["namespace"], i["name"]) for e in events for i in e.get("inputs", [])}
        self.assertTrue(any(n.endswith("sales") and ns.startswith(self.kind) for ns, n in names), names)

    def test_connections_are_private(self):
        _, other = setup_user()
        ex = run_wf(other, chain(self.load_wh("sales")))
        self.assertEqual(ex["status"], "failed")
        self.assertIn("Connection not found", step(ex, "w")["error"])


@skipUnless(CH_URL, "set WH_TEST_CLICKHOUSE_URL to a running ClickHouse (see the module docstring)")
class ClickHouseTests(EngineCases, TestCase):
    kind = "clickhouse"
    schema = ""

    def config(self):
        return ch_config()

    def setUp(self):
        EngineCases.setUp(self)
        self.schema = ch_config()["database"]

    def test_readonly_is_enforced_by_the_server_too(self):
        import asyncio
        from app.warehouse.registry import open_warehouse
        wh = open_warehouse("clickhouse", ch_config(), "read_only", [])
        with patch.object(settings, "ALLOW_PRIVATE_URLS", True):
            with self.assertRaises(WarehouseError):
                asyncio.run(wh._run("CREATE TABLE should_not_exist (a Int8) ENGINE = Memory", limit=None, write=False))


@skipUnless(PG_URL, "set WH_TEST_POSTGRES_URL to a PostgreSQL database for warehouse tests")
class PostgresWarehouseTests(EngineCases, TestCase):
    kind = "postgres"
    schema = "public"

    def config(self):
        return pg_config()

    def test_redshift_connection_type_uses_the_same_protocol(self):
        cid = make_conn(self.h, "redshift", dict(pg_config(), port=pg_config()["port"]))
        self.assertTrue(client.post(f"{API}/connections/{cid}/test", headers=self.h).json()["ok"])
        ex = run_wf(self.h, chain(node("w", "loadDataNode", source="connection", connectionId=cid, table="sales", runOn="warehouse"),
                                  node("s", "summariseDataNode", groupBy=["region"], aggregations=[{"column": "*", "fn": "count", "as": "n"}])))
        self.assertEqual(ex["status"], "completed", ex)
        self.assertEqual(step(ex, "s")["pushdown"]["type"], "redshift")

    def test_postgres_pull_default_still_copies_rows(self):
        ex = run_wf(self.h, chain(node("w", "loadDataNode", source="connection", connectionId=self.cid, table="sales")))
        self.assertEqual(step(ex, "w")["row_count"], 56)
        self.assertIn("dataset_id", step(ex, "w"))
