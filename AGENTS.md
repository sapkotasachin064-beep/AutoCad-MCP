# AGENTS.md

Instructions for coding agents (Claude Code, Codex, OpenCode, ...) and humans
changing this repository. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the
workflow and [docs/architecture.md](docs/architecture.md) for the design.

## What this is

A local stdio MCP server (Python, MCP SDK 2.x) that drives AutoCAD 2021+ on
Windows over COM (`com` backend) or edits DXF files with ezdxf (`dxf`
backend). It is a drafting aid; it must never present output as code
compliance, structural design or a certified quantity survey.

## Layout

| Path | Contents |
|---|---|
| `src/server.py` | the 64 MCP tools, resources, prompts; `cad_tool` turns every failure into a JSON envelope and adds the state block |
| `src/backends/` | `base.py` (operation contract), `com.py` (live), `dxf.py` (headless), `targets.py` (plan emitters) |
| `src/tools/` | COM implementations used by `ComBackend` |
| `src/core/` | errors, COM executor, session (backend/pin/units/notices), registry, paths, evidence, reports, host detection |
| `src/domain/` | pure logic: units, plans, floor plans, grids, stairs, sheets, QC, takeoff, DXF diff -- **no pywin32, no ezdxf** |
| `src/cad_engine.py` | COM connection, active document choke point, units and pending-command handling |
| `src/db.py` | SQLite scan cache and the guarded read-only query |
| `tests/` | unit, fake-COM (`fakes.py`), golden, headless, stdio end-to-end, live (`test_integration_autocad.py`) |
| `scripts/` | generators for `docs/tools.md` and the capability catalog |
| `docs/analysis/` | reference-repository survey; historical, do not rewrite casually |

## Commands

```powershell
pip install -r requirements.txt -r requirements-dxf.txt pytest
python -m pytest tests -q                       # full suite; live tests skip without AutoCAD
python scripts\build_tool_docs.py               # regenerate docs/tools.md
python scripts\catalog\build_catalog.py         # regenerate the capability catalog
python scripts\build_tool_docs.py --check       # fail if stale (tests run these checks too)
python scripts\catalog\build_catalog.py --check
```

## Invariants -- do not break these

1. **No escape hatches.** No tool may execute raw AutoCAD commands, AutoLISP,
   Python, shell commands or arbitrary SQL writes. No network listener
   without authentication and loopback binding.
2. **Backend pinning.** The backend comes from `AUTOCAD_MCP_BACKEND` once per
   process. Never fall back from `com` to `dxf` (or back) silently.
3. **One COM thread.** Every COM call goes through `ComBackend._call`, which
   runs it on the executor thread with a timeout. Never touch COM objects
   from another thread or cache them across calls.
4. **Document choke point.** Get the drawing with
   `cad_engine.get_active_document(app, for_write=...)`. Writes pass
   `for_write=True` (pin check, pending-command cancel, units policy); reads
   pass `for_write=False` and must not change units or send keystrokes.
5. **Typed errors.** Raise `core.errors.CadError` subclasses with a code from
   `ERROR_CODES` and a `recommended_action`. Never return `{"ok": false}`,
   never swallow exceptions, never print to stdout (stdout is the MCP
   channel).
6. **Honest states.** Mutating tools report `executed` and `verified`;
   `verified` is true only after reading the result back. Nothing is
   `saved` until a save tool wrote the file and its SHA-256 was read back.
7. **Bounded output.** Anything that lists takes `limit` (and `offset` where
   useful) and reports `truncated` and totals.
8. **Files.** Use `core.paths.output_path` / `input_path`. Never overwrite
   without `overwrite=true`; never write outside the allowed folders.
9. **Units.** No hard-coded inches or millimetres; use `domain.units`
   (`unit_code`, `convert`, `defaults_for`). No national code values as
   defaults; limits are parameters with rule-of-thumb defaults labelled as
   such.
10. **Headless stays headless.** `server`, `backends.dxf` and `domain` must
    import without pywin32 (`test_headless_backend_imports_no_pywin32_code`).
11. **Compatibility.** Keep every V0.2.x tool name and required argument.
    Behaviour changes go in `CHANGELOG.md` and `docs/compatibility.md`.

## Adding or changing a tool

1. Pure logic first, in `src/domain/` with unit tests.
2. Add the operation name to `Backend.OPERATIONS` and implement it on the
   backends that can do it. A backend that cannot simply does not override
   it -- the base class refuses with `E_UNSUPPORTED_BACKEND`; add the reason
   to `UNSUPPORTED_REASONS`.
3. Register the tool in `src/server.py` with
   `@cad_tool(toolset=..., kind="read"|"session"|"write"|"destructive"|"external", title=..., operation=...)`.
   `kind` sets the MCP annotations; destructive tools need a dry run or an
   explicit flag.
4. Tests: fake-COM behaviour in `test_com_tools_fake.py`, a headless test in
   `test_dxf_backend.py` (if the dxf backend supports it), the tool name in
   `EXPECTED_V0_3_0_TOOLS` (`test_server_schema.py`), and a live test in
   `test_integration_autocad.py` (skipped without AutoCAD).
5. Regenerate `docs/tools.md`, and add or update catalog entries in
   `scripts/catalog/data_*.py` with the honest status, then regenerate.

## Evidence rules

* Status words mean exactly: `planned` (no code), `implemented` (code, no
  automated test), `tested` (automated tests: unit, mock_com, headless_dxf,
  stdio_e2e, golden_regression), `verified` (a live AutoCAD test asserts it;
  listed in `scripts/catalog/data_live.py` with evidence kind `live_autocad`,
  run output recorded in `docs/testing.md`). Never promote without evidence.
* Fake-COM tests prove what this code sends; they prove nothing about
  AutoCAD. Never describe them as live tests.
* Never skip, delete or loosen a failing test to get a green run; fix the
  cause or report it.
* Live tests use only scratch drawings they create and close. Never point
  tests or tools at a real project drawing.
* Do not launch AutoCAD, or run anything that changes a drawing a person has
  open, without the owner's go-ahead.

## Licensing

The repository has no licence yet (owner's decision). Do not copy code,
tests or docs from other repositories. Ideas may come from MIT/Apache-2.0
projects and are credited in the README and
[docs/analysis/reuse-and-licensing.md](docs/analysis/reuse-and-licensing.md);
nothing from GPL, AGPL, proprietary or unlicensed sources.

## Git

* Work on a branch; do not commit to `main` directly or rewrite history.
* Commit or push only when the owner asks.
* Never commit drawings from real projects, client configs with secrets,
  `.venv`, caches or output folders.
