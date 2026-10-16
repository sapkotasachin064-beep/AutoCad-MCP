# Testing

```powershell
pip install -r requirements.txt -r requirements-dxf.txt pytest
python -m pytest tests -q
```

The suite never needs a production drawing and never starts AutoCAD. Tests
that need a running AutoCAD are **skipped**, with the reason, when it is not
running -- they are never replaced by mocks and reported as live.

## Layers

| Layer | Files | What it proves | Needs |
|---|---|---|---|
| Unit: validation, geometry, units, errors, paths, registry, packaging, catalog | `test_geometry.py`, `test_validation_boundaries.py`, `test_errors.py`, `test_paths.py`, `test_registry.py`, `test_packaging.py`, `test_catalog.py`, `test_docs.py`, `test_db.py`, `test_identity.py`, `test_connection.py`, `test_server_schema.py`, `test_server_surface.py` | inputs are validated before any COM call; error envelopes; path policy; registry/annotations; generated docs and catalog are current | nothing |
| COM executor | `test_com_executor.py` | single thread, serialisation, timeout -> worker replacement, queued call cancelled with nothing sent | nothing (plain callables) |
| Units / pinning at the document choke point | `test_units_and_pinning.py` | read-only tools never change units or send keys; presets applied only when different; pin refusals happen before anything is touched | nothing (recorded fakes) |
| Fake-COM behaviour | `test_com_tools_fake.py` (with `fakes.py`) | call sequences, read-back verification and result shapes of every V0.3.0 COM tool | nothing |
| Golden regression | `test_floor_plan_parity.py` (with `golden/`) | the V0.3.0 plan engine draws the V0.2.3 floor plan entity-for-entity (golden made by running the original code from git `3cf9254`) | nothing |
| Pure domain logic | `test_domain_workflows.py` | room plans, grids, stairs, sheets, QC rules, takeoff, comparison | nothing |
| Headless integration | `test_dxf_backend.py`, `test_workflow_headless_e2e.py` | real DXF files written to temp folders and re-read with ezdxf; a full residential workflow through the public tool functions | ezdxf |
| MCP end-to-end | `test_e2e_mcp.py`, `test_workflow_headless_e2e.py::test_real_stdio_session_on_the_headless_backend` | a real stdio session with the official MCP client: discovery, annotations, calls, error envelopes, on both backends | nothing / ezdxf |
| Live AutoCAD | `test_integration_autocad.py` (11 V0.2.x + 8 V0.3.0 tests) | real COM round trips | a running AutoCAD 2021+ |

Fake-COM tests prove what this code sends and checks; they say nothing about
AutoCAD's behaviour. A capability counts as live-verified only when a live
test asserts it (`scripts/catalog/data_live.py`).

## Results recorded for V0.3.0 (2026-10-16, Windows 11, Python 3.14.7, mcp 2.3.0, ezdxf 1.4.4)

| Run | Command | Result |
|---|---|---|
| Baseline before any change (`main` @ 3cf9254) | `python -m pytest tests -q` | 85 passed, 11 skipped (live AutoCAD not running), exit 0 |
| V0.3.0 | `python -m pytest tests -q` | 263 passed, 19 skipped (live AutoCAD not running), exit 0 |
| V0.3.0 after live fixes, AutoCAD running | `python -m pytest tests -q` | 283 passed (see [live results](#live-autocad-results)) |
| Packaging (scratch copy, scratch venv with `--system-site-packages`) | `pip install --no-deps -e .`, `pip wheel --no-deps .`, then the installed `autocad-mcp.exe` driven over stdio by the MCP client with `AUTOCAD_MCP_BACKEND=dxf` | install and wheel build succeeded (pip fetched `setuptools>=69` into its isolated build environment); wheel holds `backends`, `core`, `domain`, `tools`, `utils` and the four top-level modules; server reported `autocad-mcp 0.3.0`, 64 tools; new drawing, circle and save-as DXF succeeded and the file was on disk |

Not run: any test on Python 3.10-3.13, any test on another OS, AutoCAD
releases other than 2024, Codex CLI and Claude Desktop integrations.

## Live AutoCAD results

2026-10-16, AutoCAD 2024 (`24.3s (LMS Tech)`, release 2024) on Windows 11,
launched with the owner's approval through `cad_engine.launch_and_wait()`
(`connected=True, supported=True`). Every test used its own scratch drawing;
afterwards only AutoCAD's startup `Drawing1.dwg` was open.

| Run | Command | Result |
|---|---|---|
| 1 | `python -m pytest tests	est_integration_autocad.py -v` | 15 passed, 1 failed, 3 errors |
| 2 (after fixes) | same | 19 passed in 46.6 s |
| 3 | same, `-q` | 19 passed in 49.5 s |
| Full suite, AutoCAD running | `python -m pytest tests -q` | 283 passed in 61.5 s |

Run 1 findings, both fixed and covered:

* 3 errors in the `fresh_drawing` fixture:
  `pywintypes.com_error: (-2147418111, 'Call was rejected by callee.')` from
  `doc.Name` / `doc.FullName` read right after `Documents.Add` without the
  busy retry (`tools/primitives.py`, `cad_engine.get_drawing_identity`).
* `test_v030_export_and_plot_live`: the PDF was written and verified, but
  `layout_settings_restored` was false. A live probe showed the cause: a
  fresh model layout reports `CanonicalMediaName == ''`, and writing `''`
  back fails with AutoCAD's "Invalid input". Empty media is now left at the
  device default and reported; new fake test
  `test_plot_leaves_empty_media_at_device_default`.

Live facts recorded by the passing tests: `AddHatch` with pattern type 1
reads back `ANSI31`; aligned/linear dimension measurements match geometry;
the units preset chosen with `set_drawing_units` survives later drawing
calls; save-as gives a path identity; `generate_2d_floor_plan` still draws
50 entities. Not covered live: open/activate drawing, layer property
changes, stair, sheet and takeoff tools, the timeout path.

## Running the live tests

1. Start AutoCAD 2021+ (or: `python -c "import sys; sys.path.insert(0,'src'); import cad_engine; print(cad_engine.launch_and_wait())"`).
2. `python -m pytest tests\test_integration_autocad.py -v`

Each test creates its own unsaved scratch drawing and closes it without saving;
files go to pytest's temporary folder. The V0.3.0 tests cover documents and
units, inspection, editing, annotation (including whether the hatch pattern
type constant reads back correctly), blocks, DXF export and PDF plotting,
save-as/close and the generators. Promote catalog entries to `verified` only
with the recorded output of such a run.

## Regenerating generated artefacts

```powershell
python scripts\catalog\build_catalog.py      # docs/catalog/capabilities.json + docs/feature-catalog.md
python scripts\build_tool_docs.py            # docs/tools.md
python tests\golden\make_floor_plan_golden.py   # only if V0.2.3 output must be re-captured
```

`test_catalog.py` and `test_docs.py` fail when the generated files are stale.

## Licensing check

`docs/analysis/reuse-and-licensing.md` records a line-overlap check between
`src/` and every reference repository: 6 of 814 lines at the baseline, at
most 16 of 3,889 after V0.3.0, all idioms, formulas or API facts, and zero
with reciprocal, proprietary-xstaar or unlicensed sources. Re-run it after
large changes.
