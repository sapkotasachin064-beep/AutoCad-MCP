# AutoCAD MCP Server

MCP server that drives AutoCAD 2021+ over COM on Windows.

## V0.1.0 scope

Minimal end-to-end path only: check AutoCAD state, create a drawing, draw one line, save it.
No residential/drafting features yet.

## Requirements

- Windows, AutoCAD 2021 or newer installed
- Python 3.10+

```bash
pip install -r requirements.txt
```

## Run

```bash
python src/MCP/server.py
```

Runs over stdio, for use as an MCP server from a compatible client (e.g. OpenCode, Claude).

## Tools

- `autocad_get_status` - installed / running / connected / supported, plus a best-effort
  OpenCode session detection flag.
- `autocad_launch_application` - launches AutoCAD if not running, waits until it responds
  to COM calls (default timeout 60s).
- `autocad_create_test_drawing_with_line` - creates a new drawing, draws one line from
  `(0,0,0)` to `(100,100,0)`, saves it as `mcp_test_<timestamp>.dwg` under
  `AUTOCAD_MCP_OUTPUT_DIR` (default: `Documents/AutoCAD MCP Output`), and verifies the
  entity and the saved file both exist. Requires a connected AutoCAD; call
  `autocad_get_status` / `autocad_launch_application` first.

## Config

- `AUTOCAD_MCP_OUTPUT_DIR` - override the default output directory for test drawings.
