# Rebuild plan: V0.2.3 -> V0.3.0

Inputs: [`gap-analysis.md`](gap-analysis.md),
[`architecture-comparison.md`](architecture-comparison.md),
[`reuse-and-licensing.md`](reuse-and-licensing.md). Work happens on branch
`feat/v0.3.0-rebuild`; `main` is untouched and nothing is committed or pushed
without the owner's approval.

## Principles

1. **Evolve, don't replace.** The flat `src/` layout, the COM engine, the
   SQLite scan cache and every existing tool name stay. Existing tool argument
   schemas only gain optional parameters.
2. **Honest states.** A mutation result says separately whether it was
   accepted, passed preflight, executed, was verified by read-back, and was
   saved. Nothing is reported as verified unless it was read back.
3. **No silent switching.** The backend is chosen once, at startup, by
   `AUTOCAD_MCP_BACKEND` (`com` default, or `dxf`). A document can be pinned;
   a pinned tool call refuses to run against a different drawing.
4. **Safe by default.** Read-only tools never modify a drawing. Deletion is
   dry-run unless asked. Saving refuses to overwrite unless asked. Output paths
   are validated. There is no raw command / LISP execution tool.
5. **Testable without AutoCAD.** Engineering logic is pure Python; COM code is
   tested against recorded fakes; the headless backend gives real file-level
   integration tests. Live-AutoCAD tests stay separate and are reported as
   skipped when AutoCAD is not running.

## Target layout

```
src/
  server.py              MCP surface only: tools, resources, prompts
  cad_engine.py          COM connection, identity, units policy, pin check (existing, extended)
  db.py                  SQLite scan cache (unchanged)
  core/
    errors.py            CadError hierarchy, stable codes, client envelope
    com_executor.py      one dedicated COM thread, per-call timeout, worker replacement
    session.py           backend choice, document pin, per-call notices
    registry.py          tool metadata, toolsets, annotations, capability map
    paths.py             output-path policy
    evidence.py          file evidence (size, SHA-256), bounded-output helpers
  backends/
    base.py              Backend: every operation refuses (E_UNSUPPORTED_BACKEND) unless overridden
    com.py               live AutoCAD: runs tools/* on the COM thread
    dxf.py               headless: one ezdxf document held by the server
    targets.py           DrawingTarget adapters: COM document, ezdxf layout, recorder (tests)
  domain/                pure engineering logic, no COM and no ezdxf
    units.py  floorplan.py  grids.py  stairs.py  sheets.py  qc.py  takeoff.py  diff.py
  tools/                 live COM implementations (existing modules + documents, query,
                         annotation, blocks, output)
  utils/                 geometry validation, constants (existing)
```

The capability map is derived from code, not maintained by hand: an operation
is "supported" by a backend exactly when that backend overrides the
operation's method. A test fails if a registered tool names an operation no
backend implements.

## Phases and acceptance criteria

