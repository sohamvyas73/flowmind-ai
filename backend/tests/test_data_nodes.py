import csv
import io
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from unittest import TestCase, skipUnless
from uuid import UUID

from sqlalchemy import text

from app.api.data import EXAMPLES_DIR
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models.data import Dataset
from app.services import data_nodes as dn
from app.services.data_nodes import DataNodeError, compile_clean, compile_combine, compile_summarise
from tests.helpers import client, create_workflow, credits_used, reset_jobs, signup

API = "/api/v1"
IS_PG = engine.dialect.name == "postgresql"


def _csv_rows(name):
    with open(os.path.join(EXAMPLES_DIR, name), newline="") as f:
        return list(csv.DictReader(f))


def node(id_, type_, **data):
    return {"id": id_, "type": type_, "position": {"x": 0, "y": 0}, "data": {"label": data.pop("label", id_), **data}}


def chain(*nodes):
    return {"nodes": list(nodes), "edges": [{"id": f"e{i}", "source": a["id"], "target": b["id"]}
                                            for i, (a, b) in enumerate(zip(nodes, nodes[1:]))]}


def setup_user(credits=50):
    email, _, h = signup(credits=credits)
    r = client.post(f"{API}/data/examples", headers=h)
    assert r.status_code == 200, r.text
    return email, h


