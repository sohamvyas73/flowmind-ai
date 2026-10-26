from uuid import UUID
from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from app.core.config import settings
from app.core.database import SessionLocal
from app.jobs import scheduler
from app.jobs.queue import PostgresJobQueue
from app.jobs.runtime import build_worker
from app.models.job import Job
from app.models.schedule import Schedule
from app.models.user import User
from app.models.workflow import WorkflowExecution
from tests.helpers import client, create_workflow, credits_used, reset_jobs, signup

q = PostgresJobQueue()
API = "/api/v1"


def _execution(eid):
    db = SessionLocal()
    ex = db.query(WorkflowExecution).filter(WorkflowExecution.id == UUID(str(eid))).first()
    db.expunge(ex)
    db.close()
    return ex


def _start(headers, wid, data=None):
    return client.post(f"{API}/runs", json={"workflow_id": wid, "input_data": data or {"a": 1}}, headers=headers)


class BackgroundRunTests(IsolatedAsyncioTestCase):
    def setUp(self):
        reset_jobs()

    async def test_async_run_end_to_end(self):
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        r = _start(h, wid)
        self.assertEqual(r.status_code, 202, r.text)
        eid = r.json()["execution_id"]
        self.assertEqual(r.json()["status"], "pending")
        self.assertEqual(credits_used(email), 1)                      # reserved up front (1 transform)

        pending = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual((pending["status"], pending["job"]["state"]), ("pending", "queued"))

        self.assertTrue(await build_worker().run_once())

        done = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["job"]["state"], "succeeded")
        self.assertEqual(done["triggered_by"], "background")
        self.assertEqual(len(done["execution_trace"]), 3)
        self.assertEqual(credits_used(email), 1)                      # settled to actual, not double-charged
        self.assertEqual(_execution(eid).reserved_credits, 0)

        listed = client.get(f"{API}/runs", headers=h).json()
        self.assertEqual([x["execution_id"] for x in listed], [eid])

    async def test_insufficient_credits_creates_nothing(self):
        email, _, h = signup(credits=0)
        wid = create_workflow(h)
        self.assertEqual(_start(h, wid).status_code, 402)
        self.assertFalse(await build_worker().run_once())
        self.assertEqual(client.get(f"{API}/runs", headers=h).json(), [])
        self.assertEqual(credits_used(email), 0)

    async def test_cancel_queued_run_refunds(self):
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        eid = _start(h, wid).json()["execution_id"]
        self.assertEqual(credits_used(email), 1)
        r = client.post(f"{API}/runs/{eid}/cancel", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "cancelled")
        self.assertEqual(r.json()["job"]["state"], "cancelled")
        self.assertEqual(credits_used(email), 0)
        self.assertFalse(await build_worker().run_once())              # nothing left to run
        self.assertEqual(client.post(f"{API}/runs/{eid}/cancel", headers=h).status_code, 409)

    async def test_dead_letter_fails_run_and_refunds_once(self):
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        eid = _start(h, wid).json()["execution_id"]
        w = build_worker()
        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 0), \
             patch("app.services.run_service.execute_prepared", side_effect=RuntimeError("infra down")):
            for _ in range(settings.JOB_MAX_ATTEMPTS):
                await w.run_once()
        run = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["job"]["state"], "dead_lettered")
        self.assertIn("attempt", run["error_message"])
        self.assertEqual(credits_used(email), 0)                        # fully refunded
        from app.services.run_service import abort_execution
        abort_execution(UUID(eid), "again")                                   # idempotent: no double refund
        self.assertEqual(credits_used(email), 0)

    async def test_business_failure_is_not_retried(self):
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        eid = _start(h, wid).json()["execution_id"]
        fake = {"status": "failed", "failed_node_id": "t", "error": "bad data", "execution_trace": [
            {"node_id": "t", "node_type": "transformNode", "result": {"error": "bad data"}}]}
        with patch("app.services.run_service.workflow_executor.execute_workflow", return_value=fake):
            await build_worker().run_once()
        run = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual((run["status"], run["job"]["state"], run["job"]["attempts"]), ("failed", "succeeded", 1))
        self.assertIn("bad data", run["error_message"])
        self.assertEqual(credits_used(email), 1)                        # the node ran, so it is billed

    async def test_redelivered_job_does_not_run_twice(self):
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        eid = _start(h, wid).json()["execution_id"]
        await build_worker().run_once()
        used = credits_used(email)
        from app.services.run_service import execute_prepared
        with patch("app.services.run_service.workflow_executor.execute_workflow", side_effect=AssertionError("re-ran")):
            await execute_prepared(UUID(eid), {})                              # simulates at-least-once redelivery
        self.assertEqual(credits_used(email), used)

    async def test_running_cancel_stops_the_job(self):
        import asyncio
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        eid = _start(h, wid).json()["execution_id"]
        started = asyncio.Event()

        async def slow(*a, **k):
            started.set()
            await asyncio.sleep(30)

        w = build_worker()
        w.lease_s = 0.6
        with patch("app.services.run_service.workflow_executor.execute_workflow", side_effect=slow):
            task = asyncio.create_task(w.run_once())
            await started.wait()
            r = client.post(f"{API}/runs/{eid}/cancel", headers=h)
            self.assertEqual(r.status_code, 200)
            await asyncio.wait_for(task, timeout=10)
        run = client.get(f"{API}/runs/{eid}", headers=h).json()
        self.assertEqual((run["status"], run["job"]["state"]), ("cancelled", "cancelled"))
        self.assertEqual(credits_used(email), 0)


