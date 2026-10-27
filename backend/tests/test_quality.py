import asyncio
import csv
import os
import uuid
from collections import Counter
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.api.data import EXAMPLES_DIR
from app.core.config import settings
from app.core.database import SessionLocal
from app.data.dataset import Column, build_dataset
from app.data.pii import detect_kind
from app.jobs.runtime import build_worker
from app.models.lineage import LineageEvent
from tests.helpers import client, create_workflow, credits_used, reset_jobs, signup
from tests.test_data_nodes import chain, node, preview, setup_user

API = "/api/v1"


def dirty_rows():
    with open(os.path.join(EXAMPLES_DIR, "orders_dirty.csv"), newline="") as f:
        return list(csv.DictReader(f))


def gate(rules, on_fail="stop", **kw):
    return node("gate", "qualityGateNode", label="Order checks", rules=rules, onFail=on_fail, **kw)


def load(file="orders_dirty.csv"):
    return node("load", "loadDataNode", label="Dirty orders", source="file", fileName=file)


def run_gate(h, rules, on_fail="stop", extra=()):
    wf = chain(load(), gate(rules, on_fail), *extra)
    return preview(h, create_workflow(h, wf))


def rule_by_type(res, t, idx=0):
    q = [n for n in res["nodes"] if n["node_id"] == "gate"][0]["quality"]
    return [r for r in q["rules"] if r["type"] == t][idx]


# ── PII from values ─────────────────────────────────────────────────────────────

class PiiDetectionTests(TestCase):
    def test_detects_kinds_from_values(self):
        cases = {
            "email": ["ann@example.com", "bob@work.org"],
            "phone": ["+91 98765 43210", "+44 20 7946 0958"],
            "pan": ["ABCDE1234F", "XYZAB9876Q"],
            "card": ["4111 1111 1111 1111", "5500-0000-0000-0004"],
            "iban": ["GB82 WEST 1234 5698 7654 32", "DE89370400440532013000"],
            "ipv4": ["192.168.0.1", "10.0.0.5"],
            "ssn": ["123-45-6789", "987-65-4321"],
            "aadhaar": ["234567890124", "2345 6789 0124"],
        }
        for kind, vals in cases.items():
            self.assertEqual(detect_kind(vals), kind, kind)

    def test_ordinary_values_are_not_flagged(self):
        for vals in (["1000", "1001", "1002"], ["Notebook", "Backpack"], ["2026-03-01", "2026-03-02"],
                     ["12", "7", "300"], ["abc", "def"], [None, "", None], ["a@b.com"], ["1234567890123456", "1111222233334444"]):
            self.assertIsNone(detect_kind(vals), vals)

    def test_mostly_matching_threshold(self):
        self.assertEqual(detect_kind(["a@x.com"] * 9 + ["n/a"]), "email")          # 90% match
        self.assertIsNone(detect_kind(["a@x.com", "n/a", "n/a", "n/a"]))            # 25% match

    def test_checksums_reject_look_alikes(self):
        self.assertIsNone(detect_kind(["4111 1111 1111 1112", "4111 1111 1111 1113"]))      # bad Luhn
        self.assertNotEqual(detect_kind(["234567890123", "234567890125"]), "aadhaar")       # bad Verhoeff

    def test_build_dataset_tags_and_masks_by_value_even_with_innocent_names(self):
        cols = [Column(name="contact", type="VARCHAR"), Column(name="ref", type="VARCHAR"), Column(name="qty", type="BIGINT")]
        rows = [{"contact": "ann@example.com", "ref": "A1", "qty": 1}, {"contact": "bob@example.com", "ref": "B2", "qty": 2}]
        ds = build_dataset(cols, rows)
        tags = {c.name: c.tags for c in ds.columns}
        self.assertEqual(tags["contact"], ["pii", "pii:email"])
        self.assertEqual(tags["ref"], [])
        self.assertEqual([r["contact"] for r in ds.sample], ["[REDACTED]", "[REDACTED]"])
        self.assertEqual([r["ref"] for r in ds.sample], ["A1", "B2"])


# ── quality rules end to end ────────────────────────────────────────────────────