def preview(h, wid):
    r = client.post(f"{API}/workflows/workflows/{wid}/preview", json={}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ── compilers (pure) ────────────────────────────────────────────────────────────

COLS = [{"name": "name", "type": "VARCHAR"}, {"name": "email", "type": "VARCHAR"},
        {"name": "age", "type": "BIGINT"}, {"name": "city", "type": "VARCHAR"}]


class CompilerTests(TestCase):
    def test_clean_passthrough_and_steps(self):
        self.assertEqual(compile_clean({}, COLS), "SELECT * FROM input")
        sql = compile_clean({"trimAll": True, "textCase": {"columns": ["email"], "mode": "lower"},
                             "dropMissing": ["name"], "fillMissing": [{"column": "age", "value": "0"}],
                             "removeDuplicates": True, "rename": [{"from": "city", "to": "town"}]}, COLS)
        for piece in ("trim(", "lower(", "IS NULL", "COALESCE", "DISTINCT", '"town"'):
            self.assertIn(piece, sql)

    def test_clean_errors_are_friendly(self):
        with self.assertRaisesRegex(DataNodeError, "not found.*Available columns"):
            compile_clean({"dropMissing": ["nope"]}, COLS)
        with self.assertRaisesRegex(DataNodeError, "not text"):
            compile_clean({"trimText": ["age"]}, COLS)
        with self.assertRaisesRegex(DataNodeError, "same name"):
            compile_clean({"rename": [{"from": "city", "to": "name"}]}, COLS)

    def test_identifier_quoting_blocks_injection(self):
        cols = [{"name": 'we"ird; DROP TABLE x', "type": "VARCHAR"}]
        sql = compile_clean({"dropMissing": ['we"ird; DROP TABLE x']}, cols)
        self.assertIn('"we""ird; DROP TABLE x"', sql)
        with self.assertRaises(DataNodeError):                 # names not in the input are rejected, never interpolated
            compile_summarise({"groupBy": ['x"; DROP TABLE y; --']}, cols)

    def test_combine(self):
        left = [{"name": "customer_id", "type": "BIGINT"}, {"name": "name", "type": "VARCHAR"}]
        right = [{"name": "customer_id", "type": "BIGINT"}, {"name": "name", "type": "VARCHAR"}, {"name": "total", "type": "DOUBLE"}]
        sql = compile_combine({"joinType": "left", "keys": [{"left": "customer_id", "right": "customer_id"}]}, left, right)
        self.assertIn("LEFT JOIN", sql)
        self.assertIn('"name_right"', sql)                     # clashing column gets a suffix
        self.assertEqual(sql.count('AS "customer_id"'), 1)     # shared key appears once
        with self.assertRaisesRegex(DataNodeError, "at least one column"):
            compile_combine({"joinType": "inner", "keys": []}, left, right)
        with self.assertRaisesRegex(DataNodeError, "types differ"):
            compile_combine({"keys": [{"left": "name", "right": "total"}]}, left, right)
        with self.assertRaisesRegex(DataNodeError, "Join type"):
            compile_combine({"joinType": "cross", "keys": [{"left": "name", "right": "name"}]}, left, right)

    def test_summarise(self):
        sql = compile_summarise({"groupBy": ["city"], "aggregations": [
            {"fn": "sum", "column": "age", "as": "total_age"}, {"fn": "count", "column": "*"}]}, COLS)
        self.assertIn('sum("age") AS "total_age"', sql)
        self.assertIn('count(*) AS "row_count"', sql)
        self.assertIn("GROUP BY", sql)
        with self.assertRaisesRegex(DataNodeError, "not numbers"):
            compile_summarise({"aggregations": [{"fn": "sum", "column": "name"}]}, COLS)
        with self.assertRaisesRegex(DataNodeError, "Choose a column"):
            compile_summarise({}, COLS)
        with self.assertRaisesRegex(DataNodeError, "Unknown calculation"):
            compile_summarise({"aggregations": [{"fn": "evil", "column": "age"}]}, COLS)

    def test_slug(self):
        self.assertEqual(dn.slug("Orders (March)"), "orders_march")
        self.assertEqual(dn.slug("2026 data"), "t_2026_data")


# ── end to end through the real executor + engine ──────────────────────────────

class PipelineTests(TestCase):
    def setUp(self):
        reset_jobs()

    def test_clean_and_summarise_messy_contacts(self):
        _, h = setup_user()
        wf = chain(
            node("load", "loadDataNode", label="Contacts", source="file", fileName="messy_contacts.csv"),
            node("clean", "cleanDataNode", label="Tidy", trimAll=True, removeDuplicates=True, dropMissing=["name"],
                 textCase={"columns": ["email"], "mode": "lower"}, fillMissing=[{"column": "city", "value": "Unknown"}]),
            node("sum", "summariseDataNode", label="By city", groupBy=["city"], aggregations=[{"fn": "count", "column": "*", "as": "people"}]),
        )
        res = preview(h, create_workflow(h, wf))
        self.assertEqual(res["status"], "completed", res)
        by_id = {n["node_id"]: n for n in res["nodes"]}
        self.assertEqual(by_id["load"]["dataset"]["row_count"], 9)
        clean = by_id["clean"]["dataset"]
        # 9 rows - 1 blank name - 2 duplicates (Ben, Farah) = 6 people
        self.assertEqual(clean["row_count"], 6)
        self.assertTrue(all(r["email"] == "[REDACTED]" for r in clean["sample"]))   # PII is masked in previews
        self.assertEqual(by_id["clean"]["sql"].count("WITH"), 1)
        summary = {r["city"]: r["people"] for r in by_id["sum"]["dataset"]["sample"]}
        self.assertEqual(sum(summary.values()), 6)
        self.assertIn("Unknown", summary)                    # blank city was filled
        self.assertIn("GROUP BY", by_id["sum"]["sql"])       # the compiled SQL is shown

        # masked previews hide the values, so verify trimming/lower-casing with SQL on the cleaned data
        check = chain(
            node("load", "loadDataNode", source="file", fileName="messy_contacts.csv"),
            node("clean", "cleanDataNode", trimAll=True, removeDuplicates=True, dropMissing=["name"],
                 textCase={"columns": ["email"], "mode": "lower"}),
            node("q", "sqlNode", query="SELECT count(*) AS bad FROM input WHERE email <> lower(trim(email)) OR name <> trim(name)"),
        )
        res2 = preview(h, create_workflow(h, check))
        self.assertEqual(res2["nodes"][-1]["dataset"]["sample"], [{"bad": 0}])

    def test_sales_totals_match_plain_python(self):
        _, h = setup_user()
        rows = _csv_rows("sales.csv")
        expected = defaultdict(int)
        for r in rows:
            expected[r["region"]] += int(r["revenue"])
        wf = chain(
            node("load", "loadDataNode", source="file", fileName="sales.csv"),
            node("sum", "summariseDataNode", groupBy=["region"], aggregations=[{"fn": "sum", "column": "revenue", "as": "total"}]),
        )
        res = preview(h, create_workflow(h, wf))
        got = {r["region"]: r["total"] for r in res["nodes"][1]["dataset"]["sample"]}
        self.assertEqual(got, dict(expected))

    def test_combine_orders_with_customers(self):
        _, h = setup_user()
        orders = _csv_rows("orders.csv")
        wf = {
            "nodes": [node("o", "loadDataNode", label="Orders", source="file", fileName="orders.csv"),
                      node("c", "loadDataNode", label="Customers", source="file", fileName="customers.csv"),
                      node("j", "combineDataNode", joinType="inner", keys=[{"left": "customer_id", "right": "customer_id"}])],
            "edges": [{"id": "e1", "source": "o", "target": "j"}, {"id": "e2", "source": "c", "target": "j"}],
        }
        res = preview(h, create_workflow(h, wf))
        joined = res["nodes"][-1]["dataset"]
        self.assertEqual(res["status"], "completed", res)
        self.assertEqual(joined["row_count"], len(orders))            # every order has a customer
        names = [c["name"] for c in joined["columns"]]
        self.assertEqual(names.count("customer_id"), 1)
        self.assertIn("tier", names)

    def test_sql_node_with_friendly_table_names(self):
        _, h = setup_user()
        wf = {
            "nodes": [node("o", "loadDataNode", label="Orders", source="file", fileName="orders.csv"),
                      node("c", "loadDataNode", label="Customers", source="file", fileName="customers.csv"),
                      node("q", "sqlNode", query=(
                          "SELECT c.tier, round(sum(o.quantity * o.unit_price), 2) AS revenue "
                          "FROM orders o JOIN customers c USING (customer_id) "
                          "WHERE o.status <> 'cancelled' GROUP BY c.tier ORDER BY revenue DESC"))],
            "edges": [{"id": "e1", "source": "o", "target": "q"}, {"id": "e2", "source": "c", "target": "q"}],
        }
        res = preview(h, create_workflow(h, wf))
        self.assertEqual(res["status"], "completed", res)
        tier = {r["customer_id"]: r["tier"] for r in _csv_rows("customers.csv")}
        exp = defaultdict(float)
        for r in _csv_rows("orders.csv"):
            if r["status"] != "cancelled":
                exp[tier[r["customer_id"]]] += int(r["quantity"]) * int(r["unit_price"])
        got = {r["tier"]: r["revenue"] for r in res["nodes"][-1]["dataset"]["sample"]}
        self.assertEqual({k: round(v, 2) for k, v in exp.items()}, got)
        self.assertEqual(len(res["nodes"][-1]["dataset"]["lineage"]), 2)        # both inputs are recorded

    def test_pii_columns_are_masked_in_previews(self):
        _, h = setup_user()
        wf = chain(node("l", "loadDataNode", source="file", fileName="customers.csv"))
        res = preview(h, create_workflow(h, wf))
        cols = {c["name"]: c for c in res["nodes"][0]["dataset"]["columns"]}
        self.assertIn("pii", cols["email"]["tags"])
        self.assertTrue(all(r["email"] == "[REDACTED]" for r in res["nodes"][0]["dataset"]["sample"]))
        self.assertNotIn("example.com", str(res))

    def test_friendly_errors_with_failed_node_named(self):
        _, h = setup_user()
        for bad, expect in [
            (node("l", "loadDataNode", source="file", fileName="missing.csv"), "not found"),
            (node("l", "loadDataNode", source="nothing"), "Choose where"),
        ]:
            res = preview(h, create_workflow(h, chain(bad)))
            self.assertEqual(res["status"], "failed")
            self.assertIn(expect, res["error"])
        res = preview(h, create_workflow(h, chain(
            node("l", "loadDataNode", source="file", fileName="sales.csv"),
            node("s", "summariseDataNode", aggregations=[{"fn": "sum", "column": "region"}]))))
        self.assertEqual(res["failed_node_id"], "s")
        self.assertIn("not numbers", res["error"])
        res = preview(h, create_workflow(h, chain(node("q", "sqlNode", query="SELECT 1"))))
        self.assertIn("connect a data node", res["error"])
        res = preview(h, create_workflow(h, chain(
            node("l", "loadDataNode", source="file", fileName="sales.csv"), node("q", "sqlNode", query="SELECT nope FROM input"))))
        self.assertIn("nope", res["error"])

    def test_preview_samples_rows_and_skips_paid_nodes(self):
        _, h = setup_user()
        big = "n\n" + "\n".join(str(i) for i in range(3000)) + "\n"
        r = client.post(f"{API}/data/files", files={"file": ("big.csv", big.encode(), "text/csv")}, headers=h)
        self.assertEqual(r.status_code, 201, r.text)
        wf = chain(node("l", "loadDataNode", source="file", fileName="big.csv"),
                   node("ai", "aiNode", aiTask="summarize"),
                   node("http", "httpNode", url="http://example.com"))
        res = preview(h, create_workflow(h, wf))
        self.assertEqual(res["nodes"][0]["dataset"]["row_count"], settings.DRY_RUN_ROWS)
        self.assertEqual([n["status"] for n in res["nodes"][1:]], ["skipped", "skipped"])

    def test_preview_is_free_but_real_runs_bill_per_node(self):
        email, h = setup_user(credits=20)
        wf = chain(node("l", "loadDataNode", source="file", fileName="sales.csv"),
                   node("c", "cleanDataNode", trimAll=True),
                   node("q", "sqlNode", query="SELECT region, sum(revenue) AS r FROM input GROUP BY region"))
        wid = create_workflow(h, wf)
        preview(h, wid)
        self.assertEqual(credits_used(email), 0)
        r = client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
        self.assertEqual(r.json()["status"], "completed", r.text)
        self.assertEqual(credits_used(email), 1 + 1 + 2)             # load + clean + sql, small data: no scan surcharge
        usage = client.get(f"{API}/admin/credit-usage/raw", headers=h)
        self.assertIn(usage.status_code, (200, 403))

    def test_real_run_persists_datasets_that_can_be_previewed_and_downloaded(self):
        _, h = setup_user()
        wf = chain(node("l", "loadDataNode", label="Sales", source="file", fileName="sales.csv"),
                   node("s", "summariseDataNode", label="Totals", groupBy=["region"], aggregations=[{"fn": "sum", "column": "revenue", "as": "total"}]))
        wid = create_workflow(h, wf)
        ex = client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h).json()
        self.assertEqual(ex["status"], "completed")
        sets = client.get(f"{API}/data/datasets", headers=h).json()
        totals = next(d for d in sets if d["name"] == "Totals")
        self.assertEqual(totals["row_count"], 4)
        self.assertIn("GROUP BY", totals["sql"])
        self.assertIsNotNone(totals["expires_at"])
        p = client.get(f"{API}/data/datasets/{totals['id']}/preview", headers=h).json()
        self.assertEqual(len(p["sample"]), 4)
        csvr = client.get(f"{API}/data/datasets/{totals['id']}/download?format=csv", headers=h)
        self.assertEqual(csvr.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(csvr.text)))
        self.assertEqual({r["region"] for r in rows}, {"North", "South", "East", "West"})
        pq = client.get(f"{API}/data/datasets/{totals['id']}/download?format=parquet", headers=h)
        self.assertTrue(pq.content.startswith(b"PAR1"))
        self.assertEqual(client.delete(f"{API}/data/datasets/{totals['id']}", headers=h).status_code, 204)
        self.assertEqual(client.get(f"{API}/data/datasets/{totals['id']}/preview", headers=h).status_code, 404)

    def test_background_run_with_data_nodes(self):
        import asyncio
        from app.jobs.runtime import build_worker
        _, h = setup_user()
        wf = chain(node("l", "loadDataNode", source="file", fileName="orders.csv"),
                   node("s", "summariseDataNode", groupBy=["status"], aggregations=[{"fn": "count", "column": "*", "as": "n"}]))
        wid = create_workflow(h, wf)
        eid = client.post(f"{API}/runs", json={"workflow_id": wid}, headers=h).json()["execution_id"]
        asyncio.run(build_worker().run_once())
        run = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual(run["status"], "completed", run)
        counts = {r["status"]: r["n"] for r in run["execution_trace"][-1]["result"]["dataset"]["sample"]}
        self.assertEqual(sum(counts.values()), len(_csv_rows("orders.csv")))


