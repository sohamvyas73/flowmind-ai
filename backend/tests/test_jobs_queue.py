import asyncio
import threading
import uuid
from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase, skipUnless
from unittest.mock import patch

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.jobs.queue import PostgresJobQueue
from app.jobs.worker import JobHandler, Worker
from app.models.job import Job, JobState
from tests.helpers import reset_jobs

IS_PG = engine.dialect.name == "postgresql"
q = PostgresJobQueue()


def _job(job_id):
    db = SessionLocal()
    j = db.query(Job).filter(Job.id == job_id).first()
    db.expunge(j)
    db.close()
    return j


class QueueTests(TestCase):
    def setUp(self):
        reset_jobs()
        self.kind = f"k_{uuid.uuid4().hex[:6]}"

    def test_claim_complete_scrubs_payload(self):
        jid = q.enqueue(self.kind, {"secret": "pii"})
        snap = q.claim("w1", ["hosted"], [self.kind], 30)
        self.assertEqual(snap.id, jid)
        self.assertEqual(snap.payload, {"secret": "pii"})
        self.assertEqual(snap.attempts, 1)
        self.assertTrue(q.complete(jid, "w1", {"ok": 1}))
        j = _job(jid)
        self.assertEqual(j.state, JobState.SUCCEEDED)
        self.assertIsNone(j.payload)            # user input scrubbed once terminal
        self.assertIsNone(q.claim("w1", ["hosted"], [self.kind], 30))

    def test_payload_is_encrypted_at_rest(self):
        from sqlalchemy import text
        jid = q.enqueue(self.kind, {"ssn": "123-45-6789"})
        with engine.connect() as c:
            raw = c.execute(text("SELECT payload FROM jobs WHERE id = :i"), {"i": str(jid).replace("-", "")}).scalar()
        self.assertTrue(raw.startswith("enc:v1:"))
        self.assertNotIn("123-45-6789", raw)

    def test_ordering_run_after_target_and_kind_filters(self):
        later = q.enqueue(self.kind, {}, run_after=datetime.utcnow() + timedelta(hours=1))
        low = q.enqueue(self.kind, {"n": "low"}, priority=0)
        high = q.enqueue(self.kind, {"n": "high"}, priority=5)
        other_target = q.enqueue(self.kind, {}, target="runner:x", priority=99)
        other_kind = q.enqueue("other_kind", {}, priority=99)
        order = []
        while (s := q.claim("w", ["hosted"], [self.kind], 30)):
            order.append(s.id)
        self.assertEqual(order, [high, low])                 # future/other-target/other-kind jobs untouched
        for jid in (later, other_target, other_kind):
            self.assertEqual(_job(jid).state, JobState.QUEUED)

    def test_fail_retries_with_backoff_then_dead_letters(self):
        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 100):
            jid = q.enqueue(self.kind, {}, max_attempts=2)
            q.claim("w", ["hosted"], [self.kind], 30)
            self.assertIsNone(q.fail(jid, "w", "boom"))
            j = _job(jid)
            self.assertEqual((j.state, j.attempts, j.last_error), (JobState.QUEUED, 1, "boom"))
            self.assertGreater(j.run_after, datetime.utcnow() + timedelta(seconds=90))   # backoff applied
            self.assertIsNone(q.claim("w", ["hosted"], [self.kind], 30))                  # not yet due
        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 0):
            q2 = q.enqueue(self.kind, {"x": 1}, max_attempts=2)
            q.claim("w", ["hosted"], [self.kind], 30)
            q.fail(q2, "w", "e1")
            q.claim("w", ["hosted"], [self.kind], 30)
            dead = q.fail(q2, "w", "e2")
        self.assertEqual(dead.state, JobState.DEAD)
        self.assertEqual(_job(q2).state, JobState.DEAD)
        self.assertIsNone(_job(q2).payload)

    def test_only_lease_owner_can_finish(self):
        jid = q.enqueue(self.kind, {})
        q.claim("owner", ["hosted"], [self.kind], 30)
        self.assertFalse(q.complete(jid, "intruder"))
        self.assertEqual(q.heartbeat(jid, "intruder", 30), (False, False))
        self.assertEqual(q.heartbeat(jid, "owner", 30), (True, False))

    def test_reaper_requeues_then_dead_letters_expired_leases(self):
        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 0):
            jid = q.enqueue(self.kind, {}, max_attempts=2)
            q.claim("w", ["hosted"], [self.kind], -1)            # lease already expired (worker died)
            self.assertEqual(q.reap_expired(), [])
            self.assertEqual(_job(jid).state, JobState.QUEUED)
            q.claim("w2", ["hosted"], [self.kind], -1)
            dead = q.reap_expired()
        self.assertEqual([d.id for d in dead], [jid])
        self.assertEqual(_job(jid).state, JobState.DEAD)

    def test_cancel(self):
        queued = q.enqueue(self.kind, {})
        self.assertEqual(q.cancel(queued), JobState.CANCELLED)
        running = q.enqueue(self.kind, {})
        q.claim("w", ["hosted"], [self.kind], 30)
        self.assertEqual(q.cancel(running), JobState.RUNNING)
        self.assertEqual(q.heartbeat(running, "w", 30), (True, True))      # worker sees the flag
        self.assertEqual(q.cancel(uuid.uuid4()), "not_found")

    def test_enqueue_joins_callers_transaction(self):
        db = SessionLocal()
        jid = q.enqueue(self.kind, {}, db=db)
        db.rollback()
        db.close()
        self.assertIsNone(SessionLocal().query(Job).filter(Job.id == jid).first())

    def test_stats(self):
        q.enqueue(self.kind, {})
        s = q.stats()
        self.assertEqual(s["counts"][JobState.QUEUED], 1)

    @skipUnless(IS_PG, "needs PostgreSQL row locking (set TEST_DATABASE_URL)")
    def test_concurrent_claims_never_double_deliver(self):
        ids = {q.enqueue(self.kind, {"i": i}) for i in range(40)}
        claimed, lock = [], threading.Lock()

        def work(name):
            while (s := q.claim(name, ["hosted"], [self.kind], 30)):
                with lock:
                    claimed.append(s.id)

        threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(claimed), 40)
        self.assertEqual(set(claimed), ids)          # every job exactly once


class WorkerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        reset_jobs()
        self.kind = f"k_{uuid.uuid4().hex[:6]}"
        self.calls = []

    def _worker(self, run, **hooks):
        return Worker(q, {self.kind: JobHandler(run=run, **hooks)}, lease_s=2, poll_s=0.05)

    async def test_success(self):
        async def run(job):
            self.calls.append(job.payload)
            return {"rows": 3}
        jid = q.enqueue(self.kind, {"a": 1})
        self.assertTrue(await self._worker(run).run_once())
        self.assertEqual(self.calls, [{"a": 1}])
        j = _job(jid)
        self.assertEqual((j.state, j.result_meta), (JobState.SUCCEEDED, {"rows": 3}))
        self.assertFalse(await self._worker(run).run_once())      # queue empty

    async def test_failures_retry_then_dead_letter_hook(self):
        dead = []

        async def run(job):
            raise RuntimeError("transient")

        async def on_dead(job):
            dead.append(job)

        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 0):
            jid = q.enqueue(self.kind, {}, max_attempts=3)
            w = self._worker(run, on_dead=on_dead)
            for _ in range(3):
                self.assertTrue(await w.run_once())
        self.assertEqual(_job(jid).state, JobState.DEAD)
        self.assertEqual(_job(jid).attempts, 3)
        self.assertEqual(len(dead), 1)
        self.assertIn("transient", dead[0].last_error)

    async def test_retry_succeeds_on_second_attempt(self):
        async def run(job):
            if job.attempts == 1:
                raise RuntimeError("flaky")
            self.calls.append(job.attempts)

        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 0):
            jid = q.enqueue(self.kind, {})
            w = self._worker(run)
            await w.run_once()
            await w.run_once()
        self.assertEqual(self.calls, [2])
        self.assertEqual(_job(jid).state, JobState.SUCCEEDED)

    async def test_running_job_is_cancelled_via_flag(self):
        cancelled = []
        started = asyncio.Event()

        async def run(job):
            started.set()
            await asyncio.sleep(30)

        async def on_cancel(job):
            cancelled.append(job.id)

        jid = q.enqueue(self.kind, {})
        w = self._worker(run, on_cancel=on_cancel)
        w.lease_s = 0.6                      # heartbeat every 0.2s so the flag is seen quickly
        task = asyncio.create_task(w.run_once())
        await started.wait()
        q.cancel(jid)
        await asyncio.wait_for(task, timeout=10)
        self.assertEqual(_job(jid).state, JobState.CANCELLED)
        self.assertEqual(cancelled, [jid])

    async def test_heartbeat_keeps_long_job_alive_past_lease(self):
        async def run(job):
            await asyncio.sleep(1.5)          # longer than the 0.6s lease

        jid = q.enqueue(self.kind, {})
        w = self._worker(run)
        w.lease_s = 0.6
        task = asyncio.create_task(w.run_once())
        await asyncio.sleep(1.0)
        self.assertEqual(await asyncio.to_thread(q.reap_expired), [])      # lease was extended, not reaped
        await task
        self.assertEqual(_job(jid).state, JobState.SUCCEEDED)

    async def test_reap_calls_dead_hook(self):
        dead = []

        async def on_dead(job):
            dead.append(job.id)

        async def run(job):
            pass

        with patch.object(settings, "JOB_RETRY_BASE_SECONDS", 0):
            jid = q.enqueue(self.kind, {}, max_attempts=1)
            q.claim("crashed", ["hosted"], [self.kind], -1)
            n = await self._worker(run, on_dead=on_dead).reap_once()
        self.assertEqual((n, dead), (1, [jid]))
