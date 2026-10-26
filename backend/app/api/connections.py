import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError
from app.connectors.registry import get_connector, list_specs
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.secrets import SECRET_SENTINEL
from app.data.dataset import DatasetRef
from app.models.connection import Connection
from app.models.user import User
from app.schemas.connections import (
    ConnectionCreate, ConnectionResponse, ConnectionUpdate, TestResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _config(conn: Connection) -> Dict[str, Any]:
    try:
        return json.loads(conn.config) if conn.config else {}
    except ValueError:
        return {}


def _masked(conn: Connection) -> Dict[str, Any]:
    secrets = set(get_connector(conn.type).spec.secret_fields)
    return {k: (SECRET_SENTINEL if k in secrets and v else v) for k, v in _config(conn).items()}


def _respond(conn: Connection, owner_email: Optional[str] = None) -> ConnectionResponse:
    return ConnectionResponse(
        id=conn.id, name=conn.name, type=conn.type, config=_masked(conn), access_mode=conn.access_mode,
        host_allowlist=conn.host_allowlist or [], last_tested_at=conn.last_tested_at,
        last_test_ok=conn.last_test_ok, last_test_message=conn.last_test_message,
        owner_email=owner_email, created_at=conn.created_at, updated_at=conn.updated_at,
    )


def _owned(db: Session, connection_id: UUID, user: User) -> Connection:
    conn = db.query(Connection).filter(Connection.id == connection_id).first()
    if conn is None or (user.role != "admin" and str(conn.user_id) != str(user.id)):
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _clean_allowlist(hosts: Optional[List[str]]) -> List[str]:
    out = []
    for h in hosts or []:
        h = (h or "").strip().lower()
        if h and "/" not in h and " " not in h and h not in out:
            out.append(h)
    return out[:20]


@router.get("/types")
async def connection_types(_: User = Depends(get_current_user)):
    return list_specs()


@router.get("", response_model=List[ConnectionResponse])
async def list_connections(
    all_users: bool = Query(False, alias="all"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Connection, User.email).outerjoin(User, User.id == Connection.user_id)
    if not (all_users and current_user.role == "admin"):
        q = q.filter(Connection.user_id == current_user.id)
    return [_respond(c, email) for c, email in q.order_by(Connection.created_at.desc()).all()]


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        connector = get_connector(body.type)
        config = connector.validate_config(body.config)
    except ConnectorError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if db.query(Connection).filter(Connection.user_id == current_user.id).count() >= settings.MAX_CONNECTIONS_PER_USER:
        raise HTTPException(status_code=409, detail=f"Connection limit reached ({settings.MAX_CONNECTIONS_PER_USER})")
    if body.host_allowlist and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can allow-list private hosts")

    conn = Connection(
        user_id=current_user.id, name=body.name.strip(), type=body.type, config=json.dumps(config),
        access_mode=body.access_mode, host_allowlist=_clean_allowlist(body.host_allowlist),
    )
    db.add(conn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a connection with that name")
    db.refresh(conn)
    return _respond(conn)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return _respond(_owned(db, connection_id, current_user))


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: UUID,
    body: ConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conn = _owned(db, connection_id, current_user)
    data = body.model_dump(exclude_unset=True)

    if "host_allowlist" in data:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can allow-list private hosts")
        conn.host_allowlist = _clean_allowlist(data["host_allowlist"])
    if data.get("name"):
        conn.name = data["name"].strip()
    if data.get("access_mode"):
        conn.access_mode = data["access_mode"]
    if data.get("config") is not None:
        connector = get_connector(conn.type)
        old = _config(conn)
        merged = dict(data["config"])
        for k in connector.spec.secret_fields:  # sentinel / blank keeps the stored secret
            if merged.get(k) in (SECRET_SENTINEL, None, "") and old.get(k):
                merged[k] = old[k]
        try:
            conn.config = json.dumps(connector.validate_config(merged))
        except ConnectorError as e:
            raise HTTPException(status_code=422, detail=str(e))
        conn.last_tested_at = conn.last_test_ok = conn.last_test_message = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a connection with that name")
    db.refresh(conn)
    return _respond(conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    db.delete(_owned(db, connection_id, current_user))
    db.commit()
    return None


async def _run(conn: Connection, op: str, **kw: Any):
    connector = get_connector(conn.type)
    common = dict(access_mode=conn.access_mode, allow_hosts=conn.host_allowlist or [])
    try:
        return await getattr(connector, op)(_config(conn), **common, **kw)
    except ConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{connection_id}/test", response_model=TestResponse)
async def test_connection(
    connection_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    conn = _owned(db, connection_id, current_user)
    result = await _run(conn, "test")
    conn.last_tested_at = datetime.utcnow()
    conn.last_test_ok = result.ok
    conn.last_test_message = result.message[:500]
    db.commit()
    return TestResponse(ok=result.ok, message=result.message, latency_ms=result.latency_ms, details=result.details)


@router.get("/{connection_id}/discover")
async def discover(
    connection_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    return await _run(_owned(db, connection_id, current_user), "discover")


@router.get("/{connection_id}/preview", response_model=DatasetRef)
async def preview(
    connection_id: UUID,
    schema_name: str = Query(..., alias="schema"),
    table: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conn = _owned(db, connection_id, current_user)
    return await _run(conn, "preview", connection_id=conn.id, schema=schema_name, table=table, limit=limit)