class QualityRuleTests(TestCase):
    def setUp(self):
        reset_jobs()

    def test_each_rule_counts_match_plain_python(self):
        _, h = setup_user()
        rows = dirty_rows()
        rules = [
            {"type": "not_null", "column": "customer_id"},
            {"type": "unique", "columns": ["order_id"]},
            {"type": "range", "column": "quantity", "min": 1, "max": 100},
            {"type": "allowed_values", "column": "status", "values": ["delivered", "shipped", "cancelled"]},
            {"type": "regex", "column": "order_date", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            {"type": "max_null_pct", "column": "unit_price", "max": 1},
            {"type": "min_rows", "value": 10},
            {"type": "max_rows", "value": 10},
            {"type": "expression", "expression": "quantity * unit_price > 0", "label": "Order value is positive"},
        ]
        res = run_gate(h, rules, "warn")
        self.assertEqual(res["status"], "completed", res)
        q = res["nodes"][1]["quality"]
        got = {r["id"]: r for r in q["rules"]}
        self.assertEqual(q["total_rows"], len(rows))

        self.assertEqual(got["r1"]["failed"], sum(1 for r in rows if not r["customer_id"].strip()))
        dup = [k for k, n in Counter(r["order_id"] for r in rows).items() if n > 1]
        self.assertEqual((got["r2"]["failed"], got["r2"]["unit"]), (len(dup), "duplicated values"))
        self.assertEqual(got["r3"]["failed"], sum(1 for r in rows if not (1 <= int(r["quantity"]) <= 100)))
        self.assertEqual(got["r4"]["failed"], sum(1 for r in rows if r["status"] not in ("delivered", "shipped", "cancelled")))
        self.assertEqual(got["r5"]["failed"], sum(1 for r in rows if r["order_date"] == "yesterday"))
        self.assertEqual(got["r6"]["status"], "fail")
        self.assertIn("% empty", got["r6"]["message"])
        self.assertEqual((got["r7"]["status"], got["r8"]["status"]), ("pass", "fail"))
        bad_value = sum(1 for r in rows if not r["unit_price"] or int(r["quantity"]) * int(r["unit_price"]) <= 0)
        self.assertEqual(got["r9"]["failed"], bad_value)
        self.assertEqual(q["failed_errors"], 8)
        self.assertFalse(q["passed"])
        # examples exist for failed row rules, capped at 5
        self.assertTrue(0 < len(got["r3"]["examples"]) <= 5)
        self.assertEqual(got["r1"]["examples"][0]["customer_id"], None)

    def test_a_clean_table_passes(self):
        _, h = setup_user()
        res = preview(h, create_workflow(h, chain(
            node("load", "loadDataNode", source="file", fileName="orders.csv"),
            gate([
                {"type": "not_null", "column": "order_id"}, {"type": "unique", "columns": ["order_id"]},
                {"type": "range", "column": "quantity", "min": 1, "max": 4},
                {"type": "allowed_values", "column": "status", "values": "delivered, shipped, cancelled"},
            ]),
        )))
        q = res["nodes"][1]["quality"]
        self.assertEqual(res["status"], "completed", res)
        self.assertTrue(q["passed"])
        self.assertEqual((q["checks"], q["failed_errors"], q["failed_warnings"]), (4, 0, 0))

    def test_stop_halts_the_run_with_a_readable_reason(self):
        _, h = setup_user()
        res = run_gate(h, [{"type": "unique", "columns": ["order_id"]}, {"type": "range", "column": "quantity", "min": 1, "max": 100}],
                       "stop", extra=(node("after", "sqlNode", query="SELECT count(*) AS n FROM input"),))
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["failed_node_id"], "gate")
        self.assertIn("2 of 2 quality checks did not pass", res["error"])
        self.assertIn("order_id must be unique", res["error"])
        self.assertEqual([n["node_id"] for n in res["nodes"]], ["load", "gate"])          # nothing ran after the gate
        gate_step = res["nodes"][1]
        self.assertEqual(gate_step["status"], "error")
        self.assertFalse(gate_step["quality"]["passed"])

    def test_warn_mode_and_warn_severity_let_the_run_continue(self):
        _, h = setup_user()
        after = node("after", "sqlNode", query="SELECT count(*) AS n FROM input")
        res = run_gate(h, [{"type": "unique", "columns": ["order_id"]}], "warn", extra=(after,))
        self.assertEqual(res["status"], "completed", res)
        self.assertEqual(res["nodes"][-1]["dataset"]["sample"], [{"n": len(dirty_rows())}])      # the table passed through intact
        res = run_gate(h, [{"type": "unique", "columns": ["order_id"], "severity": "warn"}], "stop", extra=(after,))
        self.assertEqual(res["status"], "completed")
        q = res["nodes"][1]["quality"]
        self.assertTrue(q["passed"])
        self.assertEqual((q["failed_errors"], q["failed_warnings"]), (0, 1))

    def test_schema_contract(self):
        _, h = setup_user()
        res = run_gate(h, [{"type": "schema", "expected": [
            {"name": "order_id", "type": "integer"}, {"name": "status", "type": "text"},
            {"name": "unit_price", "type": "number"}, {"name": "order_date", "type": "date"},
            {"name": "ghost", "type": ""}], "allowExtra": False}], "warn")
        r = rule_by_type(res, "schema")
        self.assertEqual(r["status"], "fail")
        self.assertIn("missing column 'ghost'", r["message"])
        self.assertIn("'order_date' is VARCHAR, expected date", r["message"])          # 'yesterday' made it text
        self.assertIn("unexpected columns", r["message"])
        self.assertNotIn("'order_id'", r["message"])                                      # integer column matches its contract
        ok = run_gate(h, [{"type": "schema", "expected": [{"name": "order_id", "type": "integer"}, {"name": "unit_price", "type": "number"}]}])
        self.assertEqual(ok["status"], "completed")

    def test_unique_on_several_columns_and_nulls_ignored(self):
        _, h = setup_user()
        res = run_gate(h, [{"type": "unique", "columns": ["customer_id", "order_date"]}], "warn")
        r = rule_by_type(res, "unique")
        rows = dirty_rows()
        keys = Counter((x["customer_id"], x["order_date"]) for x in rows if x["customer_id"].strip())
        self.assertEqual(r["failed"], sum(1 for n in keys.values() if n > 1))
        self.assertIn("times_seen", r["examples"][0])

    def test_dates_and_numbers_in_ranges(self):
        _, h = setup_user()
        res = run_gate(h, [{"type": "range", "column": "unit_price", "min": 100, "max": 1000}], "warn")
        rows = [r for r in dirty_rows() if r["unit_price"]]
        self.assertEqual(rule_by_type(res, "range")["failed"], sum(1 for r in rows if not 100 <= int(r["unit_price"]) <= 1000))
        res = preview(h, create_workflow(h, chain(
            node("load", "loadDataNode", source="file", fileName="orders.csv"),
            node("q", "sqlNode", query="SELECT CAST(order_date AS DATE) AS d FROM input"),
            node("gate", "qualityGateNode", rules=[{"type": "range", "column": "d", "min": "2026-03-05", "max": "2026-03-31"}], onFail="warn"))))
        d = [r for r in _csv("orders.csv") if r["order_date"] < "2026-03-05"]
        self.assertEqual(res["nodes"][2]["quality"]["rules"][0]["failed"], len(d))

    def test_configuration_errors_are_clear(self):
        _, h = setup_user()
        cases = [
            ([], "Add at least one check"),
            ([{"type": "not_null", "column": "nope"}], "column 'nope' was not found"),
            ([{"type": "bogus"}], "unknown type"),
            ([{"type": "range", "column": "status", "min": 1}], "needs a number or date"),
            ([{"type": "range", "column": "quantity"}], "give a minimum and/or a maximum"),
            ([{"type": "range", "column": "quantity", "min": "abc"}], "must be a number"),
            ([{"type": "regex", "column": "status", "pattern": "("}], "invalid pattern"),
            ([{"type": "allowed_values", "column": "status", "values": []}], "at least one allowed value"),
            ([{"type": "max_null_pct", "column": "status", "max": 120}], "between 0 and 100"),
            ([{"type": "expression", "expression": "a > 1; DROP TABLE x"}], "one SQL expression"),
            ([{"type": "not_null", "column": "status", "severity": "fatal"}], "severity"),
            ([{"type": "not_null", "column": "status", "id": "x"}, {"type": "unique", "column": "order_id", "id": "x"}], "ids must be unique"),
        ]
        for rules, expect in cases:
            res = run_gate(h, rules)
            self.assertEqual(res["status"], "failed", rules)
            self.assertIn(expect, res["error"], rules)
        res = run_gate(h, [{"type": "not_null", "column": "status"}], "explode")
        self.assertIn("must be 'stop' or 'warn'", res["error"])

    def test_values_cannot_inject_sql_or_read_files(self):
        _, h = setup_user()
        evil = "x'); DROP TABLE input; --"
        res = run_gate(h, [{"type": "allowed_values", "column": "status", "values": [evil, "delivered"]}], "warn")
        self.assertEqual(res["status"], "completed", res)
        self.assertGreater(rule_by_type(res, "allowed_values")["failed"], 0)
        res = run_gate(h, [{"type": "expression", "expression": "(SELECT count(*) FROM read_csv('/etc/passwd')) > 0"}], "warn")
        self.assertEqual(res["status"], "failed")
        self.assertIn("file system operations are disabled", res["error"])
        res = run_gate(h, [{"type": "regex", "column": "status", "pattern": "x'; SELECT 1; --"}], "warn")
        self.assertEqual(res["status"], "completed")
        res = run_gate(h, [{"type": "regex", "column": "status", "pattern": "'); SELECT 1; --"}], "warn")
        self.assertIn("invalid pattern", res["error"])             # unbalanced regex is rejected before any SQL is built

    def test_examples_of_failures_are_masked(self):
        _, h = setup_user()
        wf = chain(node("l", "loadDataNode", source="file", fileName="messy_contacts.csv"),
                   node("gate", "qualityGateNode", rules=[{"type": "not_null", "column": "name"}], onFail="warn"))
        res = preview(h, create_workflow(h, wf))
        ex = res["nodes"][1]["quality"]["rules"][0]["examples"]
        self.assertEqual(ex[0]["email"], "[REDACTED]")
        self.assertNotIn("example.com", str(res))

    def test_pii_detected_by_value_hides_data_in_previews(self):
        _, h = setup_user()
        r = client.post(f"{API}/data/files", files={"file": ("contacts_x.csv", b"id,contact\n1,ann@example.com\n2,bob@example.com\n3,cy@example.com\n", "text/csv")}, headers=h)
        self.assertEqual(r.status_code, 201)
        p = client.get(f"{API}/data/files/{r.json()['id']}/preview", headers=h).json()
        col = [c for c in p["columns"] if c["name"] == "contact"][0]
        self.assertEqual(col["tags"], ["pii", "pii:email"])
        self.assertTrue(all(row["contact"] == "[REDACTED]" for row in p["sample"]))


