# Audit report: current repository (All-in-One CAD MCP, Phase 1)

Audit only. No source file was changed while producing this report. No AutoCAD
was launched. No drawing file was modified. Nothing was committed.

Scope: the whole repository at commit `9b0ebe4` (`main`, tree clean when the
audit began, `main == origin/main`, no tags), plus a fresh read of three
reference repositories ([`02-reference-feature-matrix.md`](02-reference-feature-matrix.md)).
The working tree changed during the audit; see the note at the end of §1.

Evidence standard used throughout this report:

| Word | Means |
|---|---|
| **run** | executed during this audit; command and result are stated |
| **read** | the implementing code was read, with `path:line` |
| **claimed** | stated in the repository's own docs, not re-verified here |

---

## 1. Repository state and baseline

| Item | Value | How |
|---|---|---|
| Version | `0.3.0` (`src/version.py:4`) | read |
| Branch | `main` only; `origin/main` == `main`, no uncommitted changes at audit start, no tags | run (`git status`, `git log origin/main..main`) |
| History | 14 commits, `edca17c` (initial) .. `9b0ebe4`; V0.3.0 landed in `3343e7c`, live-run fixes in `c591f7a`/`5cda7bc` | run |
| Python | 3.14.7 on Windows 11 | run |
| Installed deps | `mcp 2.3.0`, `mcp-types 2.3.0`, `pydantic 2.14.1`, `pywin32 312`, `ezdxf 1.4.4`, `pytest 9.1.1`; also present: `pillow 12.3.0`, `openpyxl 3.1.5`, `numpy 2.5.4`; `matplotlib` absent | run (`pip list`) |
| **Baseline test run** | **`272 passed, 19 skipped in 29.13s`** (`python -m pytest tests -q`) | run |
| Tests collected | 291 (`pytest --collect-only -q`) | run |
| Skipped tests | the 19 live-AutoCAD tests; AutoCAD was not running | run |
| Generated artefacts | `docs/tools.md`, `docs/catalog/capabilities.json`, `docs/feature-catalog.md` — freshness enforced by `tests/test_docs.py`, `tests/test_catalog.py` (green in the baseline run) | run |

This is the regression baseline. Any later milestone must reproduce
`272 passed, 19 skipped` (with AutoCAD absent) or better, plus its own new
tests.

### Note: the working tree changed during this audit (not my change)

A **concurrent workstream** edited the repository while this audit was being
written. The audit itself changed no source file; these edits are someone
else's in-flight work and were left untouched. All numbers, line counts and
"clean tree" statements in this report refer to commit `9b0ebe4` only.

Observed at the end of the audit (`git status`, `git diff --stat`,
file timestamps; the tree may keep moving after this note):

* 19 modified tracked files and 3 new untracked source files
  (`src/domain/civil.py` 19,622 bytes, 14:52; `src/tools/civil.py` 19,446
  bytes, 14:54; `tests/test_domain_civil.py` 8,119 bytes, 14:51 on
  2026-10-17); diffstat 954 insertions, 105 deletions.
* The change adds a `civil` toolset (6 tools: alignment station/offset,
  point at station/offset, ground profile, cut/fill volumes, pipe clearance,
  place points) plus matching COM/DXF backend operations, registry entry,
  tests and regenerated catalog/docs — the first instalment of the
  discipline-module plan (catalog categories Y/Z), evidently following
  `AGENTS.md`'s "adding a tool" procedure.
* `src/backends/dxf.py` (1,609 lines), `src/server.py` (1,254 lines) and the
  capability catalog (650 entries) no longer match the audited snapshot
  (1,369 / 1,136 / 647).
* Suite run on this mid-edit tree: **`304 passed, 19 errors in 116.12s`**
  (2026-10-17). The 19 errors are all in `tests/test_integration_autocad.py`,
  which errored in setup instead of skipping — its import-time availability
  guard did not skip on this tree, and AutoCAD was not running. No AutoCAD
  process existed before or after the run (`Get-Process acad` empty). This
  result is an **observation of an unfinished tree, not a regression verdict**
  on either the baseline or the other workstream.

