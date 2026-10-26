"""Standalone worker/scheduler process:  python -m app.worker

Use this to scale workers independently of the API (set WORKER_ENABLED=false / SCHEDULER_ENABLED=false
on the API instances). Importing app.main is deliberately avoided; only the database is needed.
"""
import asyncio
import logging
import signal

from app.core.config import settings
from app.core.database import Base, engine
from app.jobs.runtime import run_background
from app.models import connection, data, job, schedule, user, workflow  # noqa: F401  (register tables)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    Base.metadata.create_all(bind=engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    await run_background(stop, worker=True, sched=settings.SCHEDULER_ENABLED)


if __name__ == "__main__":
    asyncio.run(_main())
