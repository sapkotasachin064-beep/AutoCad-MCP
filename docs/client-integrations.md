# Client integrations

The server is a local stdio MCP server: every client starts it with the same
command -- the Python that has the packages installed, plus `src\server.py`.
Replace `C:\path\to\AutoCad-MCP` below with your clone, and use the venv's
`python.exe` if you made one ([installation.md](installation.md)).

## What was verified

| Client | Version checked | What was verified | Not verified |
|---|---|---|---|
| Any MCP client (official MCP Python SDK client) | mcp 2.3.0 | Full stdio session: initialize, list tools with annotations, call tools, error envelopes, on both backends (automated tests `test_e2e_mcp.py`, `test_workflow_headless_e2e.py`) | -- |
| Claude Code | 2.1.300 | `claude mcp add ... --scope project` generated the `.mcp.json` below and `claude mcp get` parsed it, in a scratch folder | A connected session: project-scoped servers need interactive approval, and user/local scope would have edited your real config |
| OpenCode | 2.0.31 | `opencode mcp add` generated the `opencode.json` below, in a scratch folder | `opencode mcp list` (it would also start the servers in your global config) |
| Codex CLI | -- (not installed) | Format taken from OpenAI's Codex MCP documentation | Everything |
| Claude Desktop | -- | Format from the MCP documentation | Everything (editing its config is your call) |

"Verified" never means a client drove a live AutoCAD in this project:
AutoCAD was not running during the V0.3.0 work.

## Claude Code

```powershell
claude mcp add autocad --scope user -e AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

* `--scope user`: available in every project; `--scope project` writes a
  shareable `.mcp.json` in the current folder (Claude Code asks you to approve
  it on first use); `--scope local` (default) is this project only, for you.
* Everything after `--` is the command and its arguments; quote paths with spaces.
* Check: `claude mcp list` or `claude mcp get autocad`; inside a session, `/mcp`.

The project file `claude mcp add --scope project` wrote (checked with 2.1.300):

```json
{
  "mcpServers": {
    "autocad": {
      "type": "stdio",
      "command": "C:\\path\\to\\AutoCad-MCP\\.venv\\Scripts\\python.exe",
      "args": ["C:/path/to/AutoCad-MCP/src/server.py"],
      "env": { "AUTOCAD_MCP_BACKEND": "com" }
    }
  }
}
```

## OpenCode

```powershell
opencode mcp add autocad --env AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

Without `--global` this writes the project's `opencode.json`; with `--global`
your user configuration. Check with `opencode mcp list`. What OpenCode 2.0.31
wrote:

```json
{
  "mcp": {
    "servers": {
      "autocad": {
        "type": "local",
        "command": [
          "C:\\path\\to\\AutoCad-MCP\\.venv\\Scripts\\python.exe",
          "C:/path/to/AutoCad-MCP/src/server.py"
        ],
        "environment": { "AUTOCAD_MCP_BACKEND": "com" }
      }
    }
  }
}
```

Older OpenCode documentation shows `"mcp": { "autocad": { ... } }` without the
`servers` level; prefer whatever your installed `opencode mcp add` writes.
`autocad_get_status` also reports a best-effort OpenCode detection flag
(environment markers only).

## Codex CLI (documented, not tested here)

```powershell
codex mcp add autocad --env AUTOCAD_MCP_BACKEND=com -- "C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe" "C:\path\to\AutoCad-MCP\src\server.py"
```

or in `~/.codex/config.toml` (project: `.codex/config.toml`, trusted projects only):

```toml
[mcp_servers.autocad]
command = 'C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe'
args = ['C:\path\to\AutoCad-MCP\src\server.py']
startup_timeout_sec = 30   # documented default 10; importing the MCP SDK took ~6 s on the dev machine
tool_timeout_sec = 300     # documented default 60; this server's COM calls may take 120 s, plots 300 s

[mcp_servers.autocad.env]
AUTOCAD_MCP_BACKEND = "com"
```

TOML single-quoted strings are literal, so Windows backslashes need no
escaping. Check with `codex mcp list`; inside the TUI, `/mcp`.

## Claude Desktop (documented, not tested here)

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "autocad": {
      "command": "C:\\path\\to\\AutoCad-MCP\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\AutoCad-MCP\\src\\server.py"],
      "env": { "AUTOCAD_MCP_BACKEND": "com" }
    }
  }
}
```

JSON needs doubled backslashes (or forward slashes). Restart Claude Desktop
after editing.

## Headless (no AutoCAD) configuration

Same command, `AUTOCAD_MCP_BACKEND=dxf`, with `ezdxf` installed. Use a second
server name (for example `autocad-dxf`) if you want both available; each
process is pinned to its backend.

## Smallest working check (any client)

1. Ask the client to call `autocad_get_status`. Expect JSON with `backend`.
   Live: `connected: true` once AutoCAD runs. Headless: `version` = ezdxf version.
2. Headless round trip: `autocad_create_new_drawing`, `autocad_draw_circle`
   (`center [0,0]`, `radius 5`), `autocad_save_drawing` (`path "check.dxf"`) --
   the file appears in the output folder and the result shows its SHA-256.

## Transport and security notes

* stdio only: the server opens no network port. The MCP SDK can serve
  streamable HTTP, but that is not wired up here because it would need
  authentication and loopback binding first (catalogued as planned).
* The client process runs the server with your user rights; AutoCAD automation
  acts on whatever drawings your AutoCAD session has open. Use
  `autocad_pin_document` for jobs on one drawing and
  `AUTOCAD_MCP_ALLOWED_DIRS` to confine file writes.
* Keep secrets out of committed client configs; this server needs none.