Consequence for every later phase: re-run the baseline on the merged,
committed tree before starting M0, and treat `9b0ebe4` as the contract
reference, not the working tree.

### Documentation drift found during the audit (claims vs reality)

| # | Finding | Evidence |
|---|---|---|
| A1 | README says "Tests: 283" and `docs/testing.md` records "283 passed" for a full run with AutoCAD; the suite now collects **291** tests. The README number is stale by two commits (8 tests). | `README.md:21`, `docs/testing.md:36`, run above |
| A2 | `docs/compatibility.md:54` still says "everything is on branch `feat/v0.3.0-rebuild`; `main` still holds V0.2.3". `main` holds V0.3.0 and the branch is merged. | read, `git log` |
| A3 | `docs/analysis/rebuild-plan.md:6,86` describes `main` as untouched at `3cf9254`. Historical analysis doc; correct for its period, misleading if read as current. | read |

None of these is a code defect; all three are user-visible documentation
inaccuracies and are cheap to fix in the first implementation milestone.

---

## 2. Architecture as built (verified by reading the code)

```
MCP client --stdio--> src/server.py        64 tools, resources, prompts, @cad_tool boundary
                          |
                     src/backends/         base.py (contract) | com.py | dxf.py | targets.py
                          |
      com path: src/tools/* over one COM thread (core/com_executor.py)
      dxf path: src/backends/dxf.py, one in-memory ezdxf document
                          |
                     src/domain/            pure logic (units, plans, grids, stairs, sheets, qc, takeoff, diff)
                     src/core/              errors, session/pin, registry, paths, evidence, reports, hosts
                     src/utils/             geometry + validation + constants
                     src/db.py              SQLite scan cache (read-only query guard)
                     src/cad_engine.py      COM connect/launch/identity/units policy
```

Code scale (lines, excluding `__pycache__`):

| Area | Lines | Files |
|---|---|---|
| `src/server.py` | 1,136 | 1 |
| `src/backends/` | 1,973 | 4 (`dxf.py` alone 1,369) |
| `src/tools/` (COM implementations) | 2,874 | 12 |
| `src/domain/` (pure) | 1,594 | 9 |
| `src/core/` | 951 | 8 |
| `src/cad_engine.py` + `src/db.py` | 689 | 2 |
| `src/utils/` | 323 | 3 |
| `tests/` | 3,635 | 25 `.py` files (incl. `fakes.py`) + `golden/floor_plan_v0_2_3.json` |
| `scripts/` (catalog generators + tool docs) | 1,241 | 7 |

### 2.1 MCP surface (verified by running the registry, not by reading docs)

`import server; capability_map()` **run**, output:

| Dimension | Value |
|---|---|
| Tools | **64** |
| Toolsets | `core` 13, `editing` 12, `drawing` 7, `architecture` 7, `query` 6, `analysis` 5, `layers` 4, `output` 4, `blocks` 4, `annotation` 2 |
| Kinds (annotations) | `write` 35, `read` 18, `external` 6, `destructive` 3, `session` 2 |
| Backend-independent tools | 57 served by both backends |
| COM-only tools | 6: `autocad_create_test_drawing_with_line`, `autocad_highlight_entity`, `autocad_highlight_text_matches`, `autocad_launch_application`, `autocad_plot_pdf`, `autocad_query_and_highlight` |
| DXF-only tools | 1: `autocad_render_preview` |
| Backend operations | 52 on `com`, 47 on `dxf`; DXF-only operation `render_preview` |

All values from `capability_map()` at `9b0ebe4`. The concurrent work noted in
§1 adds a `civil` toolset, so the working tree lists more.

Capability discovery is **derived from code**
(`core/registry.py:94-129`): a backend supports an operation exactly when the
class overrides it, so the advertised map cannot drift from the
implementation. A registered tool naming an unimplemented operation is a test
failure (`tests/test_registry.py:30`).

### 2.2 The `@cad_tool` boundary — the property to protect

`server.py` decorates every tool with `@cad_tool(toolset=, kind=, title=, operation=)`.
It gives, in one place:

1. a `ToolSpec` in `core/registry.py` (source of `autocad_get_capabilities`, the
   `autocad://capabilities` resource and the generated `docs/tools.md`);
