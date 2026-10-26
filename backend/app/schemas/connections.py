from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str
    config: Dict[str, Any]
    access_mode: Literal["read_only", "read_write"] = "read_only"
    host_allowlist: Optional[List[str]] = None  # admin only


class ConnectionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    config: Optional[Dict[str, Any]] = None     # "__secret__" keeps a stored secret
    access_mode: Optional[Literal["read_only", "read_write"]] = None
    host_allowlist: Optional[List[str]] = None  # admin only


class ConnectionResponse(BaseModel):
    id: UUID
    name: str
    type: str
    config: Dict[str, Any]                      # secrets replaced by "__secret__"
    access_mode: str
    host_allowlist: List[str] = []
    last_tested_at: Optional[datetime] = None
    last_test_ok: Optional[bool] = None
    last_test_message: Optional[str] = None
    owner_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: Optional[int] = None
    details: Dict[str, Any] = {}
