"""PostgreSQL and Redshift (same wire protocol) via psycopg2, reusing the SSRF-safe, address-pinned connection logic."""
import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras

from app.connectors.base import ConnectorError
from app.connectors.postgres import PostgresConnector, _clean_pg_error
from app.warehouse.base import Result, Warehouse, WarehouseError, quote_ident

_OID = {16: "BOOLEAN", 20: "BIGINT", 21: "BIGINT", 23: "BIGINT", 26: "BIGINT", 700: "DOUBLE", 701: "DOUBLE", 1700: "DOUBLE",
        1082: "DATE", 1114: "TIMESTAMP", 1184: "TIMESTAMP"}
_PG_TYPES = {"BIGINT": "bigint", "DOUBLE": "double precision", "BOOLEAN": "boolean", "DATE": "date", "TIMESTAMP": "timestamp", "VARCHAR": "text"}
STATEMENT_TIMEOUT = "120s"


class PostgresWarehouse(Warehouse):
    type = "postgres"
    dialect = "postgres"
    label = "PostgreSQL"
    supports_insert = True

    def default_schema(self) -> str:
        return "public"

    async def _conn(self, write: bool):
        try:
            return await PostgresConnector()._connect(self.config, "read_write" if write else "read_only", self.allow_hosts)
        except ConnectorError as e:
            raise WarehouseError(str(e))

    async def _run(self, sql: str, *, limit: Optional[int], write: bool) -> Result:
        conn = await self._conn(write)

        def _work() -> Result:
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
                cur.execute(sql)
                if cur.description is None:
                    return Result([])
                cols = [{"name": d.name, "type": _OID.get(d.type_code, "VARCHAR")} for d in cur.description]
                rows = cur.fetchmany(limit) if limit is not None and limit > 0 else (cur.fetchall() if limit != 0 else [])
                return Result(cols, [list(r) for r in rows], truncated=bool(limit and len(rows) >= limit))
        try:
            return await asyncio.to_thread(_work)
        except psycopg2.Error as e:
            raise WarehouseError(_clean_pg_error(e))
        finally:
            conn.close()

    async def test(self) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            res = await self._run("SELECT current_database(), current_user, version()", limit=1, write=False)
        except WarehouseError as e:
            return {"ok": False, "message": str(e)}
        db, user, ver = res.rows[0]
        return {"ok": True, "message": f"Connected to {db} as {user} ({ver.split(',')[0]})", "latency_ms": int((time.monotonic() - t0) * 1000)}

    async def tables(self) -> List[Dict[str, str]]:
        res = await self._run(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast') AND table_schema NOT LIKE 'pg_temp%' "
            "ORDER BY table_schema, table_name LIMIT 501", limit=501, write=False)
        return [{"schema": s, "name": n, "type": "view" if t == "VIEW" else "table"} for s, n, t in res.rows[:500]]

    async def insert_rows(self, target: str, columns: List[Dict[str, str]], rows: Sequence[Sequence[Any]], mode: str) -> None:
        self._need_write()
        conn = await self._conn(True)
        names = ", ".join(quote_ident(c["name"], "postgres") for c in columns)
        ddl = ", ".join(f"{quote_ident(c['name'], 'postgres')} {_PG_TYPES.get(c['type'].split('(')[0], 'text')}" for c in columns)

        def _work():
            with conn.cursor() as cur:
                if mode == "replace":
                    cur.execute(f"DROP TABLE IF EXISTS {target}")
                if mode in ("create", "replace"):
                    cur.execute(f"CREATE TABLE {target} ({ddl})")
                psycopg2.extras.execute_values(cur, f"INSERT INTO {target} ({names}) VALUES %s", [tuple(r) for r in rows], page_size=2000)
        try:
            await asyncio.to_thread(_work)
        except psycopg2.Error as e:
            raise WarehouseError(_clean_pg_error(e))
        finally:
            conn.close()


class RedshiftWarehouse(PostgresWarehouse):
    type = "redshift"
    dialect = "redshift"
    label = "Amazon Redshift"