class RunAccessTests(TestCase):
    def setUp(self):
        reset_jobs()

    def test_other_users_cannot_see_or_start_runs(self):
        _, _, h1 = signup(credits=10)
        _, _, h2 = signup(credits=10)
        wid = create_workflow(h1)
        self.assertEqual(_start(h2, wid).status_code, 403)
        eid = _start(h1, wid).json()["execution_id"]
        self.assertEqual(client.get(f"{API}/runs/{eid}", headers=h2).status_code, 403)
        self.assertEqual(client.post(f"{API}/runs/{eid}/cancel", headers=h2).status_code, 403)
        self.assertEqual(client.get(f"{API}/runs", headers=h2).json(), [])

    def test_inactive_user_cannot_start_runs(self):
        _, _, h = signup(activate=False)
        self.assertEqual(client.post(f"{API}/runs", json={"workflow_id": "00000000-0000-0000-0000-000000000000"}, headers=h).status_code, 403)

    def test_sync_execute_still_works_and_is_listed(self):
        email, _, h = signup(credits=10)
        wid = create_workflow(h)
        r = client.post(f"{API}/workflows/workflows/{wid}/execute", json={"workflow_id": wid, "input_data": {}}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "completed")
        self.assertEqual(r.json()["triggered_by"], "manual")
        runs = client.get(f"{API}/runs", params={"workflow_id": wid}, headers=h).json()
        self.assertEqual(runs[0]["triggered_by"], "manual")
        self.assertIsNone(runs[0]["job"])                                # inline runs have no job


