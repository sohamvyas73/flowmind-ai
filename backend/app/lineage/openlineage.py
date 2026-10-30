"""OpenLineage events for pipeline runs.

Every run that executed data nodes produces standard OpenLineage ``RunEvent`` s (built with the official
``openlineage-python`` classes so the facets and schema URLs are exactly the spec's):

* one **workflow** run (START / COMPLETE|FAIL) with the external sources it read and the tables it produced
* one **child run per data node** (linked with a ParentRunFacet) with its input and output datasets,
  the ``schema`` facet, ``outputStatistics`` (rows / bytes), the ``sql`` job facet, and for quality gates the
  ``dataQualityAssertions`` / ``dataQualityMetrics`` facets, plus an ``errorMessage`` facet when it failed.

Events are stored (and exportable as JSON) and, if ``OPENLINEAGE_URL`` is configured, also POSTed to that
OpenLineage-compatible backend (Marquez, DataHub, OpenMetadata…) on a best-effort basis.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openlineage.client import set_producer
from openlineage.client.event_v2 import InputDataset, Job, OutputDataset, Run, RunEvent, RunState
from openlineage.client.facet_v2 import (
    data_quality_assertions_dataset, data_quality_metrics_input_dataset, error_message_run,
    output_statistics_output_dataset, parent_run, schema_dataset, sql_job,
)
from openlineage.client.serde import Serde

from app.core.config import settings

logger = logging.getLogger(__name__)

PRODUCER = "https://github.com/sohamvyas73/flowmind-ai"
set_producer(PRODUCER)

DATASETS_NS = "flowmind://datasets"
FILES_NS = "flowmind://files"
DATA_NODE_TYPES = {"loadDataNode", "cleanDataNode", "combineDataNode", "summariseDataNode", "sqlNode", "qualityGateNode",
                   "batchScoreNode", "driftCheckNode", "feedbackNode", "pullDataNode", "writeWarehouseNode"}
# nodes that hand their input table through unchanged
PASSTHROUGH = {"qualityGateNode", "driftCheckNode", "feedbackNode"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "unnamed"


def _iso(dt: Optional[datetime]) -> str:
    dt = dt or datetime.utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def _edge_identity(edge: Dict[str, Any]) -> Tuple[str, str]:
    """(namespace, name) of a lineage edge."""
    if edge.get("namespace") and edge.get("name"):
        return edge["namespace"], edge["name"]
    src = edge.get("source", "")
    if src.startswith("dataset:"):
        return DATASETS_NS, src.split(":", 1)[1]
    if src.startswith("file:"):
        return FILES_NS, src.split(":", 1)[1]
    return "flowmind://external", src


def _schema_facet(columns: List[Dict[str, Any]]):
    return schema_dataset.SchemaDatasetFacet(
        fields=[schema_dataset.SchemaDatasetFacetFields(name=c["name"], type=c.get("type") or None) for c in columns]
    )


def _quality_facets(q: Dict[str, Any], total_rows: Optional[int]) -> Dict[str, Any]:
    assertions = []
    for r in q.get("rules", []):
        cols = r.get("columns") or []
        col = cols[0] if cols and r.get("type") not in ("min_rows", "max_rows", "schema", "expression") else None
        assertions.append(data_quality_assertions_dataset.Assertion(
            assertion=f"{r['type']}: {r['description']}", success=(r["status"] == "pass"), column=col,
        ))
    facets: Dict[str, Any] = {
        "dataQualityAssertions": data_quality_assertions_dataset.DataQualityAssertionsDatasetFacet(assertions=assertions),
    }
    if total_rows is not None:
        # a not_null check's failure count is that column's null count
        metrics = {
            r["columns"][0]: data_quality_metrics_input_dataset.ColumnMetrics(nullCount=r["failed"])
            for r in q.get("rules", []) if r.get("type") == "not_null" and len(r.get("columns") or []) == 1
        }
        facets["dataQualityMetrics"] = data_quality_metrics_input_dataset.DataQualityMetricsInputDatasetFacet(
            rowCount=total_rows, columnMetrics=metrics)
    return facets


def build_events(
    *, execution_id: Any, workflow_name: str, started_at: Optional[datetime], completed_at: Optional[datetime],
    status: str, error: Optional[str], trace: List[Dict[str, Any]], labels: Dict[str, str],
    terminal_node_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Return OpenLineage RunEvents (as plain dicts). Empty when the run executed no data nodes."""
    steps = [s for s in trace if s.get("node_type") in DATA_NODE_TYPES]
    if not steps:
        return []
    ns = settings.OPENLINEAGE_NAMESPACE
    wf_job = f"workflow.{slug(workflow_name)}"
    wf_run_id = str(execution_id)
    events: List[RunEvent] = []

    external_inputs: Dict[Tuple[str, str], InputDataset] = {}
    last_end = started_at
    terminal_outputs: List[OutputDataset] = []
    terminal = set(terminal_node_ids or [])

    for step in steps:
        r = step.get("result") or {}
        node_id, label = step["node_id"], labels.get(step["node_id"], step["node_id"])
        end = _parse(step.get("timestamp")) or completed_at
        start = last_end or started_at
        last_end = end
        job_name = f"{wf_job}.{slug(label)}-{node_id}"
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{wf_run_id}:{node_id}"))
        failed = "error" in r

        ds = r.get("dataset") or {}
        out_id = r.get("dataset_id")
        inputs: List[InputDataset] = []
        outputs: List[OutputDataset] = []
        if step["node_type"] in PASSTHROUGH:
            if out_id:
                q = r.get("quality") or {}
                inputs.append(InputDataset(
                    namespace=DATASETS_NS, name=out_id, facets={"schema": _schema_facet(ds.get("columns", []))},
                    inputFacets=_quality_facets(q, q.get("total_rows")) if q else {},
                ))
                outputs.append(OutputDataset(namespace=DATASETS_NS, name=out_id))
        else:
            for e in ds.get("lineage", []):
                nsp, name = _edge_identity(e)
                inp = InputDataset(namespace=nsp, name=name)
                inputs.append(inp)
                if nsp != DATASETS_NS:
                    external_inputs[(nsp, name)] = inp
            if out_id:
                outputs.append(OutputDataset(
                    namespace=DATASETS_NS, name=out_id, facets={"schema": _schema_facet(ds.get("columns", []))},
                    outputFacets={"outputStatistics": output_statistics_output_dataset.OutputStatisticsOutputDatasetFacet(
                        rowCount=ds.get("row_count"), size=ds.get("size_bytes"))},
                ))
        if node_id in terminal and outputs and not failed:
            terminal_outputs.append(OutputDataset(namespace=DATASETS_NS, name=out_id))

        job_facets: Dict[str, Any] = {}
        sql = r.get("sql")
        if sql and not str(sql).startswith("--"):
            job_facets["sql"] = sql_job.SQLJobFacet(query=str(sql))
        parent = parent_run.ParentRunFacet(
            run=parent_run.Run(runId=wf_run_id), job=parent_run.Job(namespace=ns, name=wf_job))
        job = Job(namespace=ns, name=job_name, facets=job_facets)

        events.append(RunEvent(eventTime=_iso(start), producer=PRODUCER, eventType=RunState.START,
                               run=Run(runId=run_id, facets={"parent": parent}), job=job,
                               inputs=inputs, outputs=outputs))
        run_facets: Dict[str, Any] = {"parent": parent}
        if failed:
            run_facets["errorMessage"] = error_message_run.ErrorMessageRunFacet(
                message=str(r.get("error", "failed"))[:1000], programmingLanguage="SQL")
        events.append(RunEvent(eventTime=_iso(end), producer=PRODUCER,
                               eventType=RunState.FAIL if failed else RunState.COMPLETE,
                               run=Run(runId=run_id, facets=run_facets), job=job, inputs=inputs, outputs=outputs))

    wf_failed = status == "failed"
    wf_job_obj = Job(namespace=ns, name=wf_job)
    events.insert(0, RunEvent(eventTime=_iso(started_at), producer=PRODUCER, eventType=RunState.START,
                              run=Run(runId=wf_run_id), job=wf_job_obj, inputs=list(external_inputs.values()), outputs=[]))
    wf_facets: Dict[str, Any] = {}
    if wf_failed and error:
        wf_facets["errorMessage"] = error_message_run.ErrorMessageRunFacet(message=error[:1000], programmingLanguage="SQL")
    events.append(RunEvent(eventTime=_iso(completed_at), producer=PRODUCER,
                           eventType=RunState.FAIL if wf_failed else RunState.COMPLETE,
                           run=Run(runId=wf_run_id, facets=wf_facets), job=wf_job_obj,
                           inputs=list(external_inputs.values()), outputs=terminal_outputs))
    return [Serde.to_dict(e) for e in events]


