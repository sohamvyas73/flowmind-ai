"""Hosted SQL engine: runs a single SELECT over tenant datasets in an isolated, killable DuckDB process.

Isolation (defence in depth — see docs/data-engineering-platform.md §12):
  * separate process, empty environment, throwaway working directory, hard timeout + process-group kill
  * CPU / file-size / open-file rlimits and a DuckDB memory limit
  * DuckDB external access is disabled *before* the user's SQL runs, so queries cannot read files, reach the
    network, attach databases, or install extensions; only SELECT is accepted
  * the parent decides which files are visible (tenant-owned only) and where the result is written
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings

_CHILD = os.path.join(os.path.dirname(__file__), "_child.py")
_MARK = b"\n__FM_RESULT__"
_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_slots = threading.Semaphore(max(settings.ENGINE_MAX_CONCURRENT, 1))


class EngineError(Exception):
    """A user-facing SQL / data error."""


@dataclass
class EngineInput:
    alias: str
    path: str
    format: str = "parquet"


@dataclass
class EngineResult:
    columns: List[Dict[str, str]]
    row_count: int
    sample: List[Dict[str, Any]]
    out_bytes: int
    scanned_rows: int
    scanned_bytes: int
    compute_s: float
    extra: Dict[str, Any] = field(default_factory=dict)


def qi(name: str) -> str:
    """Quote an SQL identifier."""
    return '"' + str(name).replace('"', '""') + '"'


def _limits() -> None:  # runs in the child between fork and exec
    import resource
    cpu = max(settings.ENGINE_TIMEOUT_S * 2, 10)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 ** 3, 4 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


def _kill(proc: "asyncio.subprocess.Process") -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, 9)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass


async def run_sql(
    inputs: List[EngineInput],
    sql: str,
    out_path: str,
    *,
    max_rows: Optional[int] = None,
    sample_rows: int = 100,
    timeout_s: Optional[int] = None,
) -> EngineResult:
    for i in inputs:
        if not _ALIAS_RE.match(i.alias):
            raise EngineError(f"Invalid table name '{i.alias}'")
    if len({i.alias.lower() for i in inputs}) != len(inputs):
        raise EngineError("Two inputs have the same table name")
    if not (sql or "").strip():
        raise EngineError("The SQL query is empty")

    timeout_s = timeout_s or settings.ENGINE_TIMEOUT_S
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    await asyncio.to_thread(_slots.acquire)
    try:
        with tempfile.TemporaryDirectory(prefix="fm_sql_") as tmp:
            payload = json.dumps({
                "inputs": [{"alias": i.alias, "path": i.path, "format": i.format} for i in inputs],
                "sql": sql,
                "out_path": out_path,
                "temp_dir": tmp,
                "memory_mb": settings.ENGINE_MEMORY_MB,
                "threads": 2,
                "max_rows": max_rows or settings.MAX_RESULT_ROWS,
                "sample_rows": sample_rows,
            }).encode()
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", _CHILD,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=tmp, env={}, preexec_fn=_limits if os.name == "posix" else None,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(payload), timeout=timeout_s)
            except asyncio.TimeoutError:
                _kill(proc)
                await proc.wait()
                _cleanup(out_path)
                raise EngineError(f"The query took longer than {timeout_s}s and was stopped. Try filtering or aggregating first.")
            except asyncio.CancelledError:
                _kill(proc)
                await proc.wait()
                _cleanup(out_path)
                raise
            finally:
                if proc.returncode is None:
                    _kill(proc)
    finally:
        _slots.release()

    idx = stdout.rfind(_MARK)
    if idx == -1:
        _cleanup(out_path)
        raise EngineError("The query was stopped (out of memory or time limit exceeded).")
    result = json.loads(stdout[idx + len(_MARK):])
    if not result.get("ok"):
        _cleanup(out_path)
        raise EngineError(_clean_error(result.get("error", "Query failed"), inputs))
    return EngineResult(
        columns=result["columns"], row_count=result["row_count"], sample=result["sample"],
        out_bytes=result["out_bytes"], scanned_rows=result["scanned_rows"],
        scanned_bytes=result["scanned_bytes"], compute_s=result["compute_s"],
    )


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _clean_error(msg: str, inputs: List[EngineInput]) -> str:
    """Make DuckDB errors readable and keep server paths out of user-visible messages."""
    for i in inputs:
        msg = msg.replace(i.path, i.alias)
    msg = re.sub(r"/[^\s'\"]*fm_[A-Za-z0-9_]+[^\s'\"]*", "<temp>", msg)
    first = msg.strip().splitlines()[0] if msg.strip() else "Query failed"
    return first[:400]