2. MCP `ToolAnnotations` derived from `kind` (`registry.py:31-59`);
3. a `state` block on mutations: `accepted / preflight_passed / executed /
   verified / saved`, with `verified` copied from the tool's own read-back and
   `saved` false until a save tool wrote the file and read its SHA-256 back
   (`core/evidence.py`);
4. a JSON error envelope with a stable code, `recoverable` and
   `recommended_action` (`core/errors.py:20-50`), delivered as `ToolError` text
   so MCP SDK 2.x cannot replace the message with `Error executing tool <name>`;
5. toolset filtering (`AUTOCAD_MCP_TOOLSETS`).

This boundary is what makes a *modular* server possible without touching 64
call sites: new backends and new modules plug in below it.

### 2.3 Backend contract and the plan/emit seam

`backends/base.py` declares `Backend.OPERATIONS` (52 names) and installs a
refusal method for each; a backend implements an operation by overriding the
method, otherwise the caller gets `E_UNSUPPORTED_BACKEND` with a declared
reason. There is no `{"ok": false}` default (`base.py:1-9,47-63`).

Generators do not draw. `domain/*` planners return a `Plan` (layers + ordered
tagged primitives); `backends/targets.emit(plan, target)` draws it into a
`ComTarget`, a `DxfTarget` or a `RecordingTarget` and raises
`E_VERIFICATION_FAILED` unless model space grew by exactly the number of
primitives (`targets.py:201-216`). This is the project's only engine-independent
"document sink" abstraction, and it is the natural extension point for a third
engine (see the architecture deliverable).

### 2.4 Units, identity, pinning, units safety

* Units policy: presets `engineering|architectural|metric_mm|metric_m|preserve`
  (`domain/units.py:22-29`); applied **only** by mutating tools, only when a
  variable differs, reported as a `units_changed` notice. Read-only tools never
  send keystrokes or change variables (`cad_engine.get_active_document`,
  `tests/test_units_and_pinning.py`).
* Drawing identity: `path:<full path, lower-case>` for saved drawings,
  `unsaved:<name>` otherwise (`cad_engine.get_drawing_identity`).
* Pinning: `autocad_pin_document` refuses any tool call against a different
  active drawing with `E_DOCUMENT_CHANGED` before anything is touched.
* `E_UNITS_MISMATCH` is raised instead of guessing when a drawing's INSUNITS
  has no fixed length (`units.py:80-89`).

### 2.5 Read-only analysis pipeline

`snapshot_entities` (both backends) produces one normalised list of entity
dicts; `domain/qc.py`, `domain/takeoff.py`, `domain/diff.py` are pure functions
of that list. Checks, quantities and comparisons therefore behave identically
live and headless — a genuinely reusable verification service, and the seam the
"verification" roadmap item extends.

### 2.6 Safety controls present

