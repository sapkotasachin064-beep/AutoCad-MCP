"""AutoCAD MCP server, V0.1.0 foundation milestone.

Tools:
  autocad_get_status              - installed/running/connected/supported check
  autocad_launch_application      - launch AutoCAD and wait until ready
  autocad_create_test_drawing_with_line - new drawing, one line (0,0,0)-(100,100,0), saved
"""

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer

from autocad import connection, opencode
from autocad.drawing import create_test_drawing_with_line

server = MCPServer(name="autocad-mcp")


@server.tool()
def autocad_get_status() -> dict:
    """Report whether AutoCAD 2021+ is installed, running, and reachable over COM,
    and whether this process appears to be running inside an OpenCode session."""
    status = dataclasses.asdict(connection.get_status())
    status["opencode"] = opencode.detect()
    return status


@server.tool()
def autocad_launch_application(timeout_seconds: float = 60) -> dict:
    """Launch AutoCAD if not already running, and wait until it answers COM calls.
    Does nothing destructive if AutoCAD is already running; just verifies it."""
    return dataclasses.asdict(connection.launch_and_wait(timeout=timeout_seconds))


@server.tool()
def autocad_create_test_drawing_with_line(output_dir: str | None = None) -> dict:
    """Create a new drawing, draw one line from (0,0,0) to (100,100,0), save it as
    mcp_test_<timestamp>.dwg under output_dir (default: Documents/AutoCAD MCP Output),
    and verify the entity and file exist. Requires AutoCAD to already be connected;
    call autocad_get_status / autocad_launch_application first."""
    return create_test_drawing_with_line(output_dir=output_dir)


if __name__ == "__main__":
    server.run("stdio")
