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


_ARROW_BY_PG = {
    "smallint": "int64", "integer": "int64", "bigint": "int64", "real": "float64", "double precision": "float64",
    "numeric": "float64", "boolean": "bool", "date": "date32", "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamp_tz",
}


def _arrow_type(pg_type: str):
    import pyarrow as pa
    kind = _ARROW_BY_PG.get(pg_type, "string")
    return {
        "int64": pa.int64(), "float64": pa.float64(), "bool": pa.bool_(), "date32": pa.date32(),
        "timestamp": pa.timestamp("us"), "timestamp_tz": pa.timestamp("us", tz="UTC"), "string": pa.string(),
    }[kind], kind


def _coerce(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == "float64":
        return float(value)                      # NUMERIC -> double (precision beyond ~15 digits is lost)
    if kind == "string" and not isinstance(value, str):
        return str(value)
    return value


async def stream_table_to_parquet(
    connector: "PostgresConnector", config: Dict[str, Any], *, access_mode: str, allow_hosts: Iterable[str],
    schema: str, table: str, columns: Iterable[str], limit: int, out_path: str,
) -> int:
    """Copy (a slice of) a table into a Parquet file in bounded memory. Returns the number of rows written."""
    conn = await connector._connect(config, access_mode, allow_hosts)

    def _work() -> int:
        import os
        import pyarrow as pa
        import pyarrow.parquet as pq

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as meta:
            meta.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (schema, table),
            )
            all_cols = meta.fetchall()
        if not all_cols:
            raise ConnectorError(f"Table '{schema}.{table}' not found or not accessible")
        wanted = list(columns)
        by_name = {c["column_name"]: c["data_type"] for c in all_cols}
        for w in wanted:
            if w not in by_name:
                raise ConnectorError(f"Column '{w}' does not exist in {schema}.{table}")
        names = wanted or [c["column_name"] for c in all_cols]
        types = [_arrow_type(by_name[n]) for n in names]
        arrow_schema = pa.schema([pa.field(n, t[0]) for n, t in zip(names, types)])

        conn.autocommit = False                       # server-side cursors need a transaction (still read-only)
        query = sql.SQL("SELECT {} FROM {}.{} LIMIT %s").format(
            sql.SQL(", ").join(sql.Identifier(n) for n in names), sql.Identifier(schema), sql.Identifier(table),
        )
        written = 0
        writer = pq.ParquetWriter(out_path, arrow_schema)
        try:
            with conn.cursor(name="fm_stream") as cur:
                cur.itersize = 20_000
                cur.execute(query, (limit,))
                while True:
                    rows = cur.fetchmany(20_000)
                    if not rows:
                        break
                    cols = [pa.array([_coerce(r[i], types[i][1]) for r in rows], type=types[i][0]) for i in range(len(names))]
                    writer.write_table(pa.Table.from_arrays(cols, schema=arrow_schema))
                    written += len(rows)
        finally:
            writer.close()
        return written

    try:
        return await asyncio.to_thread(_work)
    except psycopg2.Error as e:
        raise ConnectorError(_clean_pg_error(e))
    finally:
        conn.close()


def _clean_pg_error(e: Exception) -> str:
    """User-facing message without leaking credentials or internals."""
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:300]