def lineage_summary(trace: List[Dict[str, Any]], labels: Dict[str, str]) -> List[Dict[str, Any]]:
    """Human-friendly step list for the UI: what each data step read, produced, and whether its checks passed."""
    out = []
    for step in trace:
        if step.get("node_type") not in DATA_NODE_TYPES:
            continue
        r = step.get("result") or {}
        ds = r.get("dataset") or {}
        q = r.get("quality")
        reads = []
        if step["node_type"] not in PASSTHROUGH:
            for e in ds.get("lineage", []):
                reads.append({"source": e.get("source"), "operation": e.get("operation")})
        out.append({
            "node_id": step["node_id"], "label": labels.get(step["node_id"], step["node_id"]),
            "node_type": step["node_type"], "reads": reads, "dataset_id": r.get("dataset_id"),
            "row_count": ds.get("row_count"), "columns": len(ds.get("columns", [])),
            "error": r.get("error") if "error" in r else None,
            "quality": ({"passed": q["passed"], "checks": q["checks"], "failed_errors": q["failed_errors"],
                         "failed_warnings": q["failed_warnings"]} if q else None),
            "timestamp": step.get("timestamp"),
        })
    return out


def emit_http(events: List[Dict[str, Any]]) -> int:
    """POST events to the configured OpenLineage backend. Best effort: never raises. Returns events delivered."""
    url = settings.OPENLINEAGE_URL
    if not url or not events:
        return 0
    endpoint = url.rstrip("/") + "/api/v1/lineage"
    headers = {"Content-Type": "application/json"}
    if settings.OPENLINEAGE_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENLINEAGE_API_KEY}"
    sent = 0
    try:
        with httpx.Client(timeout=5) as client:
            for ev in events:
                r = client.post(endpoint, json=ev, headers=headers)
                if r.status_code >= 300:
                    logger.warning("OpenLineage backend rejected an event: HTTP %s", r.status_code)
                    break
                sent += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("OpenLineage emit failed: %s", type(e).__name__)
    return sent
