"""Phase 5: MLflow + model endpoint connections, Predict, Batch Score, Drift Check, Feedback Capture, Registry Promote.

Always runs against small in-process fake servers (a scoring endpoint and an MLflow registry). If real servers are up,
the same flows also run against them:
    ML_TEST_MLFLOW_URL=http://127.0.0.1:5000  ML_TEST_ENDPOINT_URL=http://127.0.0.1:5001/invocations
(the demo model is made by scripts/mlflow_demo.py).
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase, skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import numpy as np

from app.core.config import settings
from app.ml import drift
from app.ml.endpoints import ScoreError, build_payload, parse_predictions
from app.ml.mlflow_client import MlflowError, check_alias, check_model_name
from app.services.ml_nodes import MlNodeError, check_gates, feedback_metrics
from tests.helpers import admin_headers, client, create_workflow, credits_used, signup
from tests.test_data_nodes import chain, node, setup_user

API = "/api/v1"
FEATS = ["tenure_months", "monthly_spend", "support_tickets"]


# ── fake servers ────────────────────────────────────────────────────────────────

class FakeScorer(ThreadingHTTPServer):
    """Churn rule: support_tickets >= 3 → 1. `mode` switches behaviours for failure tests."""
    mode = "ok"

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _ScorerHandler)
        self.requests = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}/invocations"


class _ScorerHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200 if self.path == "/ping" else 404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({"body": body, "auth": self.headers.get("Authorization")})
        if self.server.mode == "http500":
            return self._send(500, {"error": "model exploded"})
        if "dataframe_records" in body:
            rows = body["dataframe_records"]
        elif "dataframe_split" in body:
            s = body["dataframe_split"]
            rows = [dict(zip(s["columns"], r)) for r in s["data"]]
        else:
            rows = body["records"]
        n = len(rows) - (1 if self.server.mode == "short" else 0)
        if self.server.mode == "proba":
            return self._send(200, {"predictions": [[0.2, 0.8] if r["support_tickets"] >= 3 else [0.9, 0.1] for r in rows[:n]]})
        self._send(200, {"predictions": [1 if r["support_tickets"] >= 3 else 0 for r in rows[:n]]})


class FakeMlflow(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _MlflowHandler)
        self.versions = {"churn-model": {
            "1": {"run": "r1", "metrics": {"accuracy": 0.80}, "status": "READY"},
            "2": {"run": "r2", "metrics": {"accuracy": 0.90}, "status": "READY"},
            "3": {"run": "r3", "metrics": {"accuracy": 0.70}, "status": "READY"}}}
        self.aliases = {("churn-model", "champion"): "1"}
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"

    def mv(self, name, v):
        d = self.versions[name][v]
        return {"name": name, "version": v, "run_id": d["run"], "status": d["status"], "current_stage": "None"}


class _MlflowHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u, srv = urlparse(self.path), self.server
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.replace("/api/2.0/mlflow/", "")
        if p == "experiments/search":
            return self._send(200, {"experiments": []})
        if p == "registered-models/search":
            return self._send(200, {"registered_models": [
                {"name": n, "aliases": [{"alias": a, "version": v} for (m, a), v in srv.aliases.items() if m == n]} for n in srv.versions]})
        if p == "model-versions/search":
            name = q["filter"].split("'")[1]
            return self._send(200, {"model_versions": [srv.mv(name, v) for v in srv.versions.get(name, {})]})
        if p == "model-versions/get":
            if q["version"] not in srv.versions.get(q["name"], {}):
                return self._send(404, {"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "no such version"})
            return self._send(200, {"model_version": srv.mv(q["name"], q["version"])})
        if p == "runs/get":
            for vs in srv.versions.values():
                for d in vs.values():
                    if d["run"] == q["run_id"]:
                        return self._send(200, {"run": {"data": {"metrics": [{"key": k, "value": v} for k, v in d["metrics"].items()]}}})
            return self._send(404, {"message": "no run"})
        if p == "registered-models/alias":
            v = srv.aliases.get((q["name"], q["alias"]))
            if v is None:
                return self._send(404, {"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "no alias"})
            return self._send(200, {"model_version": srv.mv(q["name"], v)})
        self._send(404, {"message": p})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("registered-models/alias"):
            self.server.aliases[(body["name"], body["alias"])] = body["version"]
            return self._send(200, {})
        self._send(404, {})


_scorer = _mlflow = None


def setUpModule():
    global _scorer, _mlflow
    _scorer, _mlflow = FakeScorer(), FakeMlflow()


def tearDownModule():
    for s in (_scorer, _mlflow):
        s.shutdown()


# ── pure units ──────────────────────────────────────────────────────────────────

class DriftMathTests(TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(0)

    def test_same_distribution_is_stable(self):
        a, b = self.rng.normal(50, 10, 3000), self.rng.normal(50, 10, 3000)
        r = drift.compare({"x": a}, {"x": b}, {"x": "numeric"})
        self.assertEqual(r["status"], "ok")
        self.assertLess(r["columns"][0]["psi"], 0.05)

    def test_shifted_numeric_is_drift_and_reports_the_shift(self):
        a, b = self.rng.normal(50, 10, 3000), self.rng.normal(65, 10, 3000)
        r = drift.compare({"x": a}, {"x": b}, {"x": "numeric"})
        self.assertEqual(r["status"], "drift")
        self.assertEqual(r["drifted"], ["x"])
        c = r["columns"][0]
        self.assertAlmostEqual(c["reference"]["mean"], 50, delta=1)
        self.assertAlmostEqual(c["current"]["mean"], 65, delta=1)

    def test_moderate_shift_is_a_warning(self):
        a, b = self.rng.normal(50, 10, 5000), self.rng.normal(53, 10, 5000)
        r = drift.compare({"x": a}, {"x": b}, {"x": "numeric"}, warn=0.02, alert=0.25)
        self.assertEqual(r["status"], "warning")

    def test_category_shift_names_what_moved(self):
        ref = ["a"] * 700 + ["b"] * 300
        cur = ["a"] * 300 + ["b"] * 300 + ["c"] * 400
        r = drift.compare({"k": ref}, {"k": cur}, {"k": "category"})
        self.assertEqual(r["status"], "drift")
        moved = {t["value"] for t in r["columns"][0]["top_changes"]}
        self.assertIn("c", moved)

    def test_new_missing_values_are_detected(self):
        ref = self.rng.normal(0, 1, 2000)
        cur = ref.copy()
        cur[:800] = np.nan
        self.assertEqual(drift.compare({"x": ref}, {"x": cur}, {"x": "numeric"})["status"], "drift")

    def test_constant_reference_column_does_not_crash(self):
        r = drift.compare({"x": np.ones(500)}, {"x": np.ones(500)}, {"x": "numeric"})
        self.assertEqual(r["status"], "ok")

    def test_all_missing_column_is_explained(self):
        with self.assertRaises(drift.DriftConfigError):
            drift.compare({"x": np.full(10, np.nan)}, {"x": np.ones(10)}, {"x": "numeric"})

    def test_thresholds_are_validated_and_columns_sorted_worst_first(self):
        with self.assertRaises(drift.DriftConfigError):
            drift.compare({"x": np.ones(5)}, {"x": np.ones(5)}, {"x": "numeric"}, warn=0.3, alert=0.2)
        a = self.rng.normal(0, 1, 2000)
        r = drift.compare({"calm": a, "wild": a}, {"calm": a + 0.01, "wild": a + 3}, {"calm": "numeric", "wild": "numeric"})
        self.assertEqual([c["name"] for c in r["columns"]], ["wild", "calm"])
        self.assertIn("wild", drift.summarise(r, "Weekly data"))


class UnitTests(TestCase):
    def test_feedback_metrics(self):
        m = feedback_metrics("classification", [1, 0, 1, 1], ["1", 0, 0, "1.0"])
        self.assertEqual((m["rows"], m["metric"], m["value"]), (4, "accuracy", 0.75))
        self.assertEqual(m["details"]["per_class"], {"1": {"actual": 2, "correct": 2}, "0": {"actual": 2, "correct": 1}})
        r = feedback_metrics("regression", [10, 12, 9], [11, 12, 7])
        self.assertAlmostEqual(r["value"], 1.0)
        self.assertAlmostEqual(r["details"]["rmse"], float(np.sqrt((1 + 0 + 4) / 3)))
        with self.assertRaises(MlNodeError):
            feedback_metrics("classification", [None], [1])
        with self.assertRaises(MlNodeError):
            feedback_metrics("regression", ["a"], [1])

    def test_parse_predictions_shapes(self):
        self.assertEqual(parse_predictions({"predictions": [1, 0]}, 2), [{"prediction": 1}, {"prediction": 0}])
        self.assertEqual(parse_predictions([0.5], 1), [{"prediction": 0.5}])
        self.assertEqual(parse_predictions({"predictions": [[0.2, 0.8]]}, 1), [{"prediction": 1, "prediction_proba": 0.8}])
        with self.assertRaises(ScoreError):
            parse_predictions({"predictions": [1]}, 2)
        with self.assertRaises(ScoreError):
            parse_predictions({"oops": 1}, 1)
        with self.assertRaises(ScoreError):
            parse_predictions({"predictions": [{"weird": 1}]}, 1)

    def test_payload_formats(self):
        rows = [{"a": 1, "b": 2}]
        self.assertEqual(build_payload("mlflow_records", rows, ["a", "b"]), {"dataframe_records": rows})
        self.assertEqual(build_payload("mlflow_split", rows, ["b", "a"]), {"dataframe_split": {"columns": ["b", "a"], "data": [[2, 1]]}})
        self.assertEqual(build_payload("records", rows, ["a"]), {"records": rows})

    def test_gates(self):
        res = check_gates([{"metric": "accuracy", "op": ">=", "value": 0.85}, {"metric": "f1", "op": ">", "value": 0.1}], {"accuracy": 0.9})
        self.assertEqual([g["passed"] for g in res], [True, False])
        self.assertIn("no metric", res[1]["note"])
        with self.assertRaises(MlNodeError):
            check_gates([{"metric": "a", "op": "~", "value": 1}], {})
        with self.assertRaises(MlNodeError):
            check_gates([{"metric": "a", "op": ">", "value": "x"}], {})

    def test_names_and_aliases_are_validated(self):
        self.assertEqual(check_model_name("churn-model"), "churn-model")
        for bad in ("", "a'; DROP", "x" * 300, "-bad"):
            with self.assertRaises(MlflowError):
                check_model_name(bad)
        self.assertEqual(check_alias("champion"), "champion")
        for bad in ("latest", "1", "", "has space"):
            with self.assertRaises(MlflowError):
                check_alias(bad)


# ── workflows ───────────────────────────────────────────────────────────────────

def run_wf(h, graph):
    wid = create_workflow(h, graph)
    r = client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def step(ex, node_id):
    return next(s for s in ex["execution_trace"] if s["node_id"] == node_id)["result"]


def make_conn(h, type_, config, name=None, mode="read_only"):
    r = client.post(f"{API}/connections", headers=h, json={"name": name or f"{type_}-{uuid4().hex[:6]}", "type": type_,
                                                           "config": config, "access_mode": mode})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class MlBase(TestCase):
    def setUp(self):
        _scorer.mode = "ok"
        _scorer.requests.clear()
        self.patch = patch.object(settings, "ALLOW_PRIVATE_URLS", True)       # the fakes live on 127.0.0.1
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.email, self.h = setup_user(credits=200)
        self.ep = make_conn(self.h, "ml_endpoint", {"url": _scorer.url, "input_format": "mlflow_records"})

    def score_graph(self, *tail, features=FEATS, **kw):
        load = node("l", "loadDataNode", label="Customers", source="file", fileName="churn_customers.csv")
        score = node("s", "batchScoreNode", label="Score", connectionId=self.ep, features=features, **kw)
        return chain(load, score, *tail)


class ConnectionTests(MlBase):
    def test_types_and_connection_tests(self):
        types = {t["type"]: t for t in client.get(f"{API}/connections/types", headers=self.h).json()}
        self.assertIn("mlflow", types)
        self.assertIn("ml_endpoint", types)
        self.assertTrue(next(f for f in types["mlflow"]["fields"] if f["name"] == "token")["secret"])
        t = client.post(f"{API}/connections/{self.ep}/test", headers=self.h).json()
        self.assertTrue(t["ok"], t)
        ml = make_conn(self.h, "mlflow", {"url": _mlflow.url})
        self.assertTrue(client.post(f"{API}/connections/{ml}/test", headers=self.h).json()["ok"])

    def test_private_servers_are_blocked_without_the_flag(self):
        self.patch.stop()
        try:
            t = client.post(f"{API}/connections/{self.ep}/test", headers=self.h).json()
            self.assertFalse(t["ok"])
            self.assertIn("private", t["message"].lower())
        finally:
            self.patch.start()

    def test_token_is_encrypted_and_masked(self):
        cid = make_conn(self.h, "ml_endpoint", {"url": _scorer.url, "token": "tok-secret-1"})
        self.assertNotIn("tok-secret-1", json.dumps(client.get(f"{API}/connections/{cid}", headers=self.h).json()))


class PredictTests(MlBase):
    def graph(self, **kw):
        inp = node("i", "inputNode", label="Customer", fields=[{"id": "1", "name": n, "type": "text"} for n in FEATS])
        pr = node("p", "predictNode", label="Churn?", connectionId=self.ep, features=FEATS, **kw)
        return chain(inp, pr)

    def run_with(self, graph, values):
        wid = create_workflow(self.h, graph)
        body = {"workflow_id": wid, "input_data": {"node_inputs": {"i": {k: {"content": str(v)} for k, v in values.items()}}}}
        return client.post(f"{API}/workflows/workflows/{wid}/execute", json=body, headers=self.h).json()

    def test_scores_one_record_and_converts_text_numbers(self):
        ex = self.run_with(self.graph(), {"tenure_months": "3", "monthly_spend": "40.5", "support_tickets": "5"})
        r = step(ex, "p")
        self.assertEqual(ex["status"], "completed", ex)
        self.assertEqual(r["prediction"], 1)
        self.assertEqual(r["features"], {"tenure_months": 3, "monthly_spend": 40.5, "support_tickets": 5})
        self.assertTrue(r["prediction_id"])
        sent = _scorer.requests[-1]["body"]["dataframe_records"][0]
        self.assertEqual(sent["support_tickets"], 5)                       # sent as a number, not "5"
        calm = self.run_with(self.graph(), {"tenure_months": 60, "monthly_spend": 80, "support_tickets": 0})
        self.assertEqual(step(calm, "p")["prediction"], 0)

    def test_only_listed_features_are_sent(self):
        g = self.graph()
        g["nodes"][0]["data"]["fields"].append({"id": "9", "name": "email", "type": "text"})
        wid = create_workflow(self.h, g)
        vals = {"tenure_months": 1, "monthly_spend": 2, "support_tickets": 3, "email": "a@b.com"}
        body = {"workflow_id": wid, "input_data": {"node_inputs": {"i": {k: {"content": str(v)} for k, v in vals.items()}}}}
        client.post(f"{API}/workflows/workflows/{wid}/execute", json=body, headers=self.h)
        self.assertNotIn("email", _scorer.requests[-1]["body"]["dataframe_records"][0])

    def test_settings_errors_are_explained_and_not_billed(self):
        before = credits_used(self.email)
        vals = {"tenure_months": 1, "monthly_spend": 2, "support_tickets": 3}
        no_conn = self.graph()
        no_conn["nodes"][1]["data"]["connectionId"] = ""
        self.assertIn("Nothing is chosen for you", step(self.run_with(no_conn, vals), "p")["error"])
        no_feats = self.graph()
        no_feats["nodes"][1]["data"]["features"] = []
        self.assertIn("List the features", step(self.run_with(no_feats, vals), "p")["error"])
        wrong = self.graph()
        wrong["nodes"][1]["data"]["connectionId"] = make_conn(self.h, "mlflow", {"url": _mlflow.url})
        self.assertIn("needs a ml_endpoint connection", step(self.run_with(wrong, vals), "p")["error"])
        self.assertIn("not found in the previous node", step(self.run_with(self.graph(), {"tenure_months": 1}), "p")["error"])
        self.assertEqual(credits_used(self.email), before)                      # none of the failed Predict nodes were billed
        self.assertEqual(sum(1 for _ in _scorer.requests), 0)

    def test_billing_is_two_credits_and_endpoint_failure_is_reported(self):
        vals = {"tenure_months": 1, "monthly_spend": 2, "support_tickets": 3}
        before = credits_used(self.email)
        self.run_with(self.graph(), vals)
        self.assertEqual(credits_used(self.email) - before, 2)
        _scorer.mode = "http500"
        err = step(self.run_with(self.graph(), vals), "p")["error"]
        self.assertIn("HTTP 500", err)

    def test_a_table_is_redirected_to_batch_score(self):
        g = chain(node("l", "loadDataNode", source="file", fileName="churn_customers.csv"),
                  node("p", "predictNode", connectionId=self.ep, features=FEATS))
        self.assertIn("Batch Score", step(run_wf(self.h, g), "p")["error"])


class BatchScoreTests(MlBase):
    def test_scores_a_table_and_adds_a_column(self):
        ex = run_wf(self.h, self.score_graph())
        r = step(ex, "s")
        self.assertEqual(ex["status"], "completed", ex)
        self.assertEqual((r["scored_rows"], r["row_count"]), (400, 400))
        self.assertIn("prediction", r["columns"])
        self.assertEqual(r["columns"][:2], ["customer_id", "tenure_months"])           # original columns are kept
        sample = r["dataset"]["sample"]
        self.assertTrue(all(s["prediction"] == (1 if s["support_tickets"] >= 3 else 0) for s in sample))
        self.assertEqual(sum(r["prediction_summary"]["counts"].values()), 400)
        self.assertEqual(r["requests"], 2)                                              # 400 rows / batch size 200
        full = client.get(f"{API}/data/datasets/{r['dataset_id']}/download?format=csv", headers=self.h).text.splitlines()
        self.assertEqual(len(full), 401)
        self.assertTrue(full[0].endswith('"support_tickets","churned","prediction"'))

    def test_only_the_listed_features_leave_the_building(self):
        run_wf(self.h, self.score_graph())
        keys = {k for req in _scorer.requests for row in req["body"]["dataframe_records"] for k in row}
        self.assertEqual(keys, set(FEATS))                                              # no customer_id, no label

    def test_other_request_formats_and_probabilities(self):
        _scorer.mode = "proba"
        r = step(run_wf(self.h, self.score_graph(outputColumn="churn_guess")), "s")
        self.assertEqual(r["output_columns"], ["churn_guess", "churn_guess_proba"])
        self.assertTrue(all(0.0 <= s["churn_guess_proba"] <= 1.0 for s in r["dataset"]["sample"]))
        split = make_conn(self.h, "ml_endpoint", {"url": _scorer.url, "input_format": "mlflow_split"})
        _scorer.mode = "ok"
        g = self.score_graph()
        g["nodes"][1]["data"]["connectionId"] = split
        self.assertEqual(step(run_wf(self.h, g), "s")["scored_rows"], 400)
        self.assertIn("dataframe_split", _scorer.requests[-1]["body"])

    def test_clear_errors(self):
        self.assertIn("List the features", step(run_wf(self.h, self.score_graph(features=[])), "s")["error"])
        self.assertIn("Column(s) not found: nope", step(run_wf(self.h, self.score_graph(features=["nope"])), "s")["error"])
        self.assertIn("already has a column named 'churned'", step(run_wf(self.h, self.score_graph(outputColumn="churned")), "s")["error"])
        self.assertIn("limit for one Batch Score", step(run_wf(self.h, self.score_graph(maxRows=10)), "s")["error"])
        _scorer.mode = "short"
        self.assertIn("returned 199 predictions for 200 rows", step(run_wf(self.h, self.score_graph()), "s")["error"])
        _scorer.mode = "http500"
        self.assertIn("Scoring stopped at row 1", step(run_wf(self.h, self.score_graph()), "s")["error"])

    def test_billing_and_preview(self):
        before = credits_used(self.email)
        run_wf(self.h, self.score_graph())
        self.assertEqual(credits_used(self.email) - before, 1 + 3)                      # load + score (400 rows: no surcharge)
        _scorer.requests.clear()
        wid = create_workflow(self.h, self.score_graph())
        p = client.post(f"{API}/workflows/workflows/{wid}/preview", json={}, headers=self.h).json()
        self.assertTrue([n for n in p["nodes"] if n["node_id"] == "s"][0]["status"] == "skipped")
        self.assertEqual(_scorer.requests, [])                                          # preview never calls the model

    def test_failed_scoring_is_not_billed_for_the_node(self):
        _scorer.mode = "http500"
        before = credits_used(self.email)
        run_wf(self.h, self.score_graph())
        self.assertEqual(credits_used(self.email) - before, 1)                          # only the load

    def test_lineage_names_the_model(self):
        ex = run_wf(self.h, self.score_graph())
        events = client.get(f"{API}/lineage/runs/{ex['id']}/events", headers=self.h).json()
        inputs = {(i["namespace"], i["name"]) for e in events for i in e.get("inputs", [])}
        self.assertTrue(any(ns == "flowmind://models" for ns, _ in inputs), inputs)          # the model is a named input


class DriftNodeTests(MlBase):
    def graph(self, current="churn_this_week.csv", **kw):
        return chain(node("l", "loadDataNode", label="This week", source="file", fileName=current),
                     node("d", "driftCheckNode", label="Drift check", referenceFile="churn_reference.csv", **kw))

    def test_detects_the_drift_in_the_shifted_file_and_stops(self):
        ex = run_wf(self.h, self.graph())
        r = step(ex, "d")
        self.assertEqual(ex["status"], "failed")
        self.assertIn("Data drift", r["error"])
        names = {c["name"]: c for c in r["drift"]["columns"]}
        self.assertEqual(r["drift"]["status"], "drift")
        self.assertEqual(set(names), {"tenure_months", "monthly_spend", "support_tickets"})
        self.assertEqual([x["name"] for x in r["drift"]["skipped"]], ["customer_id"])        # IDs are not "drift"
        self.assertEqual(names["tenure_months"]["status"], "drift")
        self.assertLess(names["tenure_months"]["current"]["mean"], names["tenure_months"]["reference"]["mean"])

    def test_same_distribution_passes_and_warn_mode_continues(self):
        ok = run_wf(self.h, self.graph(current="churn_customers.csv"))
        self.assertEqual(step(ok, "d")["drift"]["status"], "ok")
        self.assertEqual(ok["status"], "completed")
        warn = run_wf(self.h, chain(*self.graph(onDrift="warn")["nodes"], node("s", "summariseDataNode", groupBy=[], aggregations=[{"column": "*", "fn": "count", "as": "n"}])))
        self.assertEqual(warn["status"], "completed", warn)
        self.assertEqual(step(warn, "d")["drift"]["status"], "drift")
        self.assertNotIn("error", step(warn, "d"))

    def test_chosen_columns_and_thresholds(self):
        r = step(run_wf(self.h, self.graph(columns=["monthly_spend"], onDrift="warn", alertAt=50)), "d")
        self.assertEqual([c["name"] for c in r["drift"]["columns"]], ["monthly_spend"])
        self.assertIn(r["drift"]["status"], ("warning", "ok"))

    def test_errors_are_explained(self):
        blank = chain(node("l", "loadDataNode", source="file", fileName="churn_this_week.csv"), node("d", "driftCheckNode", referenceFile=""))
        self.assertIn("Choose the reference file", step(run_wf(self.h, blank), "d")["error"])
        self.assertIn("not in both tables", step(run_wf(self.h, self.graph(columns=["nope"])), "d")["error"])
        self.assertIn("must be", step(run_wf(self.h, self.graph(onDrift="explode")), "d")["error"])

    def test_preview_runs_it_for_free_and_a_fired_gate_is_billed(self):
        before = credits_used(self.email)
        wid = create_workflow(self.h, self.graph())
        p = client.post(f"{API}/workflows/workflows/{wid}/preview", json={}, headers=self.h).json()
        self.assertEqual(credits_used(self.email), before)
        self.assertTrue([n for n in p["nodes"] if n["node_id"] == "d"])
        run_wf(self.h, self.graph())
        self.assertEqual(credits_used(self.email) - before, 1 + 1)                      # load + the drift check that fired


class FeedbackTests(MlBase):
    def graph(self, **kw):
        cfg = dict(modelName="churn-model", taskType="classification", predictionColumn="prediction", actualColumn="churned")
        cfg.update(kw)
        return self.score_graph(node("f", "feedbackNode", label="Feedback", **cfg))

    def test_measures_accuracy_and_records_it(self):
        ex = run_wf(self.h, self.graph())
        r = step(ex, "f")
        self.assertEqual(ex["status"], "completed", ex)
        fb = r["feedback"]
        self.assertEqual((fb["metric"], fb["rows"], fb["recorded"]), ("accuracy", 400, True))
        sc = step(ex, "s")
        full = client.get(f"{API}/data/datasets/{sc['dataset_id']}/download?format=csv", headers=self.h).text.splitlines()[1:]
        want = sum(1 for line in full if line.split(",")[-1] == line.split(",")[-2]) / 400
        self.assertAlmostEqual(fb["value"], want)
        self.assertEqual(r["dataset_id"], sc["dataset_id"])                              # the table passes through unchanged
        hist = client.get(f"{API}/ml/feedback?model=churn-model", headers=self.h).json()
        self.assertEqual((len(hist), hist[0]["metric"], hist[0]["rows"]), (1, "accuracy", 400))
        self.assertAlmostEqual(hist[0]["value"], want)

    def test_threshold_stop_and_warn(self):
        stop = run_wf(self.h, self.graph(threshold=0.99, onFail="stop"))
        self.assertEqual(stop["status"], "failed")
        self.assertIn("got worse", step(stop, "f")["error"])
        warn = run_wf(self.h, self.graph(threshold=0.99, onFail="warn"))
        self.assertEqual(warn["status"], "completed")
        self.assertTrue(step(warn, "f")["feedback"]["breached"])

    def test_history_is_private_and_settings_are_validated(self):
        run_wf(self.h, self.graph())
        _, _, other = signup()
        self.assertEqual(client.get(f"{API}/ml/feedback", headers=other).json(), [])
        self.assertIn("Choose the task type", step(run_wf(self.h, self.graph(taskType="")), "f")["error"])
        self.assertIn("Give the model a name", step(run_wf(self.h, self.graph(modelName="")), "f")["error"])
        self.assertIn("Column 'nope' was not found", step(run_wf(self.h, self.graph(actualColumn="nope")), "f")["error"])

    def test_single_record_mode(self):
        inp = node("i", "inputNode", fields=[{"id": "1", "name": "prediction", "type": "text"}, {"id": "2", "name": "actual", "type": "text"}])
        fb = node("f", "feedbackNode", modelName="churn-model", taskType="classification", predictionColumn="prediction", actualColumn="actual")
        wid = create_workflow(self.h, chain(inp, fb))
        body = {"workflow_id": wid, "input_data": {"node_inputs": {"i": {"prediction": {"content": "1"}, "actual": {"content": "1"}}}}}
        r = client.post(f"{API}/workflows/workflows/{wid}/execute", json=body, headers=self.h).json()
        self.assertEqual(step(r, "f")["feedback"]["value"], 1.0)


class PromoteTests(MlBase):
    def setUp(self):
        super().setUp()
        _mlflow.aliases = {("churn-model", "champion"): "1"}
        self.rw = make_conn(self.h, "mlflow", {"url": _mlflow.url}, mode="read_write")
        self.ro = make_conn(self.h, "mlflow", {"url": _mlflow.url}, mode="read_only")

    def promote(self, **kw):
        cfg = dict(connectionId=self.rw, modelName="churn-model", alias="champion", version="2", gates=[])
        cfg.update(kw)
        ex = run_wf(self.h, chain(node("p", "registryPromoteNode", label="Promote", **cfg)))
        return ex, step(ex, "p")

    def test_promotes_when_gates_pass(self):
        ex, r = self.promote(gates=[{"metric": "accuracy", "op": ">=", "value": 0.85}])
        self.assertEqual(ex["status"], "completed", ex)
        self.assertTrue(r["promoted"])
        self.assertEqual((r["previous_version"], r["version"]), ("1", "2"))
        self.assertEqual(_mlflow.aliases[("churn-model", "champion")], "2")
        self.assertEqual(r["gates"][0]["actual"], 0.9)

    def test_blocks_when_a_gate_fails(self):
        ex, r = self.promote(version="3", gates=[{"metric": "accuracy", "op": ">=", "value": 0.85}])
        self.assertEqual(ex["status"], "failed")
        self.assertIn("Promotion blocked", r["error"])
        self.assertFalse(r["promoted"])
        self.assertEqual(_mlflow.aliases[("churn-model", "champion")], "1")             # nothing changed

    def test_skip_mode_does_not_fail_the_run(self):
        ex, r = self.promote(version="3", onFail="skip", gates=[{"metric": "accuracy", "op": ">=", "value": 0.85}])
        self.assertEqual(ex["status"], "completed")
        self.assertFalse(r["promoted"])
        self.assertIn("Skipped", r["reason"])

    def test_must_beat_the_current_model(self):
        _, r = self.promote(version="3", beatCurrent=True, compareMetric="accuracy")      # 0.70 vs champion v1 0.80
        self.assertIn("accuracy vs current v1", r["error"])
        _, ok = self.promote(version="2", beatCurrent=True, compareMetric="accuracy")     # 0.90 vs 0.80
        self.assertTrue(ok["promoted"])

    def test_latest_and_already_promoted(self):
        _, r = self.promote(version="latest")
        self.assertEqual(r["version"], "3")
        _, again = self.promote(version="latest")
        self.assertFalse(again["promoted"])
        self.assertIn("already has the alias", again["reason"])

    def test_read_only_connection_cannot_promote(self):
        _, r = self.promote(connectionId=self.ro)
        self.assertIn("read-only", r["error"])
        self.assertEqual(_mlflow.aliases[("churn-model", "champion")], "1")

    def test_bad_input_is_rejected(self):
        self.assertIn("Alias must", self.promote(alias="latest")[1]["error"])
        self.assertIn("Model name", self.promote(modelName="x'; --")[1]["error"])
        self.assertIn("does not exist", self.promote(version="99")[1]["error"])
        self.assertIn("Version must be", self.promote(version="abc")[1]["error"])
        self.assertIn("Choose a MLflow connection", self.promote(connectionId="")[1]["error"])
        self.assertIn("the run has no metric", str(self.promote(gates=[{"metric": "f1", "op": ">", "value": 0.1}])[1]["gates"]))

    def test_models_api_lists_versions_aliases_and_metrics(self):
        r = client.get(f"{API}/ml/connections/{self.rw}/models", headers=self.h).json()
        self.assertTrue(r["can_promote"])
        m = r["models"][0]
        self.assertEqual(m["name"], "churn-model")
        self.assertEqual([v["version"] for v in m["versions"]], ["3", "2", "1"])
        v1 = next(v for v in m["versions"] if v["version"] == "1")
        self.assertEqual((v1["aliases"], v1["metrics"]["accuracy"]), (["champion"], 0.8))
        self.assertFalse(client.get(f"{API}/ml/connections/{self.ro}/models", headers=self.h).json()["can_promote"])

    def test_connections_are_private(self):
        _, _, other = signup()
        self.assertEqual(client.get(f"{API}/ml/connections/{self.rw}/models", headers=other).status_code, 422)
        self.assertEqual(client.get(f"{API}/ml/connections/{self.rw}/models").status_code, 401)

    def test_try_endpoint_api(self):
        body = {"features": FEATS, "record": {"tenure_months": "3", "monthly_spend": "40", "support_tickets": "5"}}
        r = client.post(f"{API}/ml/endpoints/{self.ep}/score", json=body, headers=self.h).json()
        self.assertEqual((r["prediction"], r["features"]["support_tickets"]), (1, 5))
        bad = client.post(f"{API}/ml/endpoints/{self.ep}/score", json={"features": FEATS, "record": {}}, headers=self.h)
        self.assertEqual(bad.status_code, 422)


# ── real MLflow + real served model, when available ─────────────────────────────

REAL_MLFLOW, REAL_ENDPOINT = os.environ.get("ML_TEST_MLFLOW_URL"), os.environ.get("ML_TEST_ENDPOINT_URL")


@skipUnless(REAL_MLFLOW and REAL_ENDPOINT, "set ML_TEST_MLFLOW_URL and ML_TEST_ENDPOINT_URL (see scripts/mlflow_demo.py)")
class RealMlflowTests(TestCase):
    def setUp(self):
        self.p = patch.object(settings, "ALLOW_PRIVATE_URLS", True)
        self.p.start()
        self.addCleanup(self.p.stop)
        self.email, self.h = setup_user(credits=300)
        self.ep = make_conn(self.h, "ml_endpoint", {"url": REAL_ENDPOINT})
        self.ml = make_conn(self.h, "mlflow", {"url": REAL_MLFLOW}, mode="read_write")

    def test_connections_work(self):
        for cid in (self.ep, self.ml):
            self.assertTrue(client.post(f"{API}/connections/{cid}/test", headers=self.h).json()["ok"])
        models = client.get(f"{API}/ml/connections/{self.ml}/models", headers=self.h).json()["models"]
        self.assertEqual(models[0]["name"], "churn-model")
        self.assertIn("accuracy", models[0]["versions"][0]["metrics"])

    def test_real_model_scores_a_table_and_feedback_reflects_its_accuracy(self):
        g = chain(node("l", "loadDataNode", source="file", fileName="churn_customers.csv"),
                  node("s", "batchScoreNode", connectionId=self.ep, features=FEATS, batchSize=200),
                  node("f", "feedbackNode", modelName="churn-model", taskType="classification", predictionColumn="prediction", actualColumn="churned"))
        ex = run_wf(self.h, g)
        self.assertEqual(ex["status"], "completed", ex)
        self.assertEqual(step(ex, "s")["scored_rows"], 400)
        self.assertGreater(step(ex, "f")["feedback"]["value"], 0.75)                    # a real model, clearly better than chance

    def test_real_promotion_round_trip(self):
        alias = f"qa{uuid4().hex[:6]}"
        g = chain(node("p", "registryPromoteNode", connectionId=self.ml, modelName="churn-model", alias=alias, version="latest",
                       gates=[{"metric": "accuracy", "op": ">=", "value": 0.5}]))
        r = step(run_wf(self.h, g), "p")
        self.assertTrue(r["promoted"], r)
        again = step(run_wf(self.h, g), "p")
        self.assertFalse(again["promoted"])
