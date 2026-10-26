"""PostgreSQL-backed job queue.

Jobs live in the same database as runs and credit reservations, so enqueueing can share the
caller's transaction (no dual-write). Workers claim with `SELECT … FOR UPDATE SKIP LOCKED` and
hold a time-limited lease that they extend with heartbeats; expired leases are re-queued, and
jobs that exhaust their attempts are dead-lettered.

Delivery is **at-least-once**: a job whose worker dies after side effects will run again, so
handlers must be idempotent.
"""
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.job import Job, JobState


@dataclass
class JobSnapshot:
    """Detached copy of a job (safe to use after the DB session closes)."""
    id: uuid.UUID
    kind: str
    state: str
    target: str
    payload: Dict[str, Any]
    user_id: Optional[uuid.UUID]
    execution_id: Optional[uuid.UUID]
    group_key: Optional[str]
    attempts: int
    max_attempts: int
    last_error: Optional[str]


def _snap(j: Job) -> JobSnapshot:
    try:
        payload = json.loads(j.payload) if j.payload else {}
    except ValueError:
        payload = {}
    return JobSnapshot(
        id=j.id, kind=j.kind, state=j.state, target=j.target, payload=payload,
        user_id=j.user_id, execution_id=j.execution_id, group_key=j.group_key,
        attempts=j.attempts, max_attempts=j.max_attempts, last_error=j.last_error,
    )


def backoff_seconds(attempt: int) -> int:
    return settings.JOB_RETRY_BASE_SECONDS * (2 ** max(attempt - 1, 0))


class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, kind: str, payload: Dict[str, Any], **kw: Any) -> uuid.UUID: ...
    @abstractmethod
    def claim(self, worker_id: str, targets: Sequence[str], kinds: Sequence[str], lease_s: int) -> Optional[JobSnapshot]: ...
    @abstractmethod
    def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_s: int) -> Tuple[bool, bool]: ...
    @abstractmethod
    def complete(self, job_id: uuid.UUID, worker_id: str, result_meta: Optional[Dict[str, Any]] = None) -> bool: ...
    @abstractmethod
    def fail(self, job_id: uuid.UUID, worker_id: str, error: str) -> Optional[JobSnapshot]: ...
    @abstractmethod
    def cancel(self, job_id: uuid.UUID) -> str: ...
    @abstractmethod
    def mark_cancelled(self, job_id: uuid.UUID, worker_id: str) -> bool: ...
    @abstractmethod
    def reap_expired(self) -> List[JobSnapshot]: ...


