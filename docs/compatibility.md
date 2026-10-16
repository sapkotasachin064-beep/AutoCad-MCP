# Compatibility

## AutoCAD

| Release | Internal | Status |
|---|---|---|
| AutoCAD 2020 and older | <= 23.1 | refused (`E_AUTOCAD_UNSUPPORTED_RELEASE`) |
| AutoCAD 2021 | 24.0 | accepted; not run in this project |
| AutoCAD 2022 | 24.1 | accepted; not run |
| AutoCAD 2023 | 24.2 | accepted; not run |
| AutoCAD 2024 | 24.3 | V0.2.x tools run against it by the original author; V0.3.0 tools not yet |
| AutoCAD 2025 | 25.0 | accepted; mapping from reference evidence; not run |
| AutoCAD 2026 | 25.1 | accepted; mapping from reference evidence; not run |
| AutoCAD 2027 | 26.0 | accepted; mapping from reference evidence; not run |
| AutoCAD LT (any) | -- | not supported (no COM automation) |
| Civil 3D, Map 3D, Plant 3D, Electrical | -- | run as AutoCAD (base COM API); vertical features not implemented |

V0.2.x mapped a non-existent release 24.4 to 2025 (defect D2, fixed).

## Python, packages, OS

| | Status |
|---|---|
| Python 3.14.7 | tested |
| Python 3.10-3.13 | declared (`requires-python >=3.10`), not run (no such interpreter on the dev machine). A static scan of `src/` found no 3.11+ syntax (PEP 701 f-strings, `except*`, type statements) or 3.11+ stdlib APIs, and mcp 2.3.0, ezdxf 1.4.4, pydantic and anyio all declare `>=3.10`. `test_packaging.py` skips on 3.10 (needs `tomllib`). |
| MCP Python SDK 2.3.0 | tested; `mcp>=2.3,<3` required (1.x lacks `mcp.server.mcpserver`) |
| pywin32 312 | tested |
| ezdxf 1.4.4 | tested (headless backend, compare/validate) |
| matplotlib | not installed on the dev machine; headless previews untested |
| Windows 11 | tested |
| Linux / macOS | headless backend designed to run (no pywin32 imports, enforced by a test), not tested |

## Clients

See [client-integrations.md](client-integrations.md): official MCP SDK client
tested end to end; Claude Code 2.1.300 and OpenCode 2.0.31 configuration
generated and parsed by the CLIs; Codex CLI and Claude Desktop documented only.

## Migration from V0.2.3

| Change | Effect | If you relied on the old behaviour |
|---|---|---|
| Error text is now a JSON envelope instead of "Error executing tool <name>" | clients see the reason and a code | parse `error.code` |
| Units preset applied only by tools that change a drawing, only when different, and reported | read-only tools no longer rewrite LUNITS/INSUNITS/MEASUREMENT | `AUTOCAD_MCP_UNITS=engineering` is still the default for drawing tools |
| ESC sent only when `CMDACTIVE` shows an active command, only for writes | idle users are not interrupted | none |
| `count_text_patterns`, `highlight_text_matches`, `execute_query` take `limit` (500/500/1000) and report `truncated` | bounded responses | pass a larger `limit` |
| `draw_wall.thickness` defaults to the standard wall for the drawing's units | 9.0 in inch drawings, as before; 230 in mm drawings | pass `thickness` |
| `generate_2d_floor_plan` draws in the drawing's units, adds `dry_run`, `drawing_unit`, `verified`, and `bounds_ft` when `units="FEET"` | identical entities in inch drawings (golden test) | none |
| `create_new_drawing` gains `pin`; refuses while another drawing is pinned | protects pinned jobs | unpin or pass `pin=true` |
| Template paths with folders must be existing `.dwt` files | early, clear errors | use a bare template name to let AutoCAD search its template path |
| 42 new tools (64 total), grouped into toolsets | longer tool list | `AUTOCAD_MCP_TOOLSETS` |
| `pyproject.toml`: version 0.3.0, `mcp>=2.3,<3`, setuptools build backend, `autocad-mcp` entry point, `dxf`/`render` extras | installs fail early on SDK 1.x | install into a fresh venv |

Rollback: everything is on branch `feat/v0.3.0-rebuild`; `main` still holds V0.2.3 (commit `3cf9254`).
