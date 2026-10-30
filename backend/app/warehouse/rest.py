"""Databricks SQL, Snowflake and BigQuery through their documented REST SQL APIs.

Written against each vendor's public API documentation and exercised against simulators of those APIs in the test-suite;
there are no live accounts in this repository's CI, so treat first contact with a real account as a connection test.
"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.core.url_safety import UnsafeURLError, safe_request
from app.warehouse.base import Result, Warehouse, WarehouseError, canonical_type, coerce

POLL_SECONDS = 1.0
MAX_WAIT_SECONDS = 180


class _RestWarehouse(Warehouse):
    flavour = ""

    def _headers(self) -> Dict[str, str]:
        return {}

    async def _http(self, method: str, url: str, *, json_body: Any = None, params: Optional[Dict[str, Any]] = None,
                    headers: Optional[Dict[str, str]] = None, ok=(200,)) -> httpx.Response:
        kw: Dict[str, Any] = {"headers": {**self._headers(), **(headers or {})}}
        if json_body is not None:
            kw["json"] = json_body
        if params:
            kw["params"] = params
        try:
            r = await safe_request(method, url, timeout=60, allow_hosts=self.allow_hosts, **kw)
        except UnsafeURLError as e:
            raise WarehouseError(str(e))
        except httpx.HTTPError as e:
            raise WarehouseError(f"Could not reach {self.label}: {type(e).__name__}")
        if r.status_code not in tuple(ok):
            try:
                body = r.json()
                msg = body.get("message") or (body.get("error") or {}).get("message") or body.get("error_code") or r.text
            except ValueError:
                msg = r.text
            raise WarehouseError(f"{self.label} returned HTTP {r.status_code}: {str(msg)[:300]}")
        return r

    async def test(self) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            await self._run("SELECT 1", limit=1, write=False)
        except WarehouseError as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "message": f"Connected to {self.label}", "latency_ms": int((time.monotonic() - t0) * 1000)}


# ── Databricks SQL Statement Execution API ──────────────────────────────────────

class DatabricksWarehouse(_RestWarehouse):
    type = "databricks"
    dialect = "databricks"
    label = "Databricks SQL"
    flavour = "databricks"

    def _base(self) -> str:
        host = (self.config["host"] or "").strip().replace("https://", "").rstrip("/")
        return f"https://{host}"

    def _headers(self):
        return {"Authorization": f"Bearer {self.config['token']}"}

    def default_schema(self) -> str:
        return self.config.get("schema") or "default"

    async def _run(self, sql: str, *, limit: Optional[int], write: bool) -> Result:
        body: Dict[str, Any] = {"warehouse_id": self.config["warehouse_id"], "statement": sql, "wait_timeout": "30s",
                                "on_wait_timeout": "CONTINUE", "format": "JSON_ARRAY", "disposition": "INLINE"}
        if self.config.get("catalog"):
            body["catalog"] = self.config["catalog"]
        if self.config.get("schema"):
            body["schema"] = self.config["schema"]
        if limit and limit > 0:
            body["row_limit"] = limit
        r = await self._http("POST", self._base() + "/api/2.0/sql/statements", json_body=body)
        data = r.json()
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        while data.get("status", {}).get("state") in ("PENDING", "RUNNING"):
            if time.monotonic() > deadline:
                raise WarehouseError("Databricks took too long to answer")
            await asyncio.sleep(POLL_SECONDS)
            data = (await self._http("GET", f"{self._base()}/api/2.0/sql/statements/{quote(data['statement_id'])}")).json()
        st = data.get("status", {})
        if st.get("state") != "SUCCEEDED":
            raise WarehouseError(f"Databricks: {(st.get('error') or {}).get('message', st.get('state', 'failed'))}"[:300])
        manifest = data.get("manifest") or {}
        cols = [{"name": c["name"], "type": canonical_type(c.get("type_text") or c.get("type_name", ""), "databricks")}
                for c in (manifest.get("schema") or {}).get("columns", [])]
        rows = [[coerce(v, c["type"]) for v, c in zip(row, cols)] for row in (data.get("result") or {}).get("data_array", [])]
        if (data.get("result") or {}).get("next_chunk_index") is not None:
            raise WarehouseError("The result is larger than Databricks returns inline (about 25 MB). Select fewer rows or columns.")
        return Result(cols, rows, truncated=bool(manifest.get("truncated")))

    async def tables(self) -> List[Dict[str, str]]:
        cat = (self.config.get("catalog") or "").replace("`", "")
        src = f"`{cat}`.information_schema.tables" if cat else "information_schema.tables"
        res = await self._run(f"SELECT table_schema, table_name, table_type FROM {src} WHERE table_schema <> 'information_schema' "
                              "ORDER BY table_schema, table_name LIMIT 501", limit=501, write=False)
        return [{"schema": s, "name": n, "type": "view" if "VIEW" in (t or "") else "table"} for s, n, t in res.rows[:500]]

    def create_table_as_statements(self, target, select_sql, mode):
        if mode == "replace":
            return [f"CREATE OR REPLACE TABLE {target} AS {select_sql}"]
        return super().create_table_as_statements(target, select_sql, mode)


# ── Snowflake SQL API v2 ────────────────────────────────────────────────────────

def _snowflake_type(col: Dict[str, Any]) -> str:
    """rowType entries look like {"name": "A", "type": "fixed", "precision": 38, "scale": 0} (lower-case type names)."""
    t = str(col.get("type", "")).lower()
    if t in ("fixed", "number", "decimal", "numeric"):
        return "BIGINT" if int(col.get("scale") or 0) == 0 else f"DECIMAL({int(col.get('precision') or 38)},{int(col.get('scale') or 0)})"
    if t in ("real", "float", "double"):
        return "DOUBLE"
    if t == "boolean":
        return "BOOLEAN"
    if t == "date":
        return "DATE"
    if t.startswith("timestamp"):
        return "TIMESTAMP"
    return "VARCHAR"


class SnowflakeWarehouse(_RestWarehouse):
    type = "snowflake"
    dialect = "snowflake"
    label = "Snowflake"
    flavour = "snowflake"

    def _base(self) -> str:
        acct = (self.config["account"] or "").strip().lower().replace("https://", "").replace(".snowflakecomputing.com", "").rstrip("/")
        return f"https://{acct}.snowflakecomputing.com"

    def _headers(self):
        kind = self.config.get("token_type") or "OAUTH"
        return {"Authorization": f"Bearer {self.config['token']}", "X-Snowflake-Authorization-Token-Type": kind,
                "Accept": "application/json", "User-Agent": "FlowMind/1.0"}

    def default_schema(self) -> str:
        return self.config.get("schema") or "PUBLIC"

    async def _run(self, sql: str, *, limit: Optional[int], write: bool) -> Result:
        body: Dict[str, Any] = {"statement": sql, "timeout": 120}
        for k in ("database", "schema", "warehouse", "role"):
            if self.config.get(k):
                body[k] = self.config[k]
        r = await self._http("POST", self._base() + "/api/v2/statements", json_body=body, ok=(200, 202))
        data = r.json()
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        while r.status_code == 202 or data.get("code") == "333334":
            if time.monotonic() > deadline:
                raise WarehouseError("Snowflake took too long to answer")
            await asyncio.sleep(POLL_SECONDS)
            r = await self._http("GET", f"{self._base()}/api/v2/statements/{quote(data['statementHandle'])}", ok=(200, 202))
            data = r.json()
        meta = data.get("resultSetMetaData") or {}
        row_type = meta.get("rowType") or []
        cols = [{"name": c["name"], "type": _snowflake_type(c)} for c in row_type]
        rows = list(data.get("data") or [])
        for part in range(1, len(meta.get("partitionInfo") or [])):                      # further result partitions
            pr = await self._http("GET", f"{self._base()}/api/v2/statements/{quote(data['statementHandle'])}", params={"partition": part})
            rows += pr.json().get("data") or []
            if limit and limit > 0 and len(rows) >= limit:
                break
        out = [[coerce(v, c["type"], flavour="snowflake") for v, c in zip(row, cols)] for row in rows]
        if limit is not None and limit >= 0:
            out = out[:limit]
        return Result(cols, out)

    async def tables(self) -> List[Dict[str, str]]:
        db = (self.config.get("database") or "").replace('"', "")
        src = f'"{db}".INFORMATION_SCHEMA.TABLES' if db else "INFORMATION_SCHEMA.TABLES"
        res = await self._run(f"SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM {src} WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA' "
                              "ORDER BY TABLE_SCHEMA, TABLE_NAME LIMIT 501", limit=501, write=False)
        return [{"schema": s, "name": n, "type": "view" if "VIEW" in (t or "") else "table"} for s, n, t in res.rows[:500]]

    def create_table_as_statements(self, target, select_sql, mode):
        if mode == "replace":
            return [f"CREATE OR REPLACE TABLE {target} AS {select_sql}"]
        return super().create_table_as_statements(target, select_sql, mode)


# ── BigQuery REST (jobs.query) ──────────────────────────────────────────────────

class BigQueryWarehouse(_RestWarehouse):
    type = "bigquery"
    dialect = "bigquery"
    label = "BigQuery"
    flavour = "bigquery"
    _token: Optional[str] = None
    _token_exp: float = 0

    def default_schema(self) -> str:
        return self.config.get("dataset") or ""

    async def _access_token(self) -> str:
        if self.config.get("access_token"):
            return self.config["access_token"]
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        try:
            sa = json.loads(self.config.get("service_account_json") or "")
            email, key = sa["client_email"], sa["private_key"]
        except (ValueError, KeyError, TypeError):
            raise WarehouseError("The service account JSON is not valid (it needs client_email and private_key)")
        from jose import jwt
        now = int(time.time())
        token_uri = sa.get("token_uri") or "https://oauth2.googleapis.com/token"
        claims = {"iss": email, "scope": "https://www.googleapis.com/auth/bigquery", "aud": token_uri, "iat": now, "exp": now + 3600}
        try:
            assertion = jwt.encode(claims, key, algorithm="RS256")
        except Exception:
            raise WarehouseError("Could not sign the service account token (check the private key)")
        try:
            r = await safe_request("POST", token_uri, timeout=30, allow_hosts=self.allow_hosts,
                                   data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
        except (UnsafeURLError, httpx.HTTPError) as e:
            raise WarehouseError(f"Could not reach Google to sign in: {type(e).__name__}")
        if r.status_code != 200:
            raise WarehouseError(f"Google refused the service account (HTTP {r.status_code})")
        body = r.json()
        self._token, self._token_exp = body["access_token"], time.time() + int(body.get("expires_in", 3600))
        return self._token

    def _api(self) -> str:
        return (self.config.get("api_base") or "https://bigquery.googleapis.com").rstrip("/")

    async def _run(self, sql: str, *, limit: Optional[int], write: bool) -> Result:
        project = quote(self.config["project"], safe="")
        hdr = {"Authorization": f"Bearer {await self._access_token()}"}
        body: Dict[str, Any] = {"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 10000}
        if self.config.get("location"):
            body["location"] = self.config["location"]
        if self.config.get("dataset"):
            body["defaultDataset"] = {"projectId": self.config["project"], "datasetId": self.config["dataset"]}
        data = (await self._http("POST", f"{self._api()}/bigquery/v2/projects/{project}/queries", json_body=body, headers=hdr)).json()
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        while not data.get("jobComplete", True):
            if time.monotonic() > deadline:
                raise WarehouseError("BigQuery took too long to answer")
            await asyncio.sleep(POLL_SECONDS)
            jr = data["jobReference"]
            data = (await self._http("GET", f"{self._api()}/bigquery/v2/projects/{project}/queries/{quote(jr['jobId'])}",
                                     params={"location": jr.get("location", ""), "maxResults": 10000}, headers=hdr)).json()
        if data.get("errors"):
            raise WarehouseError(f"BigQuery: {data['errors'][0].get('message', 'query failed')}"[:300])
        fields = (data.get("schema") or {}).get("fields", [])
        cols = [{"name": f["name"], "type": canonical_type(f.get("type", ""), "bigquery")} for f in fields]
        rows: List[List[Any]] = []

        def take(page):
            for r_ in page.get("rows", []) or []:
                rows.append([coerce(c.get("v"), cols[i]["type"], flavour="bigquery") for i, c in enumerate(r_["f"])])
        take(data)
        while data.get("pageToken") and (limit is None or limit < 0 or len(rows) < limit):
            jr = data["jobReference"]
            data = (await self._http("GET", f"{self._api()}/bigquery/v2/projects/{project}/queries/{quote(jr['jobId'])}",
                                     params={"pageToken": data["pageToken"], "maxResults": 10000, "location": jr.get("location", "")}, headers=hdr)).json()
            take(data)
        if limit is not None and limit >= 0:
            rows = rows[:limit]
        return Result(cols, rows)

    async def tables(self) -> List[Dict[str, str]]:
        ds = self.config.get("dataset")
        if not ds:
            raise WarehouseError("Set a default dataset on the connection to browse its tables")
        res = await self._run(f"SELECT table_schema, table_name, table_type FROM `{self.config['project']}.{ds}`.INFORMATION_SCHEMA.TABLES "
                              "ORDER BY table_name LIMIT 501", limit=501, write=False)
        return [{"schema": s, "name": n, "type": "view" if "VIEW" in (t or "") else "table"} for s, n, t in res.rows[:500]]

    def create_table_as_statements(self, target, select_sql, mode):
        if mode == "replace":
            return [f"CREATE OR REPLACE TABLE {target} AS {select_sql}"]
        return super().create_table_as_statements(target, select_sql, mode)