def _csv(name):
    with open(os.path.join(EXAMPLES_DIR, name), newline="") as f:
        return list(csv.DictReader(f))


# ── profiling and suggestions ───────────────────────────────────────────────────

class ProfileTests(TestCase):
    def test_profile_and_suggestions(self):
        _, h = setup_user()
        files = {f["name"]: f for f in client.get(f"{API}/data/files", headers=h).json()}
        r = client.get(f"{API}/data/files/{files['orders.csv']['id']}/profile", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()
        rows = _csv("orders.csv")
        self.assertEqual(p["total_rows"], len(rows))
        cols = {c["name"]: c for c in p["columns"]}
        self.assertEqual(cols["quantity"]["min"], "1")
        self.assertEqual(cols["quantity"]["max"], str(max(int(x["quantity"]) for x in rows)))
        self.assertEqual(cols["status"]["distinct"], len({x["status"] for x in rows}))
        self.assertEqual(cols["order_id"]["nulls"], 0)
        kinds = {(s["type"], s.get("column") or tuple(s.get("columns", []))) for s in p["suggested_rules"]}
        self.assertIn(("unique", ("order_id",)), kinds)
        self.assertIn(("not_null", "order_id"), kinds)
        self.assertIn(("allowed_values", "status"), kinds)
        self.assertIn(("min_rows", ()), kinds)
        allowed = [s for s in p["suggested_rules"] if s["type"] == "allowed_values" and s["column"] == "status"][0]
        self.assertEqual(set(allowed["values"]), {x["status"] for x in rows})
        self.assertTrue(all(s.get("reason") for s in p["suggested_rules"]))

    def test_suggested_checks_pass_on_the_data_they_came_from(self):
        _, h = setup_user()
        files = {f["name"]: f for f in client.get(f"{API}/data/files", headers=h).json()}
        p = client.get(f"{API}/data/files/{files['orders.csv']['id']}/profile", headers=h).json()
        rules = [{k: v for k, v in s.items() if k != "reason"} for s in p["suggested_rules"]]
        res = preview(h, create_workflow(h, chain(node("l", "loadDataNode", source="file", fileName="orders.csv"),
                                                  node("gate", "qualityGateNode", rules=rules, onFail="stop"))))
        self.assertEqual(res["status"], "completed", res)
        self.assertTrue(res["nodes"][1]["quality"]["passed"])

    def test_suggestions_catch_the_dirty_file(self):
        _, h = setup_user()
        files = {f["name"]: f for f in client.get(f"{API}/data/files", headers=h).json()}
        p = client.get(f"{API}/data/files/{files['orders_dirty.csv']['id']}/profile", headers=h).json()
        cols = {c["name"]: c for c in p["columns"]}
        self.assertGreater(cols["customer_id"]["nulls"], 0)
        self.assertNotIn("unique", {s["type"] for s in p["suggested_rules"] if s.get("columns") == ["order_id"]})   # has duplicates

    def test_pii_columns_never_expose_values(self):
        _, h = setup_user()
        files = {f["name"]: f for f in client.get(f"{API}/data/files", headers=h).json()}
        p = client.get(f"{API}/data/files/{files['customers.csv']['id']}/profile", headers=h).json()
        email = [c for c in p["columns"] if c["name"] == "email"][0]
        self.assertTrue(email["pii"])
        self.assertEqual((email["min"], email["max"]), (None, None))
        self.assertNotIn("example.com", str(p))

    def test_profile_of_a_pipeline_dataset_and_isolation(self):
        _, h = setup_user()
        res = preview(h, create_workflow(h, chain(node("l", "loadDataNode", source="file", fileName="sales.csv"))))
        dsid = res["nodes"][0]["dataset"]["id"]
        self.assertEqual(client.get(f"{API}/data/datasets/{dsid}/profile", headers=h).status_code, 200)
        h2 = signup()[2]
        self.assertEqual(client.get(f"{API}/data/datasets/{dsid}/profile", headers=h2).status_code, 404)
        fid = client.get(f"{API}/data/files", headers=h).json()[0]["id"]
        self.assertEqual(client.get(f"{API}/data/files/{fid}/profile", headers=h2).status_code, 404)


# ── protecting personal data in Clean ───────────────────────────────────────────

class ProtectTests(TestCase):
    def _run(self, h, protect, salt=None, check="SELECT * FROM input ORDER BY name"):
        wf = chain(node("l", "loadDataNode", source="file", fileName="customers.csv"),
                   node("c", "cleanDataNode", protect=protect, hashSalt=salt or ""),
                   node("q", "sqlNode", query=check))
        return preview(h, create_workflow(h, wf))

    def test_hash_mask_redact_blank(self):
        _, h = setup_user()
        res = self._run(h, [{"column": "email", "method": "hash"}, {"column": "name", "method": "mask"},
                            {"column": "city", "method": "redact"}, {"column": "tier", "method": "blank"}],
                        check="SELECT length(email) AS hl, name, city, tier FROM input ORDER BY name")
        self.assertEqual(res["status"], "completed", res)
        rows = res["nodes"][2]["dataset"]["sample"]
        self.assertTrue(all(r["hl"] == 64 for r in rows))
        names = sorted(r["name"] for r in _csv("customers.csv"))
        self.assertEqual([r["name"] for r in rows], ["*" * (len(n) - 4) + n[-4:] for n in names] and sorted(
            ("*" * (len(n) - 4) + n[-4:]) for n in names))
        self.assertTrue(all(r["city"] == "[REMOVED]" for r in rows))
        self.assertTrue(all(r["tier"] is None for r in rows))

    def test_hash_is_deterministic_and_salt_changes_it(self):
        _, h = setup_user()
        q = "SELECT count(DISTINCT email) AS d, any_value(email) AS e FROM input"
        a = self._run(h, [{"column": "email", "method": "hash"}], check=q)["nodes"][2]["dataset"]["sample"][0]
        b = self._run(h, [{"column": "email", "method": "hash"}], check=q)["nodes"][2]["dataset"]["sample"][0]
        c = self._run(h, [{"column": "email", "method": "hash"}], salt="pepper", check=q)["nodes"][2]["dataset"]["sample"][0]
        self.assertEqual(a["d"], 8)
        self.assertEqual(a["e"], b["e"])
        self.assertNotEqual(a["e"], c["e"])

    def test_errors(self):
        _, h = setup_user()
        res = self._run(h, [{"column": "nope", "method": "hash"}])
        self.assertIn("not found", res["error"])
        res = self._run(h, [{"column": "email", "method": "teleport"}])
        self.assertIn("Unknown way to protect", res["error"])


# ── billing, runs and lineage ───────────────────────────────────────────────────

def _run(h, wid):
    return client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h).json()