class PostgresJobQueue(JobQueue):

    # ── producing ──────────────────────────────────────────────────────────────
    def enqueue(
        self,
        kind: str,
        payload: Dict[str, Any],
        *,
        db: Optional[Session] = None,
        user_id: Optional[uuid.UUID] = None,
        execution_id: Optional[uuid.UUID] = None,
        group_key: Optional[str] = None,
        target: str = "hosted",
        priority: int = 0,
        max_attempts: Optional[int] = None,
        run_after: Optional[datetime] = None,
        capabilities: Optional[List[str]] = None,
    ) -> uuid.UUID:
        """Add a job. Pass `db` to enqueue inside the caller's transaction (caller commits)."""
        job = Job(
            kind=kind,
            target=target,
            priority=priority,
            payload=json.dumps(payload, default=str),
            capabilities=capabilities,
            user_id=user_id,
            execution_id=execution_id,
            group_key=group_key,
            max_attempts=max_attempts or settings.JOB_MAX_ATTEMPTS,
            run_after=run_after or datetime.utcnow(),
        )
        if db is not None:
            db.add(job)
            db.flush()
            return job.id
        with SessionLocal() as own:
            own.add(job)
            own.commit()
            return job.id

    # ── consuming ──────────────────────────────────────────────────────────────
    def claim(self, worker_id, targets, kinds, lease_s):
        now = datetime.utcnow()
        with SessionLocal() as db:
            job = (
                db.query(Job)
                .filter(
                    Job.state == JobState.QUEUED,
                    Job.run_after <= now,
                    Job.target.in_(list(targets)),
                    Job.kind.in_(list(kinds)),
                )
                .order_by(Job.priority.desc(), Job.run_after, Job.created_at)
                .with_for_update(skip_locked=True)
                .first()
            )
            if job is None:
                return None
            job.state = JobState.RUNNING
            job.locked_by = worker_id
            job.attempts = (job.attempts or 0) + 1
            job.started_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_s)
            db.commit()
            return _snap(job)

    def heartbeat(self, job_id, worker_id, lease_s) -> Tuple[bool, bool]:
        """Extend the lease. Returns (still_owner, cancel_requested)."""
        now = datetime.utcnow()
        with SessionLocal() as db:
            res = db.execute(
                update(Job)
                .where(Job.id == job_id, Job.locked_by == worker_id, Job.state == JobState.RUNNING)
                .values(lease_expires_at=now + timedelta(seconds=lease_s))
            )
            db.commit()
            if res.rowcount == 0:
                return False, False
            flag = db.query(Job.cancel_requested).filter(Job.id == job_id).scalar()
            return True, bool(flag)

    def complete(self, job_id, worker_id, result_meta=None) -> bool:
        return self._finish(job_id, worker_id, JobState.SUCCEEDED, result_meta=result_meta)

    def mark_cancelled(self, job_id, worker_id) -> bool:
        return self._finish(job_id, worker_id, JobState.CANCELLED)

    def _finish(self, job_id, worker_id, state, result_meta=None, error=None) -> bool:
        now = datetime.utcnow()
        with SessionLocal() as db:
            res = db.execute(
                update(Job)
                .where(Job.id == job_id, Job.locked_by == worker_id, Job.state == JobState.RUNNING)
                .values(
                    state=state, finished_at=now, lease_expires_at=None, locked_by=None,
                    payload=None,  # scrub user input once terminal
                    result_meta=result_meta,
                    **({"last_error": error} if error else {}),
                )
            )
            db.commit()
            return res.rowcount == 1

    def fail(self, job_id, worker_id, error) -> Optional[JobSnapshot]:
        """Record a failed attempt: re-queue with backoff, or dead-letter when attempts are exhausted.

        Returns the snapshot only when the job was dead-lettered (so the caller can run cleanup)."""
        now = datetime.utcnow()
        with SessionLocal() as db:
            job = (
                db.query(Job)
                .filter(Job.id == job_id, Job.locked_by == worker_id, Job.state == JobState.RUNNING)
                .with_for_update()
                .first()
            )
            if job is None:
                return None
            job.last_error = (error or "")[:2000]
            job.locked_by = None
            job.lease_expires_at = None
            if job.attempts >= job.max_attempts:
                snap = _snap(job)
                job.state = JobState.DEAD
                job.finished_at = now
                job.payload = None
                db.commit()
                snap.state, snap.last_error = JobState.DEAD, job.last_error
                return snap
            job.state = JobState.QUEUED
            job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts))
            db.commit()
            return None

    # ── control ────────────────────────────────────────────────────────────────
    def cancel(self, job_id) -> str:
        """Queued jobs are cancelled immediately; running jobs get a flag the worker honours."""
        now = datetime.utcnow()
        with SessionLocal() as db:
            job = db.query(Job).filter(Job.id == job_id).with_for_update().first()
            if job is None:
                return "not_found"
            if job.state == JobState.QUEUED:
                job.state, job.finished_at, job.payload = JobState.CANCELLED, now, None
            elif job.state == JobState.RUNNING:
                job.cancel_requested = True
            db.commit()
            return job.state

    def reap_expired(self) -> List[JobSnapshot]:
        """Re-queue jobs whose worker stopped heartbeating; return the ones that are now dead-lettered."""
        now = datetime.utcnow()
        dead: List[JobSnapshot] = []
        with SessionLocal() as db:
            jobs = (
                db.query(Job)
                .filter(Job.state == JobState.RUNNING, Job.lease_expires_at < now)
                .with_for_update(skip_locked=True)
                .all()
            )
            for job in jobs:
                job.locked_by = None
                job.lease_expires_at = None
                job.last_error = "Worker lease expired (worker stopped responding)"
                if job.attempts >= job.max_attempts:
                    job.state, job.finished_at = JobState.DEAD, now
                    snap = _snap(job)
                    job.payload = None
                    dead.append(snap)
                else:
                    job.state = JobState.QUEUED
                    job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts))
            db.commit()
        return dead

    # ── observability ──────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with SessionLocal() as db:
            rows = db.query(Job.state, func.count(Job.id)).group_by(Job.state).all()
            counts = {s: n for s, n in rows}
            oldest = db.query(func.min(Job.run_after)).filter(
                Job.state == JobState.QUEUED, Job.run_after <= datetime.utcnow()
            ).scalar()
        return {
            "counts": {s: counts.get(s, 0) for s in (
                JobState.QUEUED, JobState.RUNNING, JobState.SUCCEEDED, JobState.CANCELLED, JobState.DEAD)},
            "oldest_queued_age_s": int((datetime.utcnow() - oldest).total_seconds()) if oldest else 0,
        }

    def has_active(self, group_key: str, db: Optional[Session] = None) -> bool:
        def _q(s: Session) -> bool:
            return s.query(Job.id).filter(
                Job.group_key == group_key, Job.state.in_((JobState.QUEUED, JobState.RUNNING))
            ).first() is not None
        if db is not None:
            return _q(db)
        with SessionLocal() as s:
            return _q(s)


queue = PostgresJobQueue()
