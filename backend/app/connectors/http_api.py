import time
from typing import Any, Dict

import httpx

from app.connectors.base import Connector, ConnectorSpec, FieldSpec, TestResult
from app.core.url_safety import UnsafeURLError, safe_request


class HttpApiConnector(Connector):
    spec = ConnectorSpec(
        type="http_api",
        label="HTTP API",
        description="A REST endpoint with a base URL and optional auth header, reusable across nodes.",
        fields=[
            FieldSpec(name="base_url", label="Base URL", help="https://api.example.com"),
            FieldSpec(name="auth_type", label="Auth", type="select", default="none", options=["none", "bearer", "header"]),
            FieldSpec(name="header_name", label="Header name", required=False, default="X-API-Key",
                      help="Used when Auth is 'header'."),
            FieldSpec(name="token", label="Token / key", type="password", secret=True, required=False),
            FieldSpec(name="health_path", label="Health-check path", required=False, default="/",
                      help="GET this path to test the connection."),
        ],
    )

    def auth_headers(self, config: Dict[str, Any]) -> Dict[str, str]:
        token = config.get("token")
        if config.get("auth_type") == "bearer" and token:
            return {"Authorization": f"Bearer {token}"}
        if config.get("auth_type") == "header" and token:
            return {config.get("header_name") or "X-API-Key": token}
        return {}

    async def test(self, config, *, access_mode, allow_hosts) -> TestResult:
        base = (config["base_url"] or "").rstrip("/")
        url = base + "/" + (config.get("health_path") or "/").lstrip("/")
        t0 = time.monotonic()
        try:
            r = await safe_request("GET", url, timeout=10, allow_hosts=allow_hosts, headers=self.auth_headers(config))
        except UnsafeURLError as e:
            return TestResult(False, str(e))
        except httpx.HTTPError as e:
            return TestResult(False, f"Request failed: {type(e).__name__}")
        ok = r.status_code < 400
        return TestResult(
            ok, f"HTTP {r.status_code}", latency_ms=int((time.monotonic() - t0) * 1000),
            details={"status_code": r.status_code},
        )
