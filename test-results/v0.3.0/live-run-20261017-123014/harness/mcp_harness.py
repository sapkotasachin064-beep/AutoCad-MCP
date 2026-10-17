"""Test harness for the LIVE (COM backend) campaign.

Starts src/server.py as a real subprocess with AUTOCAD_MCP_BACKEND=com and talks
to it over stdio with the official MCP Python client (the same path OpenCode /
Claude Code use). Every call is appended to a JSONL log so reports can be
checked against raw evidence. This file lives in the test-results run folder,
not in src/. Pattern copied from run-20261017-121125/harness/mcp_harness.py,
with a per-call client-side timeout added (a stuck AutoCAD must stop the run,
not hang it).

REPO is the base checkout that holds the V0.3.0 code under test (read-only use);
RUN is the folder this file lives in.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(r"C:\Users\This PC\Desktop\Autocad Mcp Server")
SERVER = REPO / "src" / "server.py"
RUN = Path(__file__).resolve().parent.parent
WORKSPACE = RUN / "workspace"
LOGS = RUN / "logs"
EVIDENCE = RUN / "evidence"
OUTSIDE = RUN / "outside_sandbox"
SYSTEM_PYTHON = r"C:\Users\This PC\AppData\Local\Programs\Python\Python314\python.exe"
DEFAULT_CALL_TIMEOUT = 180.0
PRE_CALL_HOOK = None  # optional callable run right before every tool call (07b uses it to put the scratch drawing back in front)


class StopRun(RuntimeError):
    """Raised when an MCP call does not come back in time: AutoCAD may be stuck
    (modal dialog, busy). The scripts stop and report instead of waiting."""


class CallLog:
    def __init__(self, path: Path):
        self.path = path
        self.n = 0

    def write(self, record: dict) -> None:
        self.n += 1
        record = {"seq": self.n, "t": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def server_env(backend: str = "com", extra: dict | None = None) -> dict:
    env = {
        "AUTOCAD_MCP_BACKEND": backend,
        "AUTOCAD_MCP_OUTPUT_DIR": str(WORKSPACE),
        "AUTOCAD_MCP_ALLOWED_DIRS": str(WORKSPACE),
        "AUTOCAD_MCP_DB_PATH": str(WORKSPACE / "autocad_mcp_live.db"),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if extra:
        env.update(extra)
    return env


@contextlib.asynccontextmanager
async def open_session(log_name: str, *, command: str = SYSTEM_PYTHON, args: list[str] | None = None,
                       env: dict | None = None):
    """Yield (session, CallLog). Server stderr is sent to logs/<log_name>.stderr.txt."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = CallLog(LOGS / f"{log_name}.jsonl")
    params = StdioServerParameters(
        command=command,
        args=args if args is not None else [str(SERVER)],
        env=env if env is not None else server_env(),
    )
    with open(LOGS / f"{log_name}.stderr.txt", "w", encoding="utf-8") as errfile:
        async with stdio_client(params, errlog=errfile) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                try:
                    info = init.model_dump(by_alias=True, exclude_none=True)
                except Exception:  # pragma: no cover - defensive
                    info = {"repr": repr(init)}
                log.write({"kind": "initialize", "result": info})
                yield session, log


def _parse_result(result) -> tuple[object, bool]:
    """Return (payload, is_error). Payload is parsed JSON when the text is JSON."""
    is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
    texts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(text)
    raw = "\n".join(texts)
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    payload: object = raw
    if raw.strip().startswith(("{", "[")):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
    if structured is not None and payload == raw:
        payload = structured
    return payload, is_error


async def call(session: ClientSession, log: CallLog, tool: str, args: dict | None = None, *,
               label: str = "", timeout: float | None = None) -> dict:
    """Call a tool through the real MCP client and log the exchange."""
    args = args or {}
    limit = DEFAULT_CALL_TIMEOUT if timeout is None else timeout
    if PRE_CALL_HOOK is not None:
        PRE_CALL_HOOK()
    started = time.perf_counter()
    timed_out = False
    try:
        result = await asyncio.wait_for(session.call_tool(tool, args), timeout=limit)
        payload, is_error = _parse_result(result)
        outcome = {"transport_ok": True, "is_error": is_error, "payload": payload}
    except asyncio.TimeoutError:
        timed_out = True
        outcome = {"transport_ok": False, "is_error": True,
                   "payload": {"client_timeout_seconds": limit,
                               "note": "no answer from the server in time; AutoCAD may be busy or showing a dialog"}}
    except Exception as exc:  # protocol-level failure (schema rejection, closed pipe ...)
        outcome = {"transport_ok": False, "is_error": True, "payload": {"protocol_exception": repr(exc)}}
    outcome["ms"] = round((time.perf_counter() - started) * 1000, 1)
    outcome.update({"tool": tool, "args": args, "label": label})
    log.write({"kind": "call", **outcome})
    if timed_out:
        raise StopRun(f"{tool} did not answer within {limit}s (label {label!r}); stopping so AutoCAD can be inspected")
    return outcome


def error_code(outcome: dict) -> str | None:
    payload = outcome.get("payload")
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return err.get("code")
    return None


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