| Phase | Work | Done when |
|---|---|---|
| 0 | Discovery, inventory, analysis docs | `docs/analysis/*` written; baseline suite recorded (85 passed, 11 skipped) |
| 1 Foundation | `core/errors.py` + boundary wrapper (D1); COM executor with timeout (D6); release table (D2); packaging (D3); units policy + pending-command check (D4, D5); document pin; registry, toolsets, annotations; bounded outputs (D7); docstrings (D8) | An e2e test proves a client sees `E_INVALID_INPUT` with the message; executor timeout test passes; all baseline tests still pass (updated only where behaviour intentionally changed, each change listed in CHANGELOG) |
| 2 Live capabilities | documents (list/open read-only/save-as/close/activate/pin), query (summary, list with filters + pagination, entity detail, layers), editing (delete dry-run, scale, mirror, offset, array, properties), annotation (arc, MTEXT, dimensions, hatch), blocks (list, insert with attributes, read/update attributes), output (DXF export without renaming, PDF plot with verification, evidence hashes) | Each tool has validation tests (no COM reached on bad input) and fake-COM behaviour tests; reported as *mock-tested, not live-verified* until a live run |
| 3 Headless backend | `backends/dxf.py`: new/open/save, primitives, layers, query, editing subset, scan + text search, audit, export, optional PNG preview | Integration tests write real DXF files to temp dirs and read them back with ezdxf |
| 4 Residential / civil | unit-aware plan engine on `DrawingTarget`; legacy 2x3 generator ported (same output under default units) with dry-run + count verification; floor plan from explicit rooms with areas, schedules, overall dimensions; structural grid; stair calculator + plan; sheet border + title block; QC; quantity takeoff; DXF compare | Pure-logic unit tests + headless end-to-end tests producing DXF files whose contents are asserted |
| 5 Catalog | `docs/catalog/capabilities.json` (stable IDs, status, backend, safety, tests) + generated `docs/feature-catalog.md`; test validating schema, uniqueness, and that every *implemented* entry maps to a registered tool or internal function | Catalog test passes; counts reported by status |
| 6 Clients | verify `claude mcp add` / OpenCode config on this machine; document Codex CLI and Claude Desktop from official docs (marked untested) | `docs/client-integrations.md` distinguishes verified from documented |
| 7 Docs + report | README rewrite, `docs/*.md`, AGENTS.md, CHANGELOG, CONTRIBUTING, SECURITY; final regression run; final report | Every command in the README was run, or is labelled as not run |

## Compatibility and migration (V0.2.3 -> V0.3.0)

| Change | Impact | Migration |
|---|---|---|
| Errors now arrive as `ToolError` text containing a JSON envelope | Clients previously saw only `Error executing tool <name>`; now they see the reason | none needed |
| Units are applied only by mutating tools, only when they differ, and reported | Read-only tools no longer change unit variables | Set `AUTOCAD_MCP_UNITS=preserve` to never touch units; default `engineering` keeps V0.2.3's preset for drawing tools |
| ESC is sent only when `CMDACTIVE` shows an active command | Fewer cancelled user commands | none |
| `count_text_patterns`, `highlight_text_matches`, `execute_query` gain `limit` (defaults 500 / 500 / 1000) and report `truncated` | Very large result sets are cut | pass a larger `limit`, or narrow the query |
| `draw_wall.thickness` default becomes "standard for the drawing's units" (9 in for inches, 230 mm for millimetres) | Identical in inch drawings (V0.2.3 default units) | pass `thickness` explicitly to keep any other value |
| `generate_2d_floor_plan` converts feet to the drawing's insertion units instead of assuming inches | Identical under the default `engineering` units; correct in metric drawings | none |
| Tool count grows from 22; toolsets allow trimming | Clients see more tools | `AUTOCAD_MCP_TOOLSETS=core,...` |
| `pyproject.toml` requires `mcp>=2.3,<3` | Installing on mcp 1.x now fails at install time instead of at import | install into a fresh venv |

Rollback path: the baseline is commit `3cf9254` on `main`; this work lives on
`feat/v0.3.0-rebuild` and can be discarded or reverted as a unit.

## Test strategy

| Layer | Runs where | Notes |
|---|---|---|
| Unit: geometry, units, plan engines, QC, takeoff, diff, paths, errors, registry, catalog | everywhere | pure Python |
| Validation boundaries: bad input never reaches COM | everywhere | `get_connected_app` patched to fail if called |
| Fake-COM behaviour tests | everywhere | recorded fakes of `Document`/`ModelSpace`/entities; prove call sequences, not AutoCAD behaviour |
| COM executor: timeout, worker replacement, error propagation | everywhere | uses plain Python callables |
| Headless integration (ezdxf) | everywhere with `ezdxf` | real DXF files in `tmp_path`, read back |
| MCP schema + e2e over stdio | everywhere | official `mcp` client SDK, subprocess |
| Live AutoCAD | Windows + running AutoCAD 2021+ | skipped otherwise, reported as skipped -- never substituted by mocks |
