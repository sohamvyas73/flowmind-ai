"""Encryption-at-rest for provider keys / node secrets, API-token hashing, and trace redaction."""
import base64
import copy
import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

SECRET_SENTINEL = "__secret__"
_ENC_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    material = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()))


def encrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if value.startswith(_ENC_PREFIX):
        return value
    return _ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: Optional[str]) -> Optional[str]:
    if not value or not value.startswith(_ENC_PREFIX):
        return value  # legacy plaintext row (re-encrypted by the startup migration)
    try:
        return _fernet().decrypt(value[len(_ENC_PREFIX):].encode()).decode()
    except InvalidToken:
        return None  # wrong SECRET_KEY / corrupted: treat as unset rather than leak ciphertext


class EncryptedString(TypeDecorator):
    """Transparent Fernet encryption for string columns."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)


# ── API tokens (stored hashed; plaintext shown once) ───────────────────────────

def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_prefix(token: str) -> str:
    return token[:8]


# ── Workflow node secrets ──────────────────────────────────────────────────────

_SECRET_FIELDS = {"apiKey", "authValue"}
_SECRET_HEADER_RE = re.compile(r"authorization|api[-_]?key|token|secret|password|cookie", re.I)


def _get(obj: Any, path: Tuple[Any, ...]) -> Any:
    for p in path:
        obj = obj[p]
    return obj


def _set(obj: Any, path: Tuple[Any, ...], value: Any) -> None:
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def _key(node: Dict[str, Any], i: int, path: Tuple[Any, ...]) -> str:
    return f"{node.get('id', i)}:{'.'.join(str(p) for p in path)}"


def extract_graph_secrets(graph: Dict[str, Any], existing: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Return (graph with secrets replaced by SECRET_SENTINEL, secrets map).

    A value that is already SECRET_SENTINEL keeps the previously stored secret.
    """
    existing = existing or {}
    clean = copy.deepcopy(graph)
    secrets: Dict[str, str] = {}
    nodes = clean.get("nodes", []) or []
    # sentinel values are strings too, so detect both fresh secrets and kept ones
    for i, node in enumerate(nodes):
        data = node.get("data") or {}
        for f in _SECRET_FIELDS:
            if isinstance(data.get(f), str) and data[f]:
                _stash(node, i, (f,), data, secrets, existing)
        for j, h in enumerate(data.get("headers") or []):
            if isinstance(h, dict) and isinstance(h.get("value"), str) and h["value"] \
                    and _SECRET_HEADER_RE.search(str(h.get("key", ""))):
                _stash(node, i, ("headers", j, "value"), data, secrets, existing)
    return clean, secrets


def _stash(node, i, path, data, secrets, existing) -> None:
    key = _key(node, i, path)
    val = _get(data, path)
    if val == SECRET_SENTINEL:
        if key in existing:
            secrets[key] = existing[key]
        else:
            _set(data, path, "")  # sentinel with nothing stored: treat as empty
        return
    secrets[key] = val
    _set(data, path, SECRET_SENTINEL)


def inject_graph_secrets(graph: Dict[str, Any], secrets: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """Return a deep copy of graph with sentinels replaced by stored secrets (for execution only)."""
    out = copy.deepcopy(graph)
    secrets = secrets or {}
    for i, node in enumerate(out.get("nodes", []) or []):
        data = node.get("data") or {}
        for f in _SECRET_FIELDS:
            if data.get(f) == SECRET_SENTINEL:
                data[f] = secrets.get(_key(node, i, (f,)), "")
        for j, h in enumerate(data.get("headers") or []):
            if isinstance(h, dict) and h.get("value") == SECRET_SENTINEL:
                h["value"] = secrets.get(_key(node, i, ("headers", j, "value")), "")
    return out


def dump_secrets(secrets: Dict[str, str]) -> Optional[str]:
    return encrypt(json.dumps(secrets)) if secrets else None


def load_secrets(blob: Optional[str]) -> Dict[str, str]:
    raw = decrypt(blob)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


# ── Redaction of persisted execution data ──────────────────────────────────────

_SENSITIVE_KEY_RE = re.compile(
    r"api[-_]?key|authorization|auth[-_]?value|secret|password|raw_response|"
    r"(^|[_-])token$|(access|auth|api|bearer|refresh)[-_]?token|"
    r"aadhaar|id_number|document_number|doc_number|pan_number",
    re.I,
)
REDACTED = "[REDACTED]"


def redact(value: Any, depth: int = 0) -> Any:
    """Deep-copy `value` masking secrets, KYC raw responses and identity-document numbers."""
    if depth > 12:
        return value
    if isinstance(value, dict):
        return {
            k: (
                REDACTED
                if isinstance(k, str) and _SENSITIVE_KEY_RE.search(k)
                and isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != ""
                else redact(v, depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value]
    return value
