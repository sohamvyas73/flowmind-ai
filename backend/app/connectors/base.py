"""Connector interface. One small contract per external system; new systems are mostly repetitive work."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from app.data.dataset import DatasetRef


class FieldSpec(BaseModel):
    name: str
    label: str
    type: str = "text"                 # text | password | number | select
    required: bool = True
    secret: bool = False
    default: Optional[Any] = None
    options: Optional[List[str]] = None
    help: Optional[str] = None


class ConnectorSpec(BaseModel):
    type: str
    label: str
    description: str
    fields: List[FieldSpec]
    supports_discover: bool = False
    supports_preview: bool = False

    @property
    def secret_fields(self) -> List[str]:
        return [f.name for f in self.fields if f.secret]


@dataclass
class TestResult:
    ok: bool
    message: str
    latency_ms: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


class ConnectorError(Exception):
    """A user-facing connector failure (bad config, unreachable, permission denied)."""


class Connector(ABC):
    spec: ConnectorSpec

    @abstractmethod
    async def test(self, config: Dict[str, Any], *, access_mode: str, allow_hosts: Iterable[str]) -> TestResult: ...

    async def discover(self, config: Dict[str, Any], *, access_mode: str, allow_hosts: Iterable[str]) -> Dict[str, Any]:
        raise ConnectorError(f"{self.spec.label} does not support discovery")

    async def preview(
        self, config: Dict[str, Any], *, access_mode: str, allow_hosts: Iterable[str],
        connection_id: Any, schema: str, table: str, limit: int,
    ) -> DatasetRef:
        raise ConnectorError(f"{self.spec.label} does not support preview")

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Check required fields, apply defaults, drop unknown keys. Returns the cleaned config."""
        clean: Dict[str, Any] = {}
        for f in self.spec.fields:
            v = config.get(f.name)
            if v in (None, ""):
                v = f.default
            if f.required and v in (None, ""):
                raise ConnectorError(f"'{f.label}' is required")
            if v not in (None, ""):
                if f.type == "number":
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        raise ConnectorError(f"'{f.label}' must be a number")
                elif f.type == "select" and f.options and v not in f.options:
                    raise ConnectorError(f"'{f.label}' must be one of: {', '.join(f.options)}")
                clean[f.name] = v
        return clean
