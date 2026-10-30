from typing import Dict, List

from app.connectors.base import Connector, ConnectorError
from app.connectors.http_api import HttpApiConnector
from app.connectors.postgres import PostgresConnector
from app.connectors.vector import VECTOR_CONNECTORS
from app.connectors.ml import MlEndpointConnector, MlflowConnector

_CONNECTORS: Dict[str, Connector] = {c.spec.type: c for c in (PostgresConnector(), HttpApiConnector(), *VECTOR_CONNECTORS, MlflowConnector(), MlEndpointConnector())}


def get_connector(type_: str) -> Connector:
    try:
        return _CONNECTORS[type_]
    except KeyError:
        raise ConnectorError(f"Unsupported connection type '{type_}'")


def list_specs() -> List[dict]:
    return [c.spec.model_dump() for c in _CONNECTORS.values()]
