from typing import Any, Dict, Iterable, List, Type

from app.warehouse.base import Warehouse, WarehouseError
from app.warehouse.clickhouse import ClickHouseWarehouse
from app.warehouse.postgres import PostgresWarehouse, RedshiftWarehouse
from app.warehouse.rest import BigQueryWarehouse, DatabricksWarehouse, SnowflakeWarehouse

WAREHOUSES: Dict[str, Type[Warehouse]] = {
    c.type: c for c in (PostgresWarehouse, RedshiftWarehouse, ClickHouseWarehouse, SnowflakeWarehouse, BigQueryWarehouse, DatabricksWarehouse)
}


def is_warehouse(connection_type: str) -> bool:
    return connection_type in WAREHOUSES


def open_warehouse(connection_type: str, config: Dict[str, Any], access_mode: str, allow_hosts: Iterable[str]) -> Warehouse:
    cls = WAREHOUSES.get(connection_type)
    if cls is None:
        raise WarehouseError(f"'{connection_type}' is not a warehouse connection")
    return cls(config, access_mode, allow_hosts)


def catalog() -> List[Dict[str, Any]]:
    return [{"type": c.type, "label": c.label, "dialect": c.dialect, "supports_insert": c.supports_insert} for c in WAREHOUSES.values()]