class ScheduleApiTests(TestCase):
    def setUp(self):
        reset_jobs()

    def _create(self, h, wid, **kw):
        body = {"workflow_id": wid, "cron": "*/5 * * * *", "name": "every 5"}
        body.update(kw)
        return client.post(f"{API}/schedules", json=body, headers=h)

    def test_validation(self):
        _, _, h = signup(credits=10)
        wid = create_workflow(h)
        self.assertEqual(self._create(h, wid, cron="not a cron").status_code, 422)
        self.assertEqual(self._create(h, wid, cron="* * * *").status_code, 422)              # 4 fields
        self.assertEqual(self._create(h, wid, timezone="Mars/Base").status_code, 422)
        with patch.object(settings, "MIN_SCHEDULE_INTERVAL_SECONDS", 600):
            self.assertEqual(self._create(h, wid, cron="*/5 * * * *").status_code, 422)     # too frequent
        ok = self._create(h, wid, timezone="Asia/Kolkata", input_data={"k": "v"})
        self.assertEqual(ok.status_code, 201, ok.text)
        self.assertEqual(ok.json()["input_data"], {"k": "v"})
        self.assertGreater(datetime.fromisoformat(ok.json()["next_run_at"]), datetime.utcnow() - timedelta(seconds=1))

    def test_input_is_encrypted_at_rest(self):
        from sqlalchemy import text
        from app.core.database import engine
        _, _, h = signup(credits=10)
        wid = create_workflow(h)
        sid = self._create(h, wid, input_data={"ssn": "999-99-9999"}).json()["id"]
        with engine.connect() as c:
            raw = c.execute(text("SELECT input_data FROM schedules WHERE id=:i"), {"i": sid.replace("-", "")}).scalar()
        self.assertTrue(raw.startswith("enc:v1:"))
        self.assertNotIn("999-99-9999", raw)

    def test_crud_ownership_limit_and_cascade(self):
        _, _, h1 = signup(credits=10)
        _, _, h2 = signup(credits=10)
        wid = create_workflow(h1)
        self.assertEqual(self._create(h2, wid).status_code, 403)
        sid = self._create(h1, wid).json()["id"]
        self.assertEqual(client.patch(f"{API}/schedules/{sid}", json={"enabled": False}, headers=h2).status_code, 404)
        off = client.patch(f"{API}/schedules/{sid}", json={"enabled": False}, headers=h1).json()
        self.assertEqual((off["enabled"], off["next_run_at"]), (False, None))
        on = client.patch(f"{API}/schedules/{sid}", json={"enabled": True, "cron": "0 * * * *"}, headers=h1).json()
        self.assertTrue(on["enabled"] and on["next_run_at"])
        self.assertEqual(client.patch(f"{API}/schedules/{sid}", json={"cron": "bad"}, headers=h1).status_code, 422)
        with patch.object(settings, "MAX_SCHEDULES_PER_USER", 1):
            self.assertEqual(self._create(h1, wid).status_code, 409)
        client.delete(f"{API}/workflows/workflows/{wid}", headers=h1)
        self.assertEqual(client.get(f"{API}/schedules", headers=h1).json(), [])


class SchedulerTickTests(IsolatedAsyncioTestCase):
    def setUp(self):
        reset_jobs()

    def _make(self, credits=10, activate=True, **kw):
        email, _, h = signup(credits=credits, activate=activate)
        wid = create_workflow(h)
        # create via the API while active (inactive users can't), then flip state
        sid = client.post(f"{API}/schedules", json={"workflow_id": wid, "cron": "*/5 * * * *", **kw}, headers=h)
        return email, h, wid, sid

    def _due(self, sid):
        db = SessionLocal()
        db.query(Schedule).filter(Schedule.id == UUID(str(sid))).update({"next_run_at": datetime.utcnow() - timedelta(minutes=1)})
        db.commit(); db.close()

    def _sched(self, sid):
        db = SessionLocal()
        s = db.query(Schedule).filter(Schedule.id == UUID(str(sid))).first()
        db.expunge(s); db.close()
        return s

    async def test_due_schedule_enqueues_a_run_that_executes(self):
        email, h, wid, r = self._make(input_data={"x": 1})
        sid = r.json()["id"]
        self.assertEqual(scheduler.tick(), 0)                      # not due yet
        self._due(sid)
        self.assertEqual(scheduler.tick(), 1)
        s = self._sched(sid)
        self.assertEqual(s.last_status, "queued")
        self.assertGreater(s.next_run_at, datetime.utcnow())       # advanced (missed fires collapse into one)
        self.assertEqual(scheduler.tick(), 0)                      # claimed exactly once

        await build_worker().run_once()
        run = client.get(f"{API}/runs/{s.last_execution_id}", headers=h).json()
        self.assertEqual((run["status"], run["triggered_by"], run["schedule_id"]), ("completed", "schedule", sid))
        self.assertEqual(run["input_data"], {"x": 1})

    async def test_overlap_is_skipped(self):
        _, h, wid, r = self._make()
        sid = r.json()["id"]
        self._due(sid); scheduler.tick()                            # first run queued, not yet executed
        self._due(sid); scheduler.tick()
        self.assertEqual(self._sched(sid).last_status, "skipped: previous run still active")
        db = SessionLocal()
        self.assertEqual(db.query(Job).filter(Job.group_key == f"schedule:{sid}").count(), 1)
        db.close()

    async def test_insufficient_credits_and_inactive_account_are_skipped(self):
        email, h, wid, r = self._make(credits=0)
        sid = r.json()["id"]
        self._due(sid); scheduler.tick()
        self.assertEqual(self._sched(sid).last_status, "skipped: insufficient credits")

        email2, h2, wid2, r2 = self._make()
        sid2 = r2.json()["id"]
        db = SessionLocal()
        db.query(User).filter(User.email == email2).update({"is_active": False}); db.commit(); db.close()
        self._due(sid2); scheduler.tick()
        self.assertEqual(self._sched(sid2).last_status, "skipped: account inactive")
        self.assertFalse(await build_worker().run_once())

    async def test_disabled_schedule_never_fires(self):
        _, h, wid, r = self._make()
        sid = r.json()["id"]
        client.patch(f"{API}/schedules/{sid}", json={"enabled": False}, headers=h)
        db = SessionLocal()
        db.query(Schedule).filter(Schedule.id == UUID(str(sid))).update({"next_run_at": datetime.utcnow() - timedelta(hours=1)})
        db.commit(); db.close()
        self.assertEqual(scheduler.tick(), 0)

    def test_timezone_is_honoured(self):
        now = datetime(2026, 1, 1, 0, 0)                            # 00:00 UTC == 05:30 IST
        utc = scheduler.next_fire("0 9 * * *", "UTC", after=now)
        ist = scheduler.next_fire("0 9 * * *", "Asia/Kolkata", after=now)
        self.assertEqual(utc, datetime(2026, 1, 1, 9, 0))
        self.assertEqual(ist, datetime(2026, 1, 1, 3, 30))          # 09:00 IST == 03:30 UTC


