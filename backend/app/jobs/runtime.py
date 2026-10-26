"""Wires the worker + scheduler together (embedded in the API process or run standalone)."""
import asyncio
import logging
from typing import List

from app.jobs import scheduler
from app.jobs.queue import queue
from app.jobs.worker import JobHandler, Worker
from app.services import run_service

logger = logging.getLogger(__name__)


def build_worker(**kw) -> Worker:
    return Worker(
        queue,
        {
            run_service.RUN_JOB_KIND: JobHandler(
                run=run_service.handle_run_job,
                on_dead=run_service.on_run_dead,
                on_cancel=run_service.on_run_cancelled,
            ),
        },
        **kw,
    )


async def run_background(stop: asyncio.Event, *, worker: bool = True, sched: bool = True) -> None:
    tasks: List[asyncio.Task] = []
    if worker:
        tasks.append(asyncio.create_task(build_worker().run_forever(stop)))
    if sched:
        tasks.append(asyncio.create_task(scheduler.run_forever(stop)))
    if tasks:
        await asyncio.gather(*tasks)
