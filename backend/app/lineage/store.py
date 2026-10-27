import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from app.lineage import openlineage as ol
from app.models.lineage import LineageEvent

logger = logging.getLogger(__name__)


def _store(user_id: Any, execution_id: Any, events: List[Dict[str, Any]]) -> None:
    with SessionLocal() as db:
        for ev in events:
            try:
                when = datetime.fromisoformat(ev["eventTime"].replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                when = datetime.utcnow()
            db.add(LineageEvent(
                id=uuid.uuid4(), user_id=user_id, execution_id=execution_id, event_type=ev["eventType"],
                event_time=when, job_name=ev["job"]["name"], payload=ev,
            ))
        db.commit()


async def record_run(
    *, user_id: Any, execution_id: Any, workflow_name: str, started_at: Optional[datetime],
    completed_at: Optional[datetime], status: str, error: Optional[str], trace: List[Dict[str, Any]],
    labels: Dict[str, str], terminal_node_ids: List[str],
) -> int:
    """Build, store and (optionally) forward the OpenLineage events of a finished run. Never raises."""
    try:
        events = ol.build_events(
            execution_id=execution_id, workflow_name=workflow_name, started_at=started_at, completed_at=completed_at,
            status=status, error=error, trace=trace, labels=labels, terminal_node_ids=terminal_node_ids,
        )
        if not events:
            return 0
        await asyncio.to_thread(_store, user_id, execution_id, events)
        await asyncio.to_thread(ol.emit_http, events)
        return len(events)
    except Exception:  # lineage must never break a run
        logger.exception("could not record lineage for execution %s", execution_id)
        return 0
