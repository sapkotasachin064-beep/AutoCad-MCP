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

SERVER_PATH = Path(__file__).resolve().parent.parent / "src" / "server.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_server_schema import ALL_EXPECTED_TOOLS, LEGACY_TOOLS  # noqa: E402


async def _with_session(callback, env=None):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await callback(session)


async def _discover_and_call_status(session):
    tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    result = await session.call_tool("autocad_get_status", {})
    return names, tools, result


def test_real_mcp_client_discovers_and_invokes_tools():
    names, tools, result = asyncio.run(_with_session(_discover_and_call_status))
    assert names == ALL_EXPECTED_TOOLS
    assert LEGACY_TOOLS <= names
    assert result.is_error is False
    # autocad_get_status returns a plain dict, so the SDK sends it as a JSON
    # text content block rather than a structured-output block.
    payload = json.loads(result.content[0].text)
    assert "installed" in payload
    assert payload["backend"] == "com"


def test_real_mcp_client_sees_tool_annotations():
    names, tools, _ = asyncio.run(_with_session(_discover_and_call_status))
    by_name = {t.name: t for t in tools.tools}
    status = by_name["autocad_get_status"].annotations
    assert status.read_only_hint is True and status.destructive_hint is False
    draw = by_name["autocad_draw_line"].annotations
    assert draw.read_only_hint is False


async def _call_with_bad_args(session):
    return await session.call_tool("autocad_draw_circle", {"center": [0, 0], "radius": -1})


def test_real_mcp_client_sees_validation_error_as_tool_error():
    result = asyncio.run(_with_session(_call_with_bad_args))
    assert result.is_error is True


def test_real_mcp_client_receives_the_error_code_and_message():
    # Defect D1 (docs/analysis/gap-analysis.md): before V0.3.0 the client saw only
    # "Error executing tool autocad_draw_circle" -- the SDK withholds the text of any
    # exception that is not a ToolError. The envelope must now arrive intact.
    result = asyncio.run(_with_session(_call_with_bad_args))
    envelope = json.loads(result.content[0].text)
    assert envelope["ok"] is False
    assert envelope["tool"] == "autocad_draw_circle"
    assert envelope["error"]["code"] == "E_INVALID_INPUT"
    assert "radius" in envelope["error"]["message"]
    assert envelope["error"]["recoverable"] is False
    assert envelope["error"]["recommended_action"]


async def _query_rejected(session):
    return await session.call_tool("autocad_execute_query", {"query": "DELETE FROM entities"})


def test_real_mcp_client_receives_query_rejection_code():
    result = asyncio.run(_with_session(_query_rejected))
    envelope = json.loads(result.content[0].text)
    assert envelope["error"]["code"] == "E_QUERY_REJECTED"
