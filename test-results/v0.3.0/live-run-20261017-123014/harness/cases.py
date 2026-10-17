"""Case recorder shared by the live campaign scripts.

Every executed check is one line in logs/cases.jsonl with a status, the method
that produced the evidence, and a pointer (log file + sequence number) to the
raw MCP exchange in logs/<session>.jsonl.

Statuses (never merged):
  PASS            executed against the real AutoCAD, result checked against an independent expectation
  FAIL            executed, expectation not met
  BLOCKED         cannot run in this environment (reason recorded)
  NOT_APPLICABLE  does not apply
  NOT_ATTEMPTED   not run (reason recorded)

Methods (what produced the evidence):
  real-MCP-stdio                  call went through the official MCP client to the real server process (COM backend)
  real-MCP-stdio+direct-COM       MCP call, plus an independent read-back straight from AutoCAD with pywin32
  real-MCP-stdio+file             MCP call, plus an independent check of the file on disk
  direct-COM                      pywin32 called directly (no MCP server in the loop)
  pytest                          the project's own live test file
  none                            nothing was executed

Adapted from run-20261017-121125/harness/cases.py (timeout pass-through added).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from pathlib import Path

import mcp_harness as h

CASES = h.LOGS / "cases.jsonl"
OBSERVATIONS = h.LOGS / "observations.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(**fields) -> dict:
    fields.setdefault("t", time.strftime("%Y-%m-%dT%H:%M:%S"))
    CASES.parent.mkdir(parents=True, exist_ok=True)
    with open(CASES, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields, ensure_ascii=False, default=str) + "\n")
    return fields


def observe(oid: str, tool: str | None, severity: str, text: str, evidence: str = "") -> None:
    """Record a finding that is not a pass/fail assertion (limitations, doc gaps, nitpicks)."""
    OBSERVATIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(OBSERVATIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": oid, "tool": tool, "severity": severity, "text": text,
                             "evidence": evidence[:800], "t": time.strftime("%Y-%m-%dT%H:%M:%S")},
                            ensure_ascii=False) + "\n")
    print(f"[OBSERVE:{severity}] {oid} {tool or ''}: {text}")


def load_cases() -> list[dict]:
    if not CASES.exists():
        return []
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


class Ctx:
    """Bundle of the live MCP session, its call log, and values passed between cases."""

    def __init__(self, session, log, session_name: str):
        self.session = session
        self.log = log
        self.session_name = session_name
        self.data: dict = {}


def must(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def close(a, b, tol=1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))


def pt_close(p, q, tol=1e-6) -> bool:
    return len(p) >= 2 and len(q) >= 2 and all(close(p[i], q[i], tol) for i in range(2))


def short(payload, n: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return text if len(text) <= n else text[:n] + "..."


async def tool(ctx: Ctx, name: str, args: dict | None = None, *, label: str = "", timeout: float | None = None) -> dict:
    """Plain logged MCP call (no PASS/FAIL recording); used for setup and read-back steps."""
    return await h.call(ctx.session, ctx.log, name, args or {}, label=label, timeout=timeout)


async def case(ctx: Ctx, cid: str, category: str, tool_name: str, args: dict, title: str, *,
               expect_error=None, check=None, notes: str = "", method: str = "real-MCP-stdio",
               timeout: float | None = None) -> dict:
    """Call `tool_name` through MCP and record PASS/FAIL.

    expect_error: None (call must succeed), a code string, a collection of
    codes, or "ANY" (any typed envelope with code/message/recommended_action).
    check(payload): raise AssertionError (via must) when the result is wrong.
    Returns the call outcome dict plus 'case_status'.
    """
    out = await h.call(ctx.session, ctx.log, tool_name, args, label=cid, timeout=timeout)
    own_seq = ctx.log.n  # the case's own exchange; its check may log further read-back calls
    problems: list[str] = []
    payload = out["payload"]
    code = h.error_code(out)
    if expect_error is not None:
        if not out["is_error"]:
            problems.append("expected an error result but the call succeeded")
        else:
            env = payload.get("error") if isinstance(payload, dict) else None
            if not isinstance(env, dict):
                problems.append(f"error result is not a typed envelope: {short(payload)}")
            else:
                missing = [k for k in ("code", "message", "recoverable", "recommended_action") if k not in env]
                if missing:
                    problems.append(f"error envelope missing {missing}")
                if expect_error != "ANY":
                    allowed = {expect_error} if isinstance(expect_error, str) else set(expect_error)
                    if code not in allowed:
                        problems.append(f"expected error code in {sorted(allowed)}, got {code!r}: "
                                        f"{env.get('message', '')[:160]}")
    else:
        if out["is_error"]:
            problems.append(f"call failed: {short(payload)}")
        elif not out["transport_ok"]:
            problems.append("transport failure")
    if not problems and check is not None:
        try:
            checked = check(payload)
            if inspect.isawaitable(checked):
                await checked
        except AssertionError as exc:
            problems.append(f"check failed: {exc}")
        except Exception as exc:  # a bug in the check itself must not be recorded as PASS
            problems.append(f"check raised {type(exc).__name__}: {exc}")
    status = "FAIL" if problems else "PASS"
    evidence = (f"error code {code}: {payload['error']['message'][:200]}" if expect_error is not None and not problems
                and isinstance(payload, dict) and "error" in payload else short(payload, 260))
    out["case_status"] = status
    record(id=cid, category=category, tool=tool_name, title=title, status=status, method=method,
           evidence=evidence, problems=problems, args=args, notes=notes,
           log_ref=f"{ctx.session_name}.jsonl#{own_seq}", ms=out["ms"])
    print(f"[{status}] {cid} {tool_name}: {title}" + ("" if not problems else f"\n       -> {'; '.join(problems)[:600]}"))
    return out


def lib_case(cid: str, category: str, area: str, title: str, fn, *, method: str = "direct-COM",
             tool_name: str | None = None, notes: str = "") -> bool:
    """Run fn() (raises AssertionError on failure, returns evidence text) and record it."""
    problems: list[str] = []
    evidence = ""
    try:
        evidence = str(fn() or "")
    except AssertionError as exc:
        problems.append(str(exc))
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    status = "FAIL" if problems else "PASS"
    record(id=cid, category=category, tool=tool_name, area=area, title=title, status=status, method=method,
           evidence=evidence[:800], problems=problems, notes=notes)
    print(f"[{status}] {cid} ({area}): {title}" + ("" if not problems else f"\n       -> {'; '.join(problems)[:600]}"))
    return status == "PASS"


async def acase(ctx: Ctx, cid: str, category: str, area: str, title: str, afn, *,
                method: str = "real-MCP-stdio+direct-COM", tool_name: str | None = None, notes: str = "") -> bool:
    """Like lib_case, for multi-step checks that need the live MCP session (several calls plus read-backs)."""
    problems: list[str] = []
    evidence = ""
    try:
        evidence = str(await afn() or "")
    except AssertionError as exc:
        problems.append(str(exc))
    except h.StopRun:
        raise
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    status = "FAIL" if problems else "PASS"
    record(id=cid, category=category, tool=tool_name, area=area, title=title, status=status, method=method,
           evidence=evidence[:800], problems=problems, notes=notes,
           log_ref=f"{ctx.session_name}.jsonl#{ctx.log.n}")
    print(f"[{status}] {cid} ({area}): {title}" + ("" if not problems else f"\n       -> {'; '.join(problems)[:600]}"))
    return status == "PASS"


def mark(cid: str, category: str, tool_name: str | None, title: str, status: str, reason: str, *,
         method: str = "none", notes: str = "") -> None:
    assert status in ("BLOCKED", "NOT_APPLICABLE", "NOT_ATTEMPTED"), status
    record(id=cid, category=category, tool=tool_name, title=title, status=status, method=method,
           evidence=reason, problems=[], notes=notes)
    print(f"[{status}] {cid} {tool_name or ''}: {title} -- {reason}")
