"""Async worker: claims jobs from the queue and runs registered handlers with lease heartbeats."""
import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

from app.core.config import settings
from app.jobs.queue import JobQueue, JobSnapshot

logger = logging.getLogger(__name__)

Handler = Callable[[JobSnapshot], Awaitable[Optional[Dict[str, Any]]]]
Hook = Callable[[JobSnapshot], Any]


@dataclass
class JobHandler:
    run: Handler
    on_dead: Optional[Hook] = None       # called after retries are exhausted
    on_cancel: Optional[Hook] = None     # called when a running job is cancelled


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        handlers: Dict[str, JobHandler],
        *,
        targets: Sequence[str] = ("hosted",),
        concurrency: Optional[int] = None,
        lease_s: Optional[int] = None,
        poll_s: Optional[float] = None,
        worker_id: Optional[str] = None,
    ):
        self.queue = queue
        self.handlers = handlers
        self.targets = tuple(targets)
        self.concurrency = concurrency or settings.WORKER_CONCURRENCY
        self.lease_s = lease_s or settings.JOB_LEASE_SECONDS
        self.poll_s = poll_s if poll_s is not None else settings.JOB_POLL_SECONDS
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._active: set = set()

    # ── one job ────────────────────────────────────────────────────────────────
    async def run_once(self) -> bool:
        """Claim and fully process a single job. Returns False when the queue is empty."""
        job = await asyncio.to_thread(
            self.queue.claim, self.worker_id, self.targets, tuple(self.handlers), self.lease_s
        )
        if job is None:
            return False
        await self._process(job)
        return True

    async def _process(self, job: JobSnapshot) -> None:
        handler = self.handlers[job.kind]
        logger.info("job start | id=%s kind=%s attempt=%d/%d", job.id, job.kind, job.attempts, job.max_attempts)
        task = asyncio.ensure_future(handler.run(job))
        lease_lost = False
        cancelled_by_us = False

        interval = max(self.lease_s / 3, 0.2)
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=interval)
                if task.done():
                    break
                owner, cancel_requested = await asyncio.to_thread(
                    self.queue.heartbeat, job.id, self.worker_id, self.lease_s
                )
                if not owner:
                    lease_lost = True
                    logger.warning("job %s lease lost; abandoning", job.id)
                    task.cancel()
                    break
                if cancel_requested:
                    cancelled_by_us = True
                    task.cancel()
                    break
        finally:
            if not task.done():
                task.cancel()
            await asyncio.wait({task})  # never raises; outcome inspected below

        if lease_lost:
            return  # someone else owns it now

        if cancelled_by_us or task.cancelled():
            await asyncio.to_thread(self.queue.mark_cancelled, job.id, self.worker_id)
            await self._hook(handler.on_cancel, job)
            logger.info("job cancelled | id=%s", job.id)
            return

        exc = task.exception()
        if exc is None:
            await asyncio.to_thread(self.queue.complete, job.id, self.worker_id, task.result() or None)
            logger.info("job done | id=%s", job.id)
            return

        logger.error("job failed | id=%s attempt=%d/%d | %s", job.id, job.attempts, job.max_attempts, exc, exc_info=exc)
        dead = await asyncio.to_thread(self.queue.fail, job.id, self.worker_id, f"{type(exc).__name__}: {exc}")
        if dead is not None:
            logger.error("job dead-lettered | id=%s", job.id)
            await self._hook(handler.on_dead, dead)

    @staticmethod
    async def _hook(hook: Optional[Hook], job: JobSnapshot) -> None:
        if hook is None:
            return
        try:
            res = hook(job)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            logger.exception("job hook failed | id=%s", job.id)

    # ── loops ──────────────────────────────────────────────────────────────────
    async def reap_once(self) -> int:
        dead = await asyncio.to_thread(self.queue.reap_expired)
        for snap in dead:
            handler = self.handlers.get(snap.kind)
            logger.error("job dead-lettered after lease expiry | id=%s", snap.id)
            if handler:
                await self._hook(handler.on_dead, snap)
        return len(dead)

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("worker %s started (concurrency=%d, targets=%s)", self.worker_id, self.concurrency, self.targets)
        sem = asyncio.Semaphore(self.concurrency)
        reaper = asyncio.create_task(self._reaper(stop))

        async def _one(job: JobSnapshot) -> None:
            try:
                await self._process(job)
            finally:
                sem.release()

        try:
            while not stop.is_set():
                await sem.acquire()
                try:
                    job = await asyncio.to_thread(
                        self.queue.claim, self.worker_id, self.targets, tuple(self.handlers), self.lease_s
                    )
                except Exception:
                    sem.release()
                    logger.exception("claim failed")
                    await self._sleep(stop, self.poll_s * 5)
                    continue
                if job is None:
                    sem.release()
                    await self._sleep(stop, self.poll_s)
                    continue
                t = asyncio.create_task(_one(job))
                self._active.add(t)
                t.add_done_callback(self._active.discard)
        finally:
            reaper.cancel()
            if self._active:  # let in-flight jobs finish (bounded)
                await asyncio.wait(self._active, timeout=30)
            logger.info("worker %s stopped", self.worker_id)

    async def _reaper(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.reap_once()
            except Exception:
                logger.exception("reaper failed")
            await self._sleep(stop, max(self.lease_s / 2, 1))

    @staticmethod
    async def _sleep(stop: asyncio.Event, seconds: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
