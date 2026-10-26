import asyncio
import time
from typing import Any, Dict, Iterable

import psycopg2
import psycopg2.extras
from psycopg2 import sql

from app.connectors.base import Connector, ConnectorError, ConnectorSpec, FieldSpec, TestResult
from app.core.url_safety import UnsafeURLError, resolve_public_addresses
from app.data.dataset import Column, DatasetLocation, DatasetRef, LineageEdge, build_dataset

CONNECT_TIMEOUT_S = 10
STATEMENT_TIMEOUT_MS = 15_000
MAX_TABLES = 500
_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


class PostgresConnector(Connector):
    spec = ConnectorSpec(
        type="postgres",
        label="PostgreSQL",
        description="Read tables from a PostgreSQL database. Read-only by default.",
        supports_discover=True,
        supports_preview=True,
        fields=[
            FieldSpec(name="host", label="Host", help="Public hostname. Private hosts need admin allow-listing."),
            FieldSpec(name="port", label="Port", type="number", default=5432),
            FieldSpec(name="database", label="Database"),
            FieldSpec(name="user", label="User"),
            FieldSpec(name="password", label="Password", type="password", secret=True, required=False),
            FieldSpec(name="sslmode", label="SSL mode", type="select", default="require",
                      options=["disable", "prefer", "require", "verify-full"],
                      help="'require' or stronger is recommended."),
        ],
    )

    # ── connection ─────────────────────────────────────────────────────────────
    async def _connect(self, config: Dict[str, Any], access_mode: str, allow_hosts: Iterable[str]):
        host, port = config["host"], int(config.get("port") or 5432)
        try:
            addrs = await resolve_public_addresses(host, port, allow_hosts)
        except UnsafeURLError as e:
            raise ConnectorError(str(e))
        options = f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
        if access_mode != "read_write":
            options += " -c default_transaction_read_only=on"

        def _open():
            # hostaddr pins the connection to the address we validated (no second DNS lookup → no rebinding)
            return psycopg2.connect(
                host=host, hostaddr=addrs[0], port=port, dbname=config["database"], user=config["user"],
                password=config.get("password") or None, sslmode=config.get("sslmode", "require"),
                connect_timeout=CONNECT_TIMEOUT_S, options=options, application_name="flowmind",
            )

        try:
            conn = await asyncio.to_thread(_open)
        except psycopg2.OperationalError as e:
            raise ConnectorError(_clean_pg_error(e))
        if access_mode != "read_write":
            conn.set_session(readonly=True, autocommit=True)
        else:
            conn.autocommit = True
        return conn

    # ── contract ───────────────────────────────────────────────────────────────
    async def test(self, config, *, access_mode, allow_hosts) -> TestResult:
        t0 = time.monotonic()
        try:
            conn = await self._connect(config, access_mode, allow_hosts)
        except ConnectorError as e:
            return TestResult(False, str(e))
        try:
            def _probe():
                with conn.cursor() as cur:
                    cur.execute("SELECT version(), current_database(), current_user, "
                                "current_setting('transaction_read_only')")
                    return cur.fetchone()
            version, db, user, ro = await asyncio.to_thread(_probe)
            return TestResult(
                True, f"Connected to {db} as {user}",
                latency_ms=int((time.monotonic() - t0) * 1000),
                details={"server": version.split(",")[0], "read_only_session": ro == "on"},
            )
        except psycopg2.Error as e:
            return TestResult(False, _clean_pg_error(e))
        finally:
            conn.close()

    async def discover(self, config, *, access_mode, allow_hosts) -> Dict[str, Any]:
        conn = await self._connect(config, access_mode, allow_hosts)
        try:
            def _q():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_schema, table_name, table_type FROM information_schema.tables "
                        "WHERE table_schema <> ALL(%s) AND table_schema NOT LIKE 'pg_temp%%' "
                        "ORDER BY table_schema, table_name LIMIT %s",
                        (list(_SYSTEM_SCHEMAS), MAX_TABLES + 1),
                    )
                    return cur.fetchall()
            rows = await asyncio.to_thread(_q)
            return {
                "tables": [{"schema": s, "name": n, "type": "view" if t == "VIEW" else "table"}
                           for s, n, t in rows[:MAX_TABLES]],
                "truncated": len(rows) > MAX_TABLES,
            }
        except psycopg2.Error as e:
            raise ConnectorError(_clean_pg_error(e))
        finally:
            conn.close()

    async def preview(self, config, *, access_mode, allow_hosts, connection_id, schema, table, limit) -> DatasetRef:
        conn = await self._connect(config, access_mode, allow_hosts)
        try:
            def _q():
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                        (schema, table),
                    )
                    cols = cur.fetchall()
                    if not cols:
                        raise ConnectorError(f"Table '{schema}.{table}' not found or not accessible")
                    cur.execute(
                        sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(sql.Identifier(schema), sql.Identifier(table)),
                        (limit,),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    cur.execute(
                        "SELECT c.reltuples::bigint AS est, pg_total_relation_size(c.oid) AS bytes "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = %s AND c.relname = %s", (schema, table),
                    )
                    meta = cur.fetchone() or {}
                    return cols, rows, meta
            cols, rows, meta = await asyncio.to_thread(_q)
        except psycopg2.Error as e:
            raise ConnectorError(_clean_pg_error(e))
        finally:
            conn.close()

        est = meta.get("est")
        return build_dataset(
            [Column(name=c["column_name"], type=c["data_type"], nullable=c["is_nullable"] == "YES") for c in cols],
            rows,
            kind="table",
            location=DatasetLocation(connection_id=connection_id, schema_name=schema, table=table),
            row_count=int(est) if est is not None and est >= 0 else None,
            row_count_is_estimate=True,
            size_bytes=meta.get("bytes"),
            lineage=[LineageEdge(source=f"connection:{connection_id}/{schema}.{table}", operation="read")],
            sample_limit=limit,
        )


def _clean_pg_error(e: Exception) -> str:
    """User-facing message without leaking credentials or internals."""
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:300]
