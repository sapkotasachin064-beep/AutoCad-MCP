# Installation and configuration

## Requirements

| | Live backend (`com`) | Headless backend (`dxf`) |
|---|---|---|
| OS | Windows 10/11 | Windows (tested); any OS should work but is untested |
| Python | 3.10+ (developed and tested on 3.14.7) | same |
| CAD | AutoCAD 2021 or newer, full version (not LT) | none |
| Python packages | `mcp>=2.3,<3`, `pywin32` | `mcp`, `ezdxf>=1.3` |

## Install (Windows, PowerShell)

A virtual environment keeps the server's top-level modules (`server`,
`tools`, `core`, ...) away from other projects.

```powershell
cd "C:\path\to\AutoCad-MCP"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
# optional: headless DXF backend, DXF compare/validate tools
pip install -r requirements-dxf.txt
# optional: headless PNG/PDF previews
pip install matplotlib
```

or, with the same effect, `pip install -e ".[dxf]"` (`.[render]` adds
matplotlib, `.[dev]` adds pytest). After `pip install -e .` the console
command `autocad-mcp` starts the server.

## Start the server

```powershell
python src\server.py
```

The server speaks MCP over stdio: it waits for a client on stdin and logs to
stderr. You normally do not start it yourself -- the MCP client does, using
the command in its configuration ([client-integrations.md](client-integrations.md)).
Use the absolute path of the Python that has the packages installed (for a
venv: `C:\path\to\AutoCad-MCP\.venv\Scripts\python.exe`).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `AUTOCAD_MCP_BACKEND` | `com` | `com` (live AutoCAD) or `dxf` (headless). Fixed for the process; no `auto`. |
| `AUTOCAD_MCP_UNITS` | `engineering` | Units preset applied by tools that change a drawing: `engineering`, `architectural`, `metric_mm`, `metric_m`, `preserve` (never change units). |
| `AUTOCAD_MCP_COM_TIMEOUT` | `120` | Seconds a live COM call may take (`0` = no limit). Plots get at least 300 s. |
| `AUTOCAD_MCP_TOOLSETS` | `all` | Comma list of toolsets to advertise: `core` (always on), `drawing`, `layers`, `editing`, `query`, `annotation`, `blocks`, `architecture`, `analysis`, `output`. |
| `AUTOCAD_MCP_OUTPUT_DIR` | `%USERPROFILE%\Documents\AutoCAD MCP Output` | Where relative output paths resolve; created on demand. |
| `AUTOCAD_MCP_DB_PATH` | `<output dir>\autocad_mcp.db` | SQLite cache of entity scans. |
| `AUTOCAD_MCP_ALLOWED_DIRS` | (unset) | If set (`;`-separated), every file path a tool reads or writes (drawings, templates, DXF, PDF, reports, previews) must be inside one of these folders. The scan cache (`AUTOCAD_MCP_DB_PATH`) is configured by you and not checked. |

An invalid value fails the call (or the server start, for `AUTOCAD_MCP_TOOLSETS`)
with `E_INVALID_CONFIG` naming the variable; nothing falls back silently.

## Verify the installation

```powershell
python -m pytest tests -q
```

Expected on a machine without a running AutoCAD: all tests pass except the
live-AutoCAD ones, which are reported as skipped. See [testing.md](testing.md).

## Live AutoCAD check

1. Start AutoCAD yourself (or call `autocad_launch_application` from a client).
2. From a client, call `autocad_get_status`: `connected: true, supported: true`
   and the release year mean the COM path works.
3. Optionally run the live tests (they create and close their own scratch
   drawings, and write only to a temporary folder):

   ```powershell
   python -m pytest tests\test_integration_autocad.py -v
   ```
