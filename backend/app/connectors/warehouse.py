"""Connection types for cloud / analytical warehouses. Postgres keeps its own connector (it is also a warehouse target)."""
from typing import Any, Dict, Iterable, List

from app.connectors.base import Connector, ConnectorError, ConnectorSpec, FieldSpec, TestResult
from app.data.dataset import Column, DatasetLocation, DatasetRef, LineageEdge, build_dataset
from app.warehouse.base import WarehouseError, table_ref
from app.warehouse.registry import open_warehouse

_WRITE_SCHEMA = FieldSpec(name="write_schema", label="Only allow writing to this schema", required=False,
                          help="Optional guard-rail: Save to warehouse refuses any other schema (e.g. a dedicated 'flowmind' schema).")
_SSL = FieldSpec(name="sslmode", label="SSL mode", type="select", default="require",
                 options=["disable", "prefer", "require", "verify-full"], help="'require' or stronger is recommended.")

SPECS: Dict[str, ConnectorSpec] = {
    "redshift": ConnectorSpec(
        type="redshift", label="Amazon Redshift", supports_discover=True, supports_preview=True,
        description="An Amazon Redshift cluster or serverless workgroup (PostgreSQL protocol). Read-only by default.",
        fields=[FieldSpec(name="host", label="Host", help="e.g. my-cluster.abc123.eu-west-1.redshift.amazonaws.com"),
                FieldSpec(name="port", label="Port", type="number", default=5439),
                FieldSpec(name="database", label="Database"), FieldSpec(name="user", label="User"),
                FieldSpec(name="password", label="Password", type="password", secret=True, required=False), _SSL]),
    "clickhouse": ConnectorSpec(
        type="clickhouse", label="ClickHouse", supports_discover=True, supports_preview=True,
        description="A ClickHouse server over its HTTP interface (port 8123, or 8443 for TLS). Read-only by default.",
        fields=[FieldSpec(name="url", label="HTTP URL", help="e.g. http://localhost:8123 — private hosts need admin allow-listing"),
                FieldSpec(name="user", label="User", default="default"), FieldSpec(name="password", label="Password", type="password", secret=True, required=False),
                FieldSpec(name="database", label="Database", default="default")]),
    "snowflake": ConnectorSpec(
        type="snowflake", label="Snowflake", supports_discover=True, supports_preview=True,
        description="A Snowflake account through the SQL API, using an OAuth or programmatic access token.",
        fields=[FieldSpec(name="account", label="Account", help="e.g. xy12345.eu-west-1 (the part before .snowflakecomputing.com)"),
                FieldSpec(name="token", label="Access token", type="password", secret=True),
                FieldSpec(name="token_type", label="Token type", type="select", default="OAUTH", options=["OAUTH", "PROGRAMMATIC_ACCESS_TOKEN"]),
                FieldSpec(name="warehouse", label="Warehouse", required=False), FieldSpec(name="database", label="Database", required=False),
                FieldSpec(name="schema", label="Schema", required=False, default="PUBLIC"), FieldSpec(name="role", label="Role", required=False)]),
    "bigquery": ConnectorSpec(
        type="bigquery", label="Google BigQuery", supports_discover=True, supports_preview=True,
        description="A BigQuery project, using a service account key or an access token.",
        fields=[FieldSpec(name="project", label="Project ID"), FieldSpec(name="dataset", label="Default dataset", required=False),
                FieldSpec(name="location", label="Location", required=False, help="e.g. EU or US"),
                FieldSpec(name="service_account_json", label="Service account key (JSON)", type="password", secret=True, required=False),
                FieldSpec(name="access_token", label="Or an access token", type="password", secret=True, required=False),
                FieldSpec(name="api_base", label="API endpoint (advanced)", required=False, help="Leave empty for Google's public endpoint.")]),
    "databricks": ConnectorSpec(
        type="databricks", label="Databricks SQL", supports_discover=True, supports_preview=True,
        description="A Databricks SQL warehouse, using a personal access token.",
        fields=[FieldSpec(name="host", label="Workspace host", help="e.g. dbc-1234abcd-ef56.cloud.databricks.com"),
                FieldSpec(name="warehouse_id", label="SQL warehouse ID"),
                FieldSpec(name="token", label="Access token", type="password", secret=True),
                FieldSpec(name="catalog", label="Catalog", required=False), FieldSpec(name="schema", label="Schema", required=False)]),
}


for _spec in SPECS.values():
    _spec.fields.append(_WRITE_SCHEMA)


class WarehouseConnector(Connector):
    def __init__(self, kind: str):
        self.kind = kind
        self.spec = SPECS[kind]

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        clean = super().validate_config(config)
        if self.kind == "bigquery" and not (clean.get("service_account_json") or clean.get("access_token")):
            raise ConnectorError("Give a service account key or an access token")
        return clean

    def _wh(self, config, access_mode, allow_hosts):
        return open_warehouse(self.kind, config, access_mode, allow_hosts)

    async def test(self, config, *, access_mode, allow_hosts) -> TestResult:
        try:
            r = await self._wh(config, access_mode, allow_hosts).test()
        except WarehouseError as e:
            return TestResult(False, str(e))
        return TestResult(r["ok"], r["message"], latency_ms=r.get("latency_ms"))

    async def discover(self, config, *, access_mode, allow_hosts) -> Dict[str, Any]:
        try:
            tables = await self._wh(config, access_mode, allow_hosts).tables()
        except WarehouseError as e:
            raise ConnectorError(str(e))
        return {"tables": tables, "truncated": len(tables) >= 500}

    async def preview(self, config, *, access_mode, allow_hosts, connection_id, schema, table, limit) -> DatasetRef:
        wh = self._wh(config, access_mode, allow_hosts)
        try:
            ref = table_ref(wh.dialect, *([schema] if schema else []), table)
            res = await wh.sample(f"SELECT * FROM {ref}", limit)
        except WarehouseError as e:
            raise ConnectorError(str(e))
        names = [c["name"] for c in res.columns]
        return build_dataset(
            [Column(name=c["name"], type=c["type"]) for c in res.columns], [dict(zip(names, r)) for r in res.rows],
            kind="table", location=DatasetLocation(connection_id=connection_id, schema_name=schema, table=table, target="pushdown"),
            row_count=None, lineage=[LineageEdge(source=f"connection:{connection_id}/{schema}.{table}", operation="read")], sample_limit=limit)


WAREHOUSE_CONNECTORS: List[Connector] = [WarehouseConnector(k) for k in SPECS]
