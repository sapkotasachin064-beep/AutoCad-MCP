"""Best-effort OpenCode host detection.

OpenCode exposes no documented API for an MCP server to confirm it is
running inside an active OpenCode session. This checks environment
variables OpenCode is known to set for child processes; absence does not
prove OpenCode is absent, only that it was not detected. This module never
starts an OpenCode process itself.
"""

import os

_ENV_MARKERS = ("OPENCODE_SESSION_ID", "OPENCODE_SESSION", "OPENCODE")


def detect() -> dict:
    found = [name for name in _ENV_MARKERS if os.environ.get(name)]
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
