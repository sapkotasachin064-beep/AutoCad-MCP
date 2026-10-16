"""True end-to-end test: spawns server.py as a real subprocess and talks to
it over stdio with the official MCP client, exactly as Claude Code/OpenCode
would. Does not require AutoCAD -- autocad_get_status is safe to invoke
whether or not AutoCAD is installed/running, and is enough to prove a real
client can discover and invoke tools through this server end to end.
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).resolve().parent.parent / "src" / "MCP" / "server.py"


async def _discover_and_call_status():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "autocad_get_status" in names
            assert "autocad_execute_query" in names
            assert len(names) == 18

            result = await session.call_tool("autocad_get_status", {})
            assert result.is_error is False
            return names, result


def test_real_mcp_client_discovers_and_invokes_tools():
    names, result = asyncio.run(_discover_and_call_status())
    assert len(names) == 18
    # autocad_get_status returns a plain dict, so the SDK sends it as a JSON
    # text content block rather than a structured-output block.
    payload = json.loads(result.content[0].text)
    assert "installed" in payload


async def _call_with_bad_args():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool("autocad_draw_circle", {"center": [0, 0], "radius": -1})


def test_real_mcp_client_sees_validation_error_as_tool_error():
    result = asyncio.run(_call_with_bad_args())
    assert result.is_error is True
