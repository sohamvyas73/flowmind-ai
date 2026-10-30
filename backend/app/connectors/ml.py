"""Connection types for Phase 5: an MLflow tracking server (registry) and a model-scoring endpoint."""
from typing import Any, Dict, Iterable

from app.connectors.base import Connector, ConnectorSpec, FieldSpec, TestResult
from app.ml import endpoints
from app.ml.mlflow_client import MlflowClient, MlflowError


def mlflow_client(config: Dict[str, Any], allow_hosts: Iterable[str]) -> MlflowClient:
    return MlflowClient(config["url"], token=config.get("token"), username=config.get("username"),
                        password=config.get("password"), allow_hosts=allow_hosts)


class MlflowConnector(Connector):
    spec = ConnectorSpec(
        type="mlflow", label="MLflow",
        description="An MLflow tracking server and model registry. Used to look up models and promote versions.",
        fields=[
            FieldSpec(name="url", label="Tracking server URL", help="e.g. http://localhost:5000. Private/local hosts need admin allow-listing."),
            FieldSpec(name="token", label="Bearer token", type="password", secret=True, required=False),
            FieldSpec(name="username", label="Username (basic auth)", required=False),
            FieldSpec(name="password", label="Password (basic auth)", type="password", secret=True, required=False),
        ],
    )

    async def test(self, config, *, access_mode, allow_hosts) -> TestResult:
        try:
            h = await mlflow_client(config, allow_hosts).health()
        except MlflowError as e:
            return TestResult(False, str(e))
        extra = "" if access_mode == "read_write" else " (read-only: promotion is disabled)"
        return TestResult(h["ok"], h["message"] + (extra if h["ok"] else ""))


class MlEndpointConnector(Connector):
    spec = ConnectorSpec(
        type="ml_endpoint", label="Model endpoint",
        description="A model-scoring HTTP endpoint (for example `mlflow models serve`). Rows are sent to it as JSON.",
        fields=[
            FieldSpec(name="url", label="Scoring URL", help="e.g. http://localhost:5001/invocations"),
            FieldSpec(name="input_format", label="Request format", type="select", default="mlflow_records",
                      options=endpoints.INPUT_FORMATS,
                      help="mlflow_records = {dataframe_records: […]}, mlflow_split = {dataframe_split: …}, records = {records: […]}"),
            FieldSpec(name="auth_type", label="Auth", type="select", default="bearer", options=["bearer", "header"], required=False),
            FieldSpec(name="header_name", label="Header name", required=False, default="X-API-Key"),
            FieldSpec(name="token", label="Token / key", type="password", secret=True, required=False),
            FieldSpec(name="health_path", label="Health-check path", required=False, default="/ping",
                      help="GET on the same host to test the connection."),
        ],
    )

    async def test(self, config, *, access_mode, allow_hosts) -> TestResult:
        h = await endpoints.endpoint_health(config, allow_hosts)
        return TestResult(h["ok"], h["message"], latency_ms=h.get("latency_ms"))
