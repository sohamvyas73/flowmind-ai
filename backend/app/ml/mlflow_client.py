"""A small, SSRF-safe MLflow REST client (model registry + run metrics). No mlflow package, no model code executes."""
import base64
import re
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.core.url_safety import UnsafeURLError, safe_request

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,254}$")
_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,254}$")
_RESERVED_ALIASES = {"latest"}


class MlflowError(Exception):
    """A user-facing MLflow problem."""


def check_model_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME.match(name):
        raise MlflowError("Model name: letters, numbers, spaces, dots, dashes or underscores (max 255)")
    return name


def check_alias(alias: str) -> str:
    alias = (alias or "").strip()
    if not _ALIAS.match(alias) or alias.lower() in _RESERVED_ALIASES:
        raise MlflowError("Alias must start with a letter and use letters, numbers, dots, dashes or underscores "
                          "(for example: champion, production, candidate)")
    return alias


class MlflowClient:
    def __init__(self, url: str, *, token: Optional[str] = None, username: Optional[str] = None,
                 password: Optional[str] = None, allow_hosts: Iterable[str] = ()):
        self.url = (url or "").rstrip("/")
        if not self.url.startswith(("http://", "https://")):
            raise MlflowError("The tracking server URL must start with http:// or https://")
        self.allow_hosts = list(allow_hosts)
        self.headers: Dict[str, str] = {}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        elif username:
            raw = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
            self.headers["Authorization"] = f"Basic {raw}"

    async def _call(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                    body: Optional[Dict[str, Any]] = None, ok: Iterable[int] = (200,)) -> httpx.Response:
        kwargs: Dict[str, Any] = {"headers": self.headers}
        if params:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body
        try:
            r = await safe_request(method, self.url + path, timeout=20, allow_hosts=self.allow_hosts, **kwargs)
        except UnsafeURLError as e:
            raise MlflowError(str(e))
        except httpx.HTTPError as e:
            raise MlflowError(f"Could not reach MLflow at {self.url}: {type(e).__name__}")
        if r.status_code not in tuple(ok):
            try:
                msg = r.json().get("message") or r.text
            except ValueError:
                msg = r.text
            raise MlflowError(f"MLflow returned HTTP {r.status_code}: {str(msg)[:200]}")
        return r

    async def health(self) -> Dict[str, Any]:
        try:
            await self._call("GET", "/api/2.0/mlflow/experiments/search", params={"max_results": 1})
        except MlflowError as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "message": "Connected to the MLflow tracking server"}

    async def list_models(self, limit: int = 200) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        token: Optional[str] = None
        while len(out) < limit:
            params: Dict[str, Any] = {"max_results": 100}
            if token:
                params["page_token"] = token
            data = (await self._call("GET", "/api/2.0/mlflow/registered-models/search", params=params)).json()
            out += data.get("registered_models", [])
            token = data.get("next_page_token")
            if not token:
                break
        return out[:limit]

    async def versions(self, name: str) -> List[Dict[str, Any]]:
        name = check_model_name(name)
        data = (await self._call("GET", "/api/2.0/mlflow/model-versions/search",
                                 params={"filter": f"name='{name}'", "max_results": 200})).json()
        return sorted(data.get("model_versions", []), key=lambda v: int(v["version"]), reverse=True)

    async def model(self, name: str) -> Dict[str, Any]:
        name = check_model_name(name)
        return (await self._call("GET", "/api/2.0/mlflow/registered-models/get", params={"name": name})).json()["registered_model"]

    async def version(self, name: str, version: str) -> Dict[str, Any]:
        name = check_model_name(name)
        r = await self._call("GET", "/api/2.0/mlflow/model-versions/get", params={"name": name, "version": str(version)},
                             ok=(200, 404))
        if r.status_code == 404:
            raise MlflowError(f"Version {version} of '{name}' does not exist")
        return r.json()["model_version"]

    async def run_metrics(self, run_id: Optional[str]) -> Dict[str, float]:
        if not run_id:
            return {}
        r = await self._call("GET", "/api/2.0/mlflow/runs/get", params={"run_id": run_id}, ok=(200, 404))
        if r.status_code == 404:
            return {}
        return {m["key"]: float(m["value"]) for m in r.json().get("run", {}).get("data", {}).get("metrics", [])}

    async def alias_version(self, name: str, alias: str) -> Optional[str]:
        """Version the alias points to, or None. (Real MLflow answers 400 'alias … not found'; others answer 404.)"""
        r = await self._call("GET", "/api/2.0/mlflow/registered-models/alias",
                             params={"name": check_model_name(name), "alias": check_alias(alias)}, ok=(200, 400, 404))
        if r.status_code == 200:
            return str(r.json()["model_version"]["version"])
        if r.status_code == 404 or "not found" in r.text.lower():
            return None
        raise MlflowError(f"MLflow returned HTTP {r.status_code}: {r.text[:200]}")

    async def set_alias(self, name: str, alias: str, version: str) -> None:
        await self._call("POST", "/api/2.0/mlflow/registered-models/alias",
                         body={"name": check_model_name(name), "alias": check_alias(alias), "version": str(version)})