| Control | Where |
|---|---|
| Path policy: no `..`, no UNC/`\\?\`/device paths, no Windows/Program Files, optional allow-list `AUTOCAD_MCP_ALLOWED_DIRS`, relative paths inside `AUTOCAD_MCP_OUTPUT_DIR`, overwrite only with `overwrite=true` | `core/paths.py` |
| Write-then-replace for exports/saves; size + SHA-256 read back from disk | `core/evidence.py`, `tools/output.py` |
| Delete and generators support `dry_run` | `server.py`, catalog |
| Close refuses unsaved changes without `discard_changes=true` | `tools/documents.py` |
| No raw command / AutoLISP / code-execution tool (enforced by a test) | `tests/test_catalog.py:58` |
| stdio only, no network listener | `server.py` |
| Bounded outputs (`limit` + `truncated` + totals) | `core/evidence.py`, every listing tool |
| Read-only SQL over the scan cache, two layers: keyword/shape check plus a `mode=ro` connection | `db.py:156-225` |

---

## 3. What works, by evidence level

Counts below come from `docs/catalog/capabilities.json` (647 entries) and were
re-read during this audit; **verified** = a live AutoCAD test asserted it,
**tested** = automated test only, **implemented** = code without a dedicated
test, **planned** = no code.

| Status | Entries | Note |
|---|---|---|
| verified (live AutoCAD 2024) | 62 | recorded 2026-10-16, `docs/testing.md` |
| tested | 160 | unit, fake-COM, headless-DXF, stdio e2e, golden |
| implemented (no dedicated test) | 26 | listed in §4.3 |
| planned | 399 | roadmap input |

### 3.1 Working and well covered

Core session safety (COM thread + timeout, pinning, typed errors, capability
map); document lifecycle (new/open read-only/save-as/close/list/activate/units);
primitives (line, 3D polyline, rectangle, circle, arc, TEXT, MTEXT); editing
(move, rotate, copy, scale, mirror, offset, rectangular array, delete with dry
run, property set, highlight); layers (list, create, ensure, properties with
linetype load); annotation (aligned/linear dimension with measured read-back,
hatch with pattern read-back); blocks (list, insert with attributes, read/update
attributes); inspection (drawing summary, filtered paginated entity list,
entity detail, SQLite scan + read-only SQL, text search); generators (room-based
floor plan, legacy 2×3 golden plan, structural grid, stair design + plan, sheet
frame + title block); analysis (QC checks, quantity takeoff, DXF file
validation, DXF revision compare, JSON/CSV/MD reports); output (DXF export with
document-identity check, PDF plot with on-disk `%PDF` + MediaBox check, headless
PNG/PDF/SVG preview).

### 3.2 Working but weak in evidence (honest statement)

* 19 live tests pass on AutoCAD 2024 only. **Not live-verified:** open/activate
  drawing, layer property changes, stair tools, sheet tool, takeoff, the COM
  timeout path (`docs/testing.md:73-74`).
* 26 catalog entries have code but no dedicated test (§4.3).
* The fake-COM layer proves call sequences and this project's own checks; it
  proves nothing about AutoCAD. The repository states this itself
  (`tests/fakes.py:1-8`, `tests/test_com_tools_fake.py:1-7`) — keep that
  distinction in every later claim.

### 3.3 Headless DXF: real, but narrower than the live backend

47 of 52 operations are implemented. Explicit refusals with reasons (not
failures, not silent no-ops): DWG read/write, PDF plotting, highlighting,
launching AutoCAD, offset of bulged polylines/splines/ellipses, hatch
boundaries other than one closed straight-sided polyline or a circle
(`docs/backends.md:33-46`). One document at a time, serialised by a lock.

---

## 4. Gaps, technical debt and regression risk

### 4.1 Capability gaps that matter for "All-in-One" (verified absent)

| Gap | Evidence | Consequence |
|---|---|---|
| **No screenshot / image capture of the live drawing.** Only `autocad_render_preview`, DXF-backend-only, and it needs matplotlib (not installed). | `capability_map` run: `render_preview` is DXF-only; `ComBackend.UNSUPPORTED_REASONS` names it; grep for screenshot verbs finds nothing in `src/` | A live user cannot get visual feedback; verification is numeric only |
| **No batch / multi-step call.** Every mutating call is one tool call; 50 entities = 50 undo steps. | catalog `AG` (8 entries: 1 tested, 1 verified, 6 planned) | Long workflows are slow and un-undoable as a unit |
| **No undo group / transaction tool.** | catalog `P` (2 verified, 2 tested, 1 implemented, 5 planned); `docs/architecture.md:168-169` | A generated plan cannot be rolled back with one action |
| **No DWG read/write without AutoCAD.** | `docs/backends.md:14` | Offline DWG work is impossible; ODA File Converter is an external dependency not present |
| **No 3D solid / STEP capability.** 3D is "1 tested, 15 planned". | catalog category `N`; no kernel dependency in `requirements*.txt` | STEP inspection is a new capability class, not an extension |
| **No multi-CAD adapter.** `PROG_ID = "AutoCAD.Application"` is a module constant; `PROCESS_NAME = "acad.exe"`. | `cad_engine.py:29-30`; `docs/backends.md:55` lists BricsCAD/ZWCAD/GstarCAD as planned | Only AutoCAD can be driven today |
| **Discipline modules: architecture and residential only.** Civil 3D (`Y`, 20 entries) and survey (`Z`, 15) are `planned` in full; plumbing (`AA`, 11), electrical (`AB`, 11), HVAC (`AC`, 9) and P&ID (`AD`, 9) likewise. Structural (`X`) has 4 built entries (1 verified, 3 tested, through shared grid/drafting work) and 13 planned; architecture (`V`: 10 tested, 20 planned) and residential (`W`: 2 verified, 7 tested, 1 implemented, 10 planned) are the built modules. | catalog category counts (re-read) | The server is already general-CAD plus residential architecture; the other disciplines are catalogued, not built |
| **No discipline separation in the tool order.** `architecture` is a toolset, but there is no notion of "general CAD" vs "discipline module" beyond it. | `core/registry.py:18-29` | Roadmap item (§Phase 3 architecture) |
| **No layouts/viewports creation.** `list_layouts` only; 12 of 14 `L` entries planned. | catalog `L` | Sheet sets cannot be produced beyond one title block |
| **No xrefs, no selection sets as a first-class concept** (selection sets exist internally for export only). | catalog `J` (20 planned), `O` | Filtering is by re-listing entities, not by saved selection |

### 4.2 Technical debt (read, with evidence)

| # | Debt | Evidence | Risk |
|---|---|---|---|
| T1 | `src/backends/dxf.py` is a 1,369-line module implementing 47 operations in one class. Contract parity with `com` is maintained **by hand**: two implementations, same arguments, same result keys. | `dxf.py` size; `com.py:1-8` documents the split | Adding a third backend triples hand-maintained parity; drift is silent until a client hits it |
| T2 | `PROG_ID`/`PROCESS_NAME`/release table are module constants; `cad_engine` is imported by `tools/*` directly. Generalising to another ActiveX CAD means editing the tool layer, not adding a module. | `cad_engine.py:29-32`, `tools/*` imports | Multi-CAD is a refactor, not a plugin |
| T3 | `core/errors.py:122-132` maps pre-V0.3.0 `RuntimeError` messages to codes by **substring match** on English text. It is a compatibility shim. | read | New code that raises `RuntimeError` with new wording silently becomes `E_COM_ERROR`; the shim should shrink, not grow |
| T4 | `src/server.py` (1,136 lines) mixes transport wiring, tool bodies, prompts and resources. Tool bodies are thin, but 64 tools × validation inline is a large surface for one file. | `server.py` size | Merge conflicts; harder to split by module later |
| T5 | Two COM helper styles coexist: `tools/_common.py` (V0.3.0) and per-module private helpers kept "unchanged" from V0.2.x (`_common.py:1-7`). | read | Two idioms for the same idea; new code must pick one |
| T6 | Legends of legacy: `autocad_create_test_drawing_with_line` (V0.1.0 smoke tool) is the only COM-only `external` tool with no equivalent headless path. | capability map run; catalog `D-009` | Dead weight in the public surface; removing it is a compatibility break (needs owner decision) |
| T7 | Display/`notices` are collected via a session context variable (`core/session.collect`), i.e. implicit ambient state on the COM thread. | `backends/com.py:54-65` | Works, but new backends must remember to collect notices the same way |
| T8 | Prompts and resources are defined inside `server.py`; registry covers tools only. | `server.py` | Capability discovery cannot describe prompts/resources; minor |
| T9 | Live tests are the only proof of AutoCAD behaviour and there are 19 of them, covering 62 catalog entries; several COM tools are fake-tested only. | `docs/testing.md`, catalog `data_live.py` | A regression in unverified COM code ships undetected |
| T10 | `requirements.txt` / `requirements-dxf.txt` split vs `pyproject.toml` extras — two dependency declarations to keep in step. | read both | Drift risk (already experienced as defect D3 in V0.3.0) |

### 4.3 The 26 `implemented`-without-test entries (incomplete evidence)

Read from `docs/catalog/capabilities.json` during this audit. Categories: A 1,
B 2, D 5, E 1, G 1, I 1, P 1, Q 3, T 3, U 1, W 1, AL 1, AM 5.

| ID | Exposed by | Capability |
|---|---|---|
| A-005 | – | Usage rules in the MCP initialize result |
| B-006 | – | Retry `RPC_E_CALL_REJECTED` with jittered backoff |
| B-007 | – | Retry transient dynamic-dispatch `AttributeError` |
| D-003 | `autocad_get_status` | Tell "not running" from "running but not answering COM" |
| D-005 | `autocad_launch_application` | Make a launched AutoCAD window visible |
| D-006 | `autocad_launch_application` | Bound launch waiting with an executor deadline |
| D-008 | `autocad_get_status` | Heuristic detection of an OpenCode host session |
| D-009 | `autocad_create_test_drawing_with_line` | V0.1.0 smoke test: new drawing + one line, saved and checked |
| E-002 | `autocad_create_new_drawing` | Drawing from a `.dwt` (live) or `.dxf` (headless) template |
| G-016 | `autocad_query_and_highlight` | Highlight entities returned by a read-only SQL query |
| I-007 | `autocad_add_dimension` | Dimension text override |
| P-010 | – | Documented recovery for interrupted jobs |
| Q-008 | `autocad_check_drawing` | Flag too many different text heights |
| Q-009 | `autocad_check_drawing` | Find circles and arcs with near-zero radius |
| Q-010 | `autocad_check_drawing` | Cap findings per call, report truncation |
| T-002 | `autocad_plot_pdf` | Plot a paper-space layout at 1:1 |
| T-004 | `autocad_plot_pdf` | Suppress plot error dialogs and restore the setting |
| T-009 | `autocad_plot_pdf` | Apply a plot style table |
| U-003 | `autocad_render_preview` | Headless PNG/PDF/SVG preview of model space |
| W-010 | `autocad_generate_floor_plan` | Place a plan at a chosen origin |
| AL-006 | – | Log to stderr only |
| AM-003 | – | Claude Code config checked with the CLI |
| AM-004 | – | OpenCode config checked with the CLI |
| AM-005 | – | Codex CLI config (not tested: not installed) |
| AM-006 | – | Claude Desktop config (documented, not tested) |
| AM-007 | – | Environment variable reference |

Highest-value to close (cheap and user-visible): E-002, T-002/T-004/T-009,
Q-008/Q-009/Q-010, I-007, D-009.

### 4.4 Regression risks for the planned upgrade

| Risk | Why | Mitigation required in every milestone |
|---|---|---|
| Breaking the 64 public tool contracts | `AGENTS.md` invariant 11; `docs/compatibility.md` | Adding optional parameters only; `tests/test_server_schema.py` `EXPECTED_V0_3_0_TOOLS` must stay green |
| Silent backend/target switching | The project's central safety property, deliberately unlike three reference servers | Any new backend must be selected explicitly and named in every result |
| Units drift | Generators read the drawing's INSUNITS; a new backend may carry no INSUNITS | `E_UNITS_MISMATCH` rather than a default |
| "Verified" erosion | `verified` must mean a read-back happened | New tools must either read back or report `verified: null` — never `true` by assumption |
| Generated docs/catalog staleness | `tests/test_docs.py`, `tests/test_catalog.py` fail on staleness | Regenerate in the same change |
| Catalog status inflation | `AGENTS.md` evidence rules | New entries start at `planned`/`implemented`; promote only with recorded evidence |
| Live-test scarcity | 19 live tests | Each new COM-backed milestone adds a live test; skip-with-reason when AutoCAD is absent, never a mock substitute |

---

## 5. Audit limitations (stated honestly)

1. AutoCAD was **not launched**, per the mission's rules. All live-AutoCAD
   statements in this report are quoted from `docs/testing.md` (recorded
   2026-10-16) and from `scripts/catalog/data_live.py`; they were not re-run.
2. 19 tests were **skipped**, not passed, in the baseline run.
3. matplotlib is not installed, so `autocad_render_preview` was not exercised
   in this audit (its code path can be read, not run).
4. dwg-mcp's `.NET` plugin channel and any Civil 3D object model remain
   unverifiable on this machine (not installed).
5. The reference repositories were read as cloned snapshots (see the matrix
   document for exact commits); their code was not executed.
6. The working tree changed during the audit (concurrent workstream, §1 note).
   Every count and citation here describes `9b0ebe4`; the mid-edit test run is
   recorded only as an observation.
