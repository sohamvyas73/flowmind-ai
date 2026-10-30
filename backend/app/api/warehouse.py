import asyncio
import os
import uuid
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.data import EXAMPLES_DIR
from app.core.auth import get_current_user
from app.engine.duckdb_engine import EngineError, EngineInput, run_sql
from app.models.user import User
from app.services import pushdown
from app.services.data_nodes import DataNodeError
from app.storage.local import storage, tenant_key
from app.warehouse.base import WarehouseError, table_ref
from app.warehouse.registry import catalog

router = APIRouter()

# What each warehouse can do in FlowMind, and how well that has been checked (kept in sync with docs/warehouse-guide.md)
VERIFIED = {
    "postgres": "tested against a real PostgreSQL 16 server",
    "redshift": "same protocol as PostgreSQL (tested there); not tested against a real Redshift cluster",
    "clickhouse": "tested against a real ClickHouse 24.8 server",
    "snowflake": "tested against a simulator of the SQL API; not tested against a real account",
    "bigquery": "tested against a simulator of the REST API; not tested against a real project",
    "databricks": "tested against a simulator of the SQL Statement API; not tested against a real workspace",
}


@router.get("/types")
async def warehouse_types(_: User = Depends(get_current_user)):
    return [{**c, "verified": VERIFIED.get(c["type"], "")} for c in catalog()]


class ExamplesIn(BaseModel):
    tables: Optional[List[str]] = None


class ExamplesOut(BaseModel):
    schema_name: str
    tables: List[str]


@router.post("/connections/{connection_id}/examples", response_model=ExamplesOut)
async def install_example_tables(connection_id: UUID, body: ExamplesIn, user: User = Depends(get_current_user)):
    """Copy FlowMind's example CSV files into the user's warehouse as tables, so the guides can be followed there.

    Needs a read-write connection to PostgreSQL or ClickHouse. Existing tables with the same names are replaced."""
    try:
        conn = await asyncio.to_thread(pushdown.load_connection, user.id, str(connection_id))
        if conn.mode != "read_write":
            raise DataNodeError("This connection is read-only. Set it to 'Read & write' to let FlowMind create the example tables.")
        wh = conn.warehouse(write=True)
        if not wh.supports_insert:
            raise DataNodeError(f"Loading example tables is supported for PostgreSQL and ClickHouse (this is {wh.label}).")
        names = sorted(f[:-4] for f in os.listdir(EXAMPLES_DIR) if f.endswith(".csv"))
        wanted = body.tables or names
        bad = [t for t in wanted if t not in names]
        if bad:
            raise DataNodeError(f"Unknown example table(s): {', '.join(bad)}. Choose from: {', '.join(names)}")
        schema = wh.default_schema()
        done = []
        for name in wanted:
            pushdown._check_target(conn, schema, name, wh)
            out = storage.path_for(tenant_key(user.id, "tmp", f"{uuid.uuid4()}.parquet"))
            res = await run_sql([EngineInput("f", os.path.join(EXAMPLES_DIR, name + ".csv"), "csv")], "SELECT * FROM f", out, sample_rows=0)
            import pyarrow.parquet as pq
            table = await asyncio.to_thread(pq.read_table, out)
            os.remove(out)
            cols = [{"name": c["name"], "type": c["type"]} for c in res.columns]
            rows = [[r.get(c["name"]) for c in cols] for r in table.to_pylist()]
            await wh.insert_rows(table_ref(wh.dialect, schema, name), cols, rows, "replace")
            done.append(name)
        return ExamplesOut(schema_name=schema, tables=done)
    except (DataNodeError, WarehouseError, EngineError) as e:
        raise HTTPException(status_code=422, detail=str(e))