class IsolationAndLimitsTests(TestCase):
    def test_users_cannot_load_each_others_files(self):
        _, h1 = setup_user()
        h2 = signup(credits=10)[2]
        fid = client.get(f"{API}/data/files", headers=h1).json()[0]["id"]
        # by id and by name: user 2 has no such file, so the node must fail rather than read user 1's data
        wid = create_workflow(h2, chain(node("l", "loadDataNode", source="file", fileId=fid)))
        res = preview(h2, wid)
        self.assertEqual(res["status"], "failed")
        self.assertIn("not found", res["error"])
        res = preview(h2, create_workflow(h2, chain(node("l", "loadDataNode", source="file", fileName="orders.csv"))))
        self.assertEqual(res["status"], "failed")
        self.assertEqual(client.get(f"{API}/data/files/{fid}/preview", headers=h2).status_code, 404)
        self.assertEqual(client.delete(f"{API}/data/files/{fid}", headers=h2).status_code, 404)

    def test_user_cannot_reference_another_users_dataset(self):
        _, h1 = setup_user()
        wid = create_workflow(h1, chain(node("l", "loadDataNode", source="file", fileName="sales.csv")))
        client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid}, headers=h1)
        ds_id = client.get(f"{API}/data/datasets", headers=h1).json()[0]["id"]
        _, h2 = setup_user()
        self.assertEqual(client.get(f"{API}/data/datasets/{ds_id}/preview", headers=h2).status_code, 404)
        self.assertEqual(client.get(f"{API}/data/datasets/{ds_id}/download", headers=h2).status_code, 404)
        self.assertEqual(client.delete(f"{API}/data/datasets/{ds_id}", headers=h2).status_code, 404)

    def test_upload_validation(self):
        _, _, h = signup()
        up = lambda name, data: client.post(f"{API}/data/files", files={"file": (name, data, "application/octet-stream")}, headers=h)
        self.assertEqual(up("x.exe", b"MZ").status_code, 422)
        self.assertEqual(up("empty.csv", b"").status_code, 422)
        self.assertEqual(up("bad.parquet", b"not parquet").status_code, 422)
        self.assertEqual(up("bad.json", b"{{{{").status_code, 422)
        ok = up("../../etc/evil name!.csv", b"a,b\n1,2\n")
        self.assertEqual(ok.status_code, 201, ok.text)
        self.assertNotIn("/", ok.json()["name"])
        self.assertEqual((ok.json()["row_count"], [c["name"] for c in ok.json()["columns"]]), (1, ["a", "b"]))
        from app.storage.local import storage
        self.assertTrue(os.path.realpath(storage.path_for(f"tenants/x/{ok.json()['id']}.csv")).startswith(str(storage.root)))

    def test_upload_size_and_storage_quota(self):
        from unittest.mock import patch
        _, _, h = signup()
        with patch.object(settings, "MAX_UPLOAD_MB", 1):
            r = client.post(f"{API}/data/files", files={"file": ("big.csv", b"a\n" + b"1\n" * 700_000, "text/csv")}, headers=h)
            self.assertEqual(r.status_code, 413)
        with patch.object(settings, "MAX_STORAGE_MB_PER_USER", 0):
            r = client.post(f"{API}/data/files", files={"file": ("a.csv", b"a\n1\n", "text/csv")}, headers=h)
            self.assertEqual(r.status_code, 413)
        u = client.get(f"{API}/data/usage", headers=h).json()
        self.assertEqual((u["files"], u["used_bytes"]), (0, 0))              # nothing left behind by failed uploads

    def test_examples_are_idempotent_and_deletable(self):
        _, _, h = signup()
        first = client.post(f"{API}/data/examples", headers=h).json()
        self.assertEqual({f["name"] for f in first}, {"customers.csv", "orders.csv", "orders_dirty.csv", "sales.csv", "messy_contacts.csv",
                                                          "churn_customers.csv", "churn_reference.csv", "churn_this_week.csv"})
        self.assertEqual(client.post(f"{API}/data/examples", headers=h).json(), [])
        fid = first[0]["id"]
        self.assertEqual(client.delete(f"{API}/data/files/{fid}", headers=h).status_code, 204)
        p = client.get(f"{API}/data/files/{first[1]['id']}/preview", headers=h).json()
        self.assertTrue(p["sample"])

    def test_inactive_and_anonymous_are_rejected(self):
        _, _, h = signup(activate=False)
        self.assertEqual(client.get(f"{API}/data/files", headers=h).status_code, 403)
        self.assertEqual(client.get(f"{API}/data/files").status_code, 401)

    def test_expired_datasets_are_purged_with_their_files(self):
        from app.services.dataset_service import purge_expired_datasets
        from app.storage.local import storage
        _, h = setup_user()
        wid = create_workflow(h, chain(node("l", "loadDataNode", source="file", fileName="sales.csv")))
        client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid}, headers=h)
        sid = client.get(f"{API}/data/datasets", headers=h).json()[0]["id"]
        db = SessionLocal()
        d = db.query(Dataset).filter(Dataset.id == UUID(sid)).first()
        path = storage.path_for(d.storage_key)
        self.assertTrue(os.path.exists(path))
        d.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit(); db.close()
        self.assertGreaterEqual(purge_expired_datasets(), 1)
        self.assertFalse(os.path.exists(path))

    def test_data_nodes_need_a_user(self):
        import asyncio
        from app.services.workflow_executor import WorkflowExecutor
        out = asyncio.run(WorkflowExecutor().execute_workflow(chain(node("l", "loadDataNode", source="file", fileName="x.csv"))))
        self.assertEqual(out["status"], "failed")
        self.assertIn("signed-in user", out["error"])


