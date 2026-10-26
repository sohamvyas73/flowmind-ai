"""Cron scheduler: turns due Schedule rows into background runs.

Two phases keep it safe to run in several processes: (1) claim due rows with SKIP LOCKED and advance
their next_run_at in one short transaction, (2) fire each claimed schedule. If the scheduler was down,
missed fires collapse into a single run (next_run_at is computed from "now").
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.secrets import decrypt
from app.jobs.queue import queue
from app.models.schedule import Schedule
from app.models.user import User
from app.models.workflow import Workflow
from app.services import run_service

logger = logging.getLogger(__name__)


class CronError(ValueError):
    pass


def next_fire(cron: str, tz_name: str, after: Optional[datetime] = None) -> datetime:
    """Next fire time as naive UTC."""
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise CronError(f"Unknown timezone '{tz_name}'")
    base = (after or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(tz)
    nxt = croniter(cron, base).get_next(datetime)
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def validate_cron(cron: str, tz_name: str) -> datetime:
    """Validate a 5-field cron expression and the minimum interval; return the next fire (naive UTC)."""
    cron = (cron or "").strip()
    if len(cron.split()) != 5 or not croniter.is_valid(cron):
        raise CronError("Invalid cron expression (expected 5 fields, e.g. '*/15 * * * *')")
    first = next_fire(cron, tz_name)
    second = next_fire(cron, tz_name, after=first)
    if (second - first).total_seconds() < settings.MIN_SCHEDULE_INTERVAL_SECONDS:
        raise CronError(f"Schedules must be at least {settings.MIN_SCHEDULE_INTERVAL_SECONDS}s apart")
    return first


@dataclass
class _Claimed:
    id: Any
    user_id: Any
    workflow_id: Any
    input_data: Dict[str, Any]


def _claim_due(limit: int = 50) -> List[_Claimed]:
    now = datetime.utcnow()
    claimed: List[_Claimed] = []
    with SessionLocal() as db:
        due = (
            db.query(Schedule)
            .filter(Schedule.enabled == True, Schedule.next_run_at <= now)  # noqa: E712
            .order_by(Schedule.next_run_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for s in due:
            try:
                s.next_run_at = next_fire(s.cron, s.timezone, after=now)
            except Exception as e:  # corrupt schedule: stop it rather than loop forever
                s.enabled, s.last_status = False, f"disabled: {e}"[:100]
                continue
            s.last_run_at = now
            raw = decrypt(s.input_data)
            try:
                payload = json.loads(raw) if raw else {}
            except ValueError:
                payload = {}
            claimed.append(_Claimed(s.id, s.user_id, s.workflow_id, payload))
        db.commit()
    return claimed


def _fire(c: _Claimed) -> None:
    status_text, execution_id = "queued", None
    with SessionLocal() as db:
        try:
            user = db.query(User).filter(User.id == c.user_id).first()
            workflow = db.query(Workflow).filter(Workflow.id == c.workflow_id).first()
            group_key = f"schedule:{c.id}"
            if user is None or workflow is None:
                status_text = "skipped: workflow or user missing"
                db.query(Schedule).filter(Schedule.id == c.id).update({"enabled": False})
            elif not user.is_active:
                status_text = "skipped: account inactive"
            elif queue.has_active(group_key, db):
                status_text = "skipped: previous run still active"
            else:
                execution_id, _ = run_service.prepare_run(
                    db, user, workflow, c.input_data,
                    triggered_by="schedule", schedule_id=c.id, rate_limit=False,
                    enqueue=True, group_key=group_key,
                )
        except HTTPException as e:
            status_text = "skipped: insufficient credits" if e.status_code == 402 else f"error: {e.detail}"[:100]
        except Exception as e:
            logger.exception("schedule %s failed to fire", c.id)
            status_text = f"error: {type(e).__name__}"[:100]
            db.rollback()
        db.query(Schedule).filter(Schedule.id == c.id).update(
            {"last_status": status_text, "last_execution_id": execution_id}
        )
        db.commit()
    logger.info("schedule fired | id=%s status=%s", c.id, status_text)


def tick() -> int:
    claimed = _claim_due()
    for c in claimed:
        _fire(c)
    return len(claimed)


async def run_forever(stop: asyncio.Event) -> None:
    logger.info("scheduler started (tick=%ss)", settings.SCHEDULER_TICK_SECONDS)
    while not stop.is_set():
        try:
            await asyncio.to_thread(tick)
        except Exception:
            logger.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.SCHEDULER_TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("scheduler stopped")
