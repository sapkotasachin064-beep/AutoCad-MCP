"""Best-effort detection of the MCP host process (pure; no COM).

OpenCode exposes no documented API for an MCP server to confirm it is
running inside an active OpenCode session. This checks environment
variables OpenCode is known to set for child processes; absence does not
prove OpenCode is absent, only that it was not detected. This never starts
an OpenCode process itself. (Moved here from cad_engine in V0.3.0 so the
headless backend does not import COM code; cad_engine re-exports it.)
"""

import os

_OPENCODE_ENV_MARKERS = ("OPENCODE_SESSION_ID", "OPENCODE_SESSION", "OPENCODE")


def detect_opencode() -> dict:
    found = [name for name in _OPENCODE_ENV_MARKERS if os.environ.get(name)]
    if found:
        return {
            "detected": True,
            "confidence": "heuristic",
            "message": f"OpenCode session markers present: {', '.join(found)}.",
        }
    return {
        "detected": False,
        "confidence": "heuristic",
        "message": "No OpenCode session markers found in environment. This does not "
        "confirm OpenCode is unavailable, only that no known marker was detected.",
    }