@skipUnless(IS_PG, "needs PostgreSQL (set TEST_DATABASE_URL)")
class LoadFromPostgresTests(TestCase):
    @classmethod
    def setUpClass(cls):
        with engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS fm_load_test"))
            c.execute(text("CREATE TABLE fm_load_test (id int, name text, price numeric(10,2), ok boolean, born date, seen timestamp, note text)"))
            c.execute(text("INSERT INTO fm_load_test SELECT g, 'n'||g, g*1.5, g%2=0, date '2020-01-01'+g, timestamp '2020-01-01 00:00'+g*interval '1 hour', NULL FROM generate_series(1,500) g"))

    def _conn(self, h):
        from urllib.parse import urlparse
        u = urlparse(os.environ["TEST_DATABASE_URL"])
        cfg = {"host": u.hostname, "port": u.port, "database": u.path.lstrip("/"), "user": u.username, "sslmode": "disable"}
        cid = client.post(f"{API}/connections", json={"name": f"pg{time.time_ns()}", "type": "postgres", "config": cfg}, headers=h).json()["id"]
        from tests.helpers import admin_headers
        client.patch(f"{API}/connections/{cid}", json={"host_allowlist": ["127.0.0.1"]}, headers=admin_headers())
        return cid

    def test_load_table_then_summarise(self):
        _, _, h = signup(credits=20)
        cid = self._conn(h)
        wf = chain(node("l", "loadDataNode", source="connection", connectionId=cid, table="fm_load_test", maxRows=400),
                   node("s", "summariseDataNode", groupBy=["ok"], aggregations=[
                       {"fn": "count", "column": "*", "as": "n"}, {"fn": "sum", "column": "price", "as": "total"}]))
        res = preview(h, create_workflow(h, wf))
        self.assertEqual(res["status"], "completed", res)
        loaded = res["nodes"][0]["dataset"]
        self.assertEqual(loaded["row_count"], settings.DRY_RUN_ROWS if 400 > settings.DRY_RUN_ROWS else 400)
        types = {c["name"]: c["type"] for c in loaded["columns"]}
        self.assertEqual((types["id"], types["ok"], types["born"]), ("BIGINT", "BOOLEAN", "DATE"))
        self.assertTrue(types["price"].startswith("DOUBLE"))
        got = {r["ok"]: r["n"] for r in res["nodes"][1]["dataset"]["sample"]}
        self.assertEqual(sum(got.values()), 400)

    def test_column_selection_errors_and_private_host_block(self):
        _, _, h = signup(credits=20)
        cid = self._conn(h)
        res = preview(h, create_workflow(h, chain(node("l", "loadDataNode", source="connection", connectionId=cid,
                                                         table="fm_load_test", columns=["id", "price"]))))
        self.assertEqual([c["name"] for c in res["nodes"][0]["dataset"]["columns"]], ["id", "price"])
        for kw, expect in ((dict(table="nope"), "not found"), (dict(table="fm_load_test", columns=["zzz"]), "does not exist"),
                           (dict(), "Choose a table")):
            res = preview(h, create_workflow(h, chain(node("l", "loadDataNode", source="connection", connectionId=cid, **kw))))
            self.assertIn(expect, res["error"])
        # a connection without the admin allow-list cannot reach 127.0.0.1
        from urllib.parse import urlparse
        u = urlparse(os.environ["TEST_DATABASE_URL"])
        bare = client.post(f"{API}/connections", json={"name": "bare", "type": "postgres", "config": {
            "host": u.hostname, "port": u.port, "database": u.path.lstrip("/"), "user": u.username, "sslmode": "disable"}}, headers=h).json()["id"]
        res = preview(h, create_workflow(h, chain(node("l", "loadDataNode", source="connection", connectionId=bare, table="fm_load_test"))))
        self.assertIn("allow-list", res["error"])

    def test_another_users_connection_cannot_be_used(self):
        _, _, h1 = signup(credits=20)
        cid = self._conn(h1)
        _, _, h2 = signup(credits=20)
        res = preview(h2, create_workflow(h2, chain(node("l", "loadDataNode", source="connection", connectionId=cid, table="fm_load_test"))))
        self.assertIn("Connection not found", res["error"])