class AdminJobsTests(TestCase):
    def test_admin_only_stats(self):
        from tests.helpers import admin_headers
        _, _, h = signup()
        self.assertEqual(client.get(f"{API}/admin/jobs/stats", headers=h).status_code, 403)
        r = client.get(f"{API}/admin/jobs/stats", headers=admin_headers())
        self.assertEqual(r.status_code, 200)
        self.assertIn("counts", r.json())
        self.assertEqual(client.get(f"{API}/admin/jobs", params={"state": "dead_lettered"}, headers=admin_headers()).status_code, 200)


class EmbeddedRuntimeTests(TestCase):
    """Starts the real FastAPI lifespan: embedded worker + scheduler process work without test drivers."""

    def test_embedded_worker_and_scheduler(self):
        import time
        from fastapi.testclient import TestClient
        from app.main import app

        reset_jobs()
        email, _, h = signup(credits=20)
        wid = create_workflow(h)
        sid = client.post(f"{API}/schedules", json={"workflow_id": wid, "cron": "*/5 * * * *"}, headers=h).json()["id"]
        db = SessionLocal()
        db.query(Schedule).filter(Schedule.id == UUID(sid)).update({"next_run_at": datetime.utcnow() - timedelta(minutes=1)})
        db.commit(); db.close()

        def wait_for(pred, timeout=15):
            end = time.time() + timeout
            while time.time() < end:
                v = pred()
                if v:
                    return v
                time.sleep(0.2)
            return None

        with patch.object(settings, "WORKER_ENABLED", True), patch.object(settings, "SCHEDULER_ENABLED", True), \
             patch.object(settings, "JOB_POLL_SECONDS", 0.1), patch.object(settings, "SCHEDULER_TICK_SECONDS", 0.2), \
             TestClient(app):
            eid = _start(h, wid).json()["execution_id"]
            manual = wait_for(lambda: (r := client.get(f"{API}/runs/{eid}", headers=h).json())["status"] == "completed" and r)
            self.assertTrue(manual, "background run was not executed by the embedded worker")

            def scheduled_done():
                runs = [r for r in client.get(f"{API}/runs", headers=h).json() if r["triggered_by"] == "schedule"]
                return runs and runs[0]["status"] == "completed"
            self.assertTrue(wait_for(scheduled_done), "schedule did not fire and complete")
        self.assertEqual(credits_used(email), 2)           # one transform per run, settled once each
