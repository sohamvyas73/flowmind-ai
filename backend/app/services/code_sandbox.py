"""Run Code Runner snippets in a separate, killable, resource-limited Python process.

This is defence in depth, NOT a full sandbox: the child has no inherited environment
(no DB URL / API keys), a throwaway working directory, CPU/memory/file/process limits,
and is hard-killed on timeout. It can still reach the network and the local filesystem
as the backend user, so keep ENABLE_CODE_NODE off unless the backend itself runs in an
isolated container/VM.
"""
import asyncio
import json
import os
import sys
import tempfile
from typing import Any, Dict

MAX_OUTPUT_BYTES = 1_000_000
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024

_RUNNER = r'''
import sys, json, re, math, datetime as dt
req = json.loads(sys.stdin.read())
safe_builtins = {
    "len": len, "range": range, "enumerate": enumerate, "list": list, "dict": dict,
    "str": str, "int": int, "float": float, "bool": bool, "set": set, "tuple": tuple,
    "sorted": sorted, "reversed": reversed, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "zip": zip, "map": map, "filter": filter,
    "any": any, "all": all, "print": print, "repr": repr, "isinstance": isinstance,
    "None": None, "True": True, "False": False,
}
g = {"__builtins__": safe_builtins, "json": json, "re": re, "math": math, "datetime": dt,
     "input_data": req["input"], "output": None}
try:
    exec(req["code"], g)
    out = json.dumps({"ok": True, "output": g.get("output")}, default=str)
except BaseException as e:
    out = json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})
sys.__stdout__.write("\n__FM_RESULT__" + out)
'''


def _limit_resources() -> None:  # runs in the child between fork and exec
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


class SandboxError(Exception):
    pass


async def run_code(code: str, input_data: Any, timeout_s: int) -> Any:
    """Execute `code` with `input_data`; return the value assigned to `output`."""
    try:
        payload = json.dumps({"code": code, "input": input_data}, default=str).encode()
    except (TypeError, ValueError) as e:
        raise SandboxError(f"Input is not JSON-serialisable: {e}")

    with tempfile.TemporaryDirectory(prefix="fm_code_") as cwd:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", "-c", _RUNNER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
            env={},
            preexec_fn=_limit_resources if os.name == "posix" else None,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(payload), timeout=timeout_s)
        except asyncio.TimeoutError:
            _kill(proc)
            await proc.wait()
            raise
        finally:
            if proc.returncode is None:
                _kill(proc)

    marker = b"\n__FM_RESULT__"
    idx = stdout.rfind(marker)
    if idx == -1:
        raise SandboxError("Code terminated without producing a result (memory/CPU limit or crash)")
    body = stdout[idx + len(marker):]
    if len(body) > MAX_OUTPUT_BYTES:
        raise SandboxError("Output too large")
    result: Dict[str, Any] = json.loads(body)
    if not result.get("ok"):
        raise SandboxError(result.get("error", "unknown error"))
    return result.get("output")


def _kill(proc: "asyncio.subprocess.Process") -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, 9)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
