"""DatasetRef — the unit nodes exchange in the data plane.

A reference to data plus enough metadata (schema, stats, redacted sample, lineage) to preview, validate
and plan against it, without moving the data itself. See docs/data-engineering-platform.md §6.
"""
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, Field

from app.data.pii import detect_kind

SAMPLE_ROWS = 100
MAX_SAMPLE_ROWS = 1000
MAX_CELL_CHARS = 200

DatasetKind = Literal["table", "file", "query", "stream_window", "vector_collection"]

_PII_NAME_RE = re.compile(
    r"e-?mail|phone|mobile|msisdn|ssn|aadhaar|aadhar|\bpan\b|passport|dob|birth|address|"
    r"password|passwd|secret|token|card|iban|account_?(no|num)|salary",
    re.I,
)
REDACTED = "[REDACTED]"


class Column(BaseModel):
    name: str
    type: str = "unknown"
    nullable: bool = True
    tags: List[str] = Field(default_factory=list)  # pii | key | label


class ColumnStats(BaseModel):
    name: str
    null_count: int = 0
    distinct_in_sample: int = 0


class LineageEdge(BaseModel):
    source: str          # e.g. "file:orders.csv", "dataset:<id>", "connection:<name>/public.orders"
    operation: str = "read"
    # OpenLineage dataset identity for external sources (set by the loader; lets lineage events name real systems)
    namespace: Optional[str] = None
    name: Optional[str] = None


class DatasetLocation(BaseModel):
    connection_id: Optional[uuid.UUID] = None
    target: str = "hosted"             # hosted | pushdown | runner
    schema_name: Optional[str] = None
    table: Optional[str] = None
    path: Optional[str] = None
    query: Optional[str] = None


class DatasetRef(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    kind: DatasetKind = "table"
    location: DatasetLocation = Field(default_factory=DatasetLocation)
    columns: List[Column] = Field(default_factory=list)
    row_count: Optional[int] = None
    row_count_is_estimate: bool = False
    size_bytes: Optional[int] = None
    sample: List[Dict[str, Any]] = Field(default_factory=list)
    stats: List[ColumnStats] = Field(default_factory=list)
    lineage: List[LineageEdge] = Field(default_factory=list)
    produced_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    def pii_columns(self) -> List[str]:
        return [c.name for c in self.columns if "pii" in c.tags]


def tag_column(name: str, base_tags: Optional[Iterable[str]] = None) -> List[str]:
    tags = list(base_tags or [])
    if _PII_NAME_RE.search(name or "") and "pii" not in tags:
        tags.append("pii")
    return tags


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    s = v if isinstance(v, str) else str(v)
    return s if len(s) <= MAX_CELL_CHARS else s[:MAX_CELL_CHARS] + "…"


def build_dataset(
    columns: List[Column],
    rows: List[Dict[str, Any]],
    *,
    kind: DatasetKind = "table",
    location: Optional[DatasetLocation] = None,
    row_count: Optional[int] = None,
    row_count_is_estimate: bool = False,
    size_bytes: Optional[int] = None,
    lineage: Optional[List[LineageEdge]] = None,
    sample_limit: int = SAMPLE_ROWS,
) -> DatasetRef:
    """Assemble a DatasetRef: tags PII columns, caps and redacts the sample, computes simple stats."""
    sample_limit = max(0, min(sample_limit, MAX_SAMPLE_ROWS))
    cols = []
    for c in columns:
        tags = tag_column(c.name, c.tags)
        if "pii" not in tags:  # name looked harmless: look at the values (before they are masked)
            pii_kind = detect_kind(r.get(c.name) for r in rows[:sample_limit])
            if pii_kind:
                tags += ["pii", f"pii:{pii_kind}"]
        cols.append(c.model_copy(update={"tags": tags}))
    pii = {c.name for c in cols if "pii" in c.tags}

    sample = [
        {c.name: (REDACTED if c.name in pii and r.get(c.name) not in (None, "") else _jsonable(r.get(c.name)))
         for c in cols}
        for r in rows[:sample_limit]
    ]
    stats = []
    for c in cols:
        vals = [r.get(c.name) for r in sample]
        stats.append(ColumnStats(
            name=c.name,
            null_count=sum(1 for v in vals if v is None),
            distinct_in_sample=len({str(v) for v in vals if v is not None}),
        ))
    return DatasetRef(
        kind=kind, location=location or DatasetLocation(), columns=cols, row_count=row_count,
        row_count_is_estimate=row_count_is_estimate, size_bytes=size_bytes, sample=sample, stats=stats,
        lineage=lineage or [],
    )
