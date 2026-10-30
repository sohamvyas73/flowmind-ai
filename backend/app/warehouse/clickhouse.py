"""ClickHouse over its HTTP interface (no driver needed)."""
import json
import time
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.core.url_safety import UnsafeURLError, safe_request
from app.warehouse.base import Result, Warehouse, WarehouseError, canonical_type, coerce, quote_ident

_CH_TYPES = {"BIGINT": "Int64", "DOUBLE": "Float64", "BOOLEAN": "Bool", "DATE": "Date", "TIMESTAMP": "DateTime64(6)", "VARCHAR": "String"}


class ClickHouseWarehouse(Warehouse):
    type = "clickhouse"
    dialect = "clickhouse"
    label = "ClickHouse"
    supports_insert = True

    def default_schema(self) -> str:
        return self.config.get("database") or "default"

    def _headers(self) -> Dict[str, str]:
        h = {"X-ClickHouse-User": self.config.get("user") or "default"}
        if self.config.get("password"):
            h["X-ClickHouse-Key"] = self.config["password"]
        return h

    async def _post(self, query: str, *, body: Optional[bytes] = None, write: bool, extra: Optional[Dict[str, Any]] = None) -> httpx.Response:
        params: Dict[str, Any] = {
            "database": self.default_schema(), "max_execution_time": 120,
            "output_format_json_quote_64bit_integers": 0, "date_time_input_format": "best_effort",
        }
        if not write:
            params["readonly"] = 1                      # the server itself refuses anything but reads
        params.update(extra or {})
        if body is not None:
            params["query"] = query
            data = body
        else:
            data = query.encode("utf-8")
        try:
            r = await safe_request("POST", self.config["url"].rstrip("/") + "/", timeout=130, allow_hosts=self.allow_hosts,
                                   headers=self._headers(), params=params, content=data)
        except UnsafeURLError as e:
            raise WarehouseError(str(e))
        except httpx.HTTPError as e:
            raise WarehouseError(f"Could not reach ClickHouse: {type(e).__name__}")
        if r.status_code >= 400:
            msg = r.text.strip().splitlines()[0] if r.text.strip() else f"HTTP {r.status_code}"
            raise WarehouseError(f"ClickHouse: {msg[:300].replace(self.config.get('password') or chr(0), '***')}")
        return r

    async def _run(self, sql: str, *, limit: Optional[int], write: bool) -> Result:
        if write:
            await self._post(sql, write=True)
            return Result([])
        r = await self._post(sql + "\nFORMAT JSONCompact", write=False)
        data = r.json()
        cols = [{"name": m["name"], "type": canonical_type(m["type"], "clickhouse")} for m in data.get("meta", [])]
        rows = [[coerce(v, c["type"]) for v, c in zip(row, cols)] for row in data.get("data", [])]
        return Result(cols, rows, truncated=bool(limit is not None and limit > 0 and len(rows) >= limit))

    async def test(self) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            res = await self._run("SELECT version(), currentDatabase(), currentUser()", limit=1, write=False)
        except WarehouseError as e:
            return {"ok": False, "message": str(e)}
        v, db, user = res.rows[0]
        return {"ok": True, "message": f"Connected to ClickHouse {v} (database {db}, user {user})",
                "latency_ms": int((time.monotonic() - t0) * 1000)}

    async def tables(self) -> List[Dict[str, str]]:
        res = await self._run(
            "SELECT database, name, engine FROM system.tables WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema') "
            "ORDER BY database, name LIMIT 501", limit=501, write=False)
        return [{"schema": d, "name": n, "type": "view" if "View" in e else "table"} for d, n, e in res.rows[:500]]

    def create_table_as_statements(self, target: str, select_sql: str, mode: str) -> List[str]:
        eng = "ENGINE = MergeTree ORDER BY tuple()"
        if mode == "replace":
            return [f"DROP TABLE IF EXISTS {target}", f"CREATE TABLE {target} {eng} AS {select_sql}"]
        if mode == "append":
            return [f"INSERT INTO {target} {select_sql}"]
        return [f"CREATE TABLE {target} {eng} AS {select_sql}"]

    async def insert_rows(self, target: str, columns: List[Dict[str, str]], rows: Sequence[Sequence[Any]], mode: str) -> None:
        self._need_write()
        ddl_cols = ", ".join(f"{quote_ident(c['name'], 'clickhouse')} Nullable({_CH_TYPES.get(c['type'].split('(')[0], 'String')})" for c in columns)
        if mode == "replace":
            await self._post(f"DROP TABLE IF EXISTS {target}", write=True)
        if mode in ("create", "replace"):
            await self._post(f"CREATE TABLE {target} ({ddl_cols}) ENGINE = MergeTree ORDER BY tuple()", write=True)
        names = [c["name"] for c in columns]
        for i in range(0, len(rows), 5000):
            lines = "\n".join(json.dumps(dict(zip(names, r)), default=str) for r in rows[i:i + 5000])
            await self._post(f"INSERT INTO {target} FORMAT JSONEachRow", body=lines.encode("utf-8"), write=True)