def _events(h, eid):
    return client.get(f"{API}/lineage/runs/{eid}/events", headers=h).json()


class RunAndLineageTests(TestCase):
    def setUp(self):
        reset_jobs()

    def test_failed_gate_fails_the_run_and_is_billed(self):
        email, h = setup_user(credits=20)
        wid = create_workflow(h, chain(load(), gate([{"type": "unique", "columns": ["order_id"]}]),
                                       node("after", "sqlNode", query="SELECT 1 AS x FROM input")))
        ex = _run(h, wid)
        self.assertEqual(ex["status"], "failed")
        self.assertIn("order_id must be unique", ex["error_message"])
        self.assertEqual(credits_used(email), 2)                 # load (1) + the gate that stopped it (1); the SQL node never ran
        trace = ex["execution_trace"]
        self.assertEqual([t["node_id"] for t in trace], ["load", "gate"])
        self.assertFalse(trace[1]["result"]["quality"]["passed"])

    def test_passing_run_records_openlineage_events(self):
        _, h = setup_user(credits=20)
        wid = create_workflow(h, chain(
            node("load", "loadDataNode", label="Orders", source="file", fileName="orders.csv"),
            node("gate", "qualityGateNode", label="Checks", rules=[{"type": "unique", "columns": ["order_id"]}, {"type": "not_null", "column": "customer_id"}]),
            node("sum", "summariseDataNode", label="By status", groupBy=["status"], aggregations=[{"column": "*", "fn": "count", "as": "n"}])))
        ex = _run(h, wid)
        self.assertEqual(ex["status"], "completed", ex)
        ev = _events(h, ex["id"])
        types = [(e["job"]["name"], e["eventType"]) for e in ev]
        self.assertEqual(len(ev), 8)                              # workflow START/COMPLETE + 3 nodes x START/COMPLETE
        self.assertEqual(types[0][1], "START")
        self.assertEqual(types[-1][1], "COMPLETE")
        wf_job = ev[0]["job"]["name"]
        self.assertTrue(wf_job.startswith("workflow."))

        for e in ev:                                              # spec-required fields on every event
            self.assertTrue(e["producer"].startswith("https://"))
            self.assertIn("openlineage.io/spec/", e["schemaURL"])
            uuid.UUID(e["run"]["runId"])
            self.assertTrue(e["eventTime"].endswith("Z"))
            self.assertEqual(e["job"]["namespace"], settings.OPENLINEAGE_NAMESPACE)

        node_events = [e for e in ev if e["job"]["name"] != wf_job and e["eventType"] == "COMPLETE"]
        self.assertEqual(len(node_events), 3)
        for e in node_events:
            parent = e["run"]["facets"]["parent"]
            self.assertEqual(parent["run"]["runId"], ex["id"])
            self.assertEqual(parent["job"]["name"], wf_job)

        load_ev = [e for e in node_events if "orders" in e["job"]["name"]][0]
        self.assertEqual(load_ev["inputs"][0]["namespace"], "flowmind://files")
        self.assertEqual(load_ev["inputs"][0]["name"], "orders.csv")
        out = load_ev["outputs"][0]
        self.assertEqual(out["namespace"], "flowmind://datasets")
        self.assertIn("order_id", [f["name"] for f in out["facets"]["schema"]["fields"]])
        self.assertEqual(out["outputFacets"]["outputStatistics"]["rowCount"], len(_csv("orders.csv")))

        gate_ev = [e for e in node_events if "checks" in e["job"]["name"]][0]
        qa = gate_ev["inputs"][0]["inputFacets"]["dataQualityAssertions"]["assertions"]
        self.assertEqual([a["success"] for a in qa], [True, True])
        self.assertEqual(qa[1]["column"], "customer_id")
        metrics = gate_ev["inputs"][0]["inputFacets"]["dataQualityMetrics"]
        self.assertEqual(metrics["rowCount"], len(_csv("orders.csv")))
        self.assertEqual(metrics["columnMetrics"]["customer_id"]["nullCount"], 0)
        self.assertEqual(gate_ev["inputs"][0]["name"], gate_ev["outputs"][0]["name"])      # the table passes through

        sum_ev = [e for e in node_events if "by-status" in e["job"]["name"]][0]
        self.assertIn("GROUP BY", sum_ev["job"]["facets"]["sql"]["query"])
        self.assertEqual(sum_ev["inputs"][0]["namespace"], "flowmind://datasets")           # chained from the previous dataset
        self.assertEqual(ev[-1]["outputs"][0]["name"], sum_ev["outputs"][0]["name"])         # workflow output = terminal node

        wf_start = ev[0]
        self.assertEqual([(i["namespace"], i["name"]) for i in wf_start["inputs"]], [("flowmind://files", "orders.csv")])

        summary = client.get(f"{API}/lineage/runs/{ex['id']}", headers=h).json()
        self.assertEqual([s["label"] for s in summary["steps"]], ["Orders", "Checks", "By status"])
        self.assertEqual(summary["steps"][1]["quality"], {"passed": True, "checks": 2, "failed_errors": 0, "failed_warnings": 0})
        self.assertEqual(summary["steps"][0]["reads"][0]["source"], "file:orders.csv")
        self.assertEqual(summary["events"], 8)

    def test_failed_gate_emits_fail_events_with_assertions(self):
        _, h = setup_user(credits=20)
        wid = create_workflow(h, chain(load(), gate([{"type": "unique", "columns": ["order_id"]}, {"type": "not_null", "column": "status"}])))
        ex = _run(h, wid)
        ev = _events(h, ex["id"])
        self.assertEqual(ev[-1]["eventType"], "FAIL")
        self.assertIn("quality checks did not pass", ev[-1]["run"]["facets"]["errorMessage"]["message"])
        gate_fail = [e for e in ev if e["eventType"] == "FAIL" and e["job"]["name"] != ev[0]["job"]["name"]]
        self.assertEqual(len(gate_fail), 1)
        qa = gate_fail[0]["inputs"][0]["inputFacets"]["dataQualityAssertions"]["assertions"]
        self.assertEqual([a["success"] for a in qa], [False, True])

    def test_runs_without_data_nodes_make_no_events(self):
        _, h = setup_user(credits=20)
        wid = create_workflow(h)
        ex = _run(h, wid)
        self.assertEqual(_events(h, ex["id"]), [])
        self.assertEqual(client.get(f"{API}/lineage/runs/{ex['id']}", headers=h).json()["steps"], [])

    def test_lineage_is_private_to_the_owner_and_cascades_with_retention(self):
        from datetime import datetime, timedelta
        from app.core.maintenance import purge_old_executions
        from app.models.workflow import WorkflowExecution
        _, h = setup_user(credits=20)
        ex = _run(h, create_workflow(h, chain(load(), gate([{"type": "min_rows", "value": 1}]))))
        h2 = signup()[2]
        for path in (f"/lineage/runs/{ex['id']}", f"/lineage/runs/{ex['id']}/events"):
            self.assertEqual(client.get(API + path, headers=h2).status_code, 403)
        self.assertEqual(client.get(f"{API}/lineage/runs/{uuid.uuid4()}", headers=h).status_code, 404)
        self.assertEqual(client.get(f"{API}/lineage/runs/{ex['id']}/events").status_code, 401)

        db = SessionLocal()
        db.query(LineageEvent).filter(LineageEvent.execution_id == uuid.UUID(ex["id"])).update({"event_time": datetime.utcnow() - timedelta(days=90)})
        db.query(WorkflowExecution).filter(WorkflowExecution.id == uuid.UUID(ex["id"])).update({"started_at": datetime.utcnow() - timedelta(days=90)})
        db.commit(); db.close()
        purge_old_executions()
        db = SessionLocal()
        self.assertEqual(db.query(LineageEvent).filter(LineageEvent.execution_id == uuid.UUID(ex["id"])).count(), 0)
        db.close()

    def test_backend_sink_receives_events_and_failures_never_break_runs(self):
        _, h = setup_user(credits=20)
        wid = create_workflow(h, chain(load("orders.csv"), gate([{"type": "min_rows", "value": 1}])))
        fake = MagicMock()
        fake.post.return_value = MagicMock(status_code=200)
        with patch.object(settings, "OPENLINEAGE_URL", "http://marquez.local:5000"), \
             patch.object(settings, "OPENLINEAGE_API_KEY", "secret-key"), \
             patch("app.lineage.openlineage.httpx.Client") as cls:
            cls.return_value.__enter__.return_value = fake
            ex = _run(h, wid)
        self.assertEqual(ex["status"], "completed")
        self.assertEqual(fake.post.call_count, 6)
        url = fake.post.call_args_list[0].args[0]
        self.assertEqual(url, "http://marquez.local:5000/api/v1/lineage")
        self.assertEqual(fake.post.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer secret-key")

        with patch.object(settings, "OPENLINEAGE_URL", "http://down.local"), \
             patch("app.lineage.openlineage.httpx.Client", side_effect=RuntimeError("connection refused")):
            ex2 = _run(h, wid)
        self.assertEqual(ex2["status"], "completed")                    # sink outage must not affect the run
        self.assertEqual(len(_events(h, ex2["id"])), 6)                 # and events are still stored

    def test_background_runs_record_lineage_and_quality_failures(self):
        _, h = setup_user(credits=20)
        wid = create_workflow(h, chain(load(), gate([{"type": "unique", "columns": ["order_id"]}])))
        eid = client.post(f"{API}/runs", json={"workflow_id": wid}, headers=h).json()["execution_id"]
        asyncio.run(build_worker().run_once())
        run = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual(run["status"], "failed")
        self.assertIn("quality checks did not pass", run["error_message"])
        self.assertEqual(run["job"]["state"], "succeeded")                # a data problem is a failed run, not a retried job
        self.assertEqual(_events(h, eid)[-1]["eventType"], "FAIL")

    def test_events_match_the_official_client_library_shapes(self):
        try:
            from openlineage.client.serde import Serde
            from openlineage.client.facet_v2 import schema_dataset, sql_job
        except ImportError:                                            # pragma: no cover
            self.skipTest("openlineage-python not installed")
        want_schema = Serde.to_dict(schema_dataset.SchemaDatasetFacet(fields=[]))["_schemaURL"]
        want_sql = Serde.to_dict(sql_job.SQLJobFacet(query="x"))["_schemaURL"]
        _, h = setup_user(credits=20)
        ex = _run(h, create_workflow(h, chain(load("orders.csv"), node("s", "sqlNode", query="SELECT * FROM input"))))
        ev = _events(h, ex["id"])
        sql_ev = [e for e in ev if e["eventType"] == "COMPLETE" and e["job"].get("facets", {}).get("sql")][0]
        self.assertEqual(sql_ev["job"]["facets"]["sql"]["_schemaURL"], want_sql)
        self.assertEqual(sql_ev["outputs"][0]["facets"]["schema"]["_schemaURL"], want_schema)
        self.assertEqual(sql_ev["outputs"][0]["facets"]["schema"]["_producer"], "https://github.com/sohamvyas73/flowmind-ai")
