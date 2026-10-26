"""Object storage for uploads and materialised datasets.

Local disk today; the interface is the seam for S3/GCS later (same keys, same semantics).
Keys are always tenant-prefixed (``tenants/<user_id>/...``) and are validated so a key can never
escape the storage root.
"""
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional

from app.core.config import settings

_SAFE_PART = re.compile(r"^[A-Za-z0-9._-]+$")


class StorageError(Exception):
    pass


class Storage(ABC):
    @abstractmethod
    def path_for(self, key: str) -> str:
        """Absolute local path for `key` (engines read files directly from disk)."""

    @abstractmethod
    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int) -> int: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


def tenant_key(user_id, *parts: str) -> str:
    """Build ``tenants/<user_id>/<parts…>``; every part must be a plain file-name-like token."""
    for p in parts:
        if not _SAFE_PART.match(p) or p in (".", ".."):
            raise StorageError(f"Unsafe storage path component: {p!r}")
    return "/".join(["tenants", str(user_id), *parts])


class LocalStorage(Storage):
    def __init__(self, root: Optional[str] = None):
        self._root = Path(root or settings.DATA_DIR).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, key: str) -> str:
        p = (self._root / key).resolve()
        if self._root != p and self._root not in p.parents:
            raise StorageError("Storage key escapes the storage root")
        return str(p)

    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int) -> int:
        path = Path(self.path_for(key))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        written = 0
        try:
            with open(tmp, "wb") as out:
                while chunk := stream.read(1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise StorageError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
                    out.write(chunk)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return written

    def delete(self, key: str) -> None:
        p = Path(self.path_for(key))
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

    def size(self, key: str) -> int:
        try:
            return os.path.getsize(self.path_for(key))
        except OSError:
            return 0

    def exists(self, key: str) -> bool:
        return os.path.exists(self.path_for(key))


storage: Storage = LocalStorage()
