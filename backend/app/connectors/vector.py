"""Connection types for vector databases (Qdrant, Weaviate, Chroma). Retrieval Setup picks one of these."""
import time
from typing import Any, Dict, Iterable

from app.connectors.base import Connector, ConnectorSpec, FieldSpec, TestResult
from app.rag.stores import REST_STORES, StoreError


class VectorConnector(Connector):
    kind = ""

    def __init__(self, kind: str, label: str, description: str, default_url: str):
        self.kind = kind
        self.spec = ConnectorSpec(
            type=kind, label=label, description=description,
            fields=[
                FieldSpec(name="url", label="Server URL", help=f"e.g. {default_url}. Private/local hosts need admin allow-listing."),
                FieldSpec(name="api_key", label="API key / token", type="password", secret=True, required=False,
                          help="Leave empty for a local Docker server without auth."),
            ],
        )

    def store(self, config: Dict[str, Any], allow_hosts: Iterable[str]):
        return REST_STORES[self.kind](config["url"], config.get("api_key"), allow_hosts)

    async def test(self, config, *, access_mode, allow_hosts) -> TestResult:
        t0 = time.monotonic()
        try:
            h = await self.store(config, allow_hosts).health()
        except StoreError as e:
            return TestResult(False, str(e))
        return TestResult(bool(h["ok"]), h["message"], latency_ms=int((time.monotonic() - t0) * 1000),
                          details={"version": h.get("version")})


VECTOR_CONNECTORS = [
    VectorConnector("qdrant", "Qdrant", "Vector database for retrieval (RAG).", "http://localhost:6333"),
    VectorConnector("weaviate", "Weaviate", "Vector database for retrieval (RAG).", "http://localhost:8080"),
    VectorConnector("chroma", "Chroma", "Vector database for retrieval (RAG).", "http://localhost:8001"),
]
