# Reference feature matrix (Phase 1: audit)

Three reference repositories were cloned to a scratch folder and read file by
file. Nothing from them was executed, installed, or copied. Evidence is
`path:line` in each clone; the audit transcripts are summarised here.

| Ref | Repository | Commit | Language | Licence |
|---|---|---|---|---|
| **R1** | `daobataotie/cad-mcp` | `bfcf9bb` (shallow, 1 commit) | Python ≥3.10 | MIT |
| **R2** | `AnCode666/multiCAD-mcp` | `360ec77` | Python ≥3.10 | Apache-2.0 |
| **R3** | `mattmohandiss/cad-mcp-server` | `9bb0caf` | TypeScript, Node ≥24 | MIT + LGPL-2.1 sidecar |

**This project** = `9b0ebe4` (V0.3.0), the source of truth. Legend for
"Evidence": **V** = implementation read in the clone; **R** = claimed in the
repository's own docs only; **UNVERIFIED** = not checkable from the repository.
Effort follows the roadmap scale: **S** ≈ 1–2 days, **M** ≈ 3–10 days,
**L** ≈ 2–5 weeks, including tests and docs.

---

## 1. Feature comparison matrix

"Where" is the implementing location, not the documentation. "Compatible" asks
whether the idea can live inside this project's architecture without violating
its invariants (`AGENTS.md`).

### 1.1 Engine connection and targeting

| Capability | This project | R1 cad-mcp | R2 multiCAD-mcp | R3 cad-mcp-server | Compatible | Effort | Verification method |
|---|---|---|---|---|---|---|---|
| Live AutoCAD over COM | V `cad_engine.py:29` `PROG_ID`, `backends/com.py` | V `src/cad_controller.py:198-220` | V `src/adapters/mixins/connection_mixin.py` | – | n/a (already have) | – | existing 19 live tests |
| Dedicated COM thread + per-call timeout | V `core/com_executor.py` | V thread, **no timeout** (`src/cad_controller.py:135-137`) | V thread, no per-call timeout found | n/a | n/a | – | `tests/test_com_executor.py` |
| **Multi-vendor COM (ProgID table)** | absent (`docs/backends.md:55` planned) | V `src/cad_controller.py:166-180` (AutoCAD/GCAD/GstarCAD/ZWCAD) | V `src/config.json:4-25` (AutoCAD/ZWCAD/GstarCAD/BricsCAD) | – | **yes**: one descriptor object behind the existing `Backend` contract | M for the descriptor; L per extra vendor (plus hardware to test) | new fake-COM descriptor tests; a live test only when the vendor is installed |
| Explicit target selection, no silent fallback | V (backend fixed by env; no `auto`) | **fails**: unknown `cad.type` silently → AutoCAD (`src/cad_controller.py:180`) | **fails**: auto-detect priority list, silent (`src/adapters/adapter_manager.py:109-124`) | n/a | yes (project invariant) | S | test asserting an unknown backend/target name is refused with a typed error |
| Per-vendor capability discovery | V `core/registry.py:94-129` (derived from code) | absent (0 error codes) | absent | V `TOOL_REGISTRY` + output schemas (`src/tools/registry.ts:7-57`) | yes | S–M | extend `supported_operations` per target descriptor |
| Active-document identity + pinning | V `cad_engine.get_drawing_identity`, `core/session.py` | partial: caches `self.doc` (`:230`); re-reads `ActiveDocument` only in open/close paths (`src/cad_controller.py:1324,1340`), never before each call; no pin check | not read as pinning; switch tool exists | n/a | yes | – | existing tests |
| Terminal / file-IPC backend for LT | planned (`docs/backends.md:52`) | absent | absent | absent | yes | L | live test only with LT installed |

### 1.2 Tool-surface design

| Capability | This project | R1 | R2 | R3 | Compatible | Effort | Verification |
|---|---|---|---|---|---|---|---|
| Typed per-task tools | V 64 tools, one schema each | V 35 tools | **op-dispatch**: 7 tools, single `operations` string + internal dispatch (`src/mcp_tools/tools/*.py`) | V 4 tools | yes; op-dispatch deliberately rejected (`docs/analysis/architecture-comparison.md:34`) | – | `tests/test_server_schema.py` |
| MCP annotations (read-only/destructive) | V all 64, from `kind` (`registry.py:31-59`) | partial 11 of 35 (`src/server.py:779-1050`) | absent | V all 4 read-only (`src/index.ts:16-21`) | yes | – | registry tests |
| **Machines-readable output schemas** | partial: results are JSON dicts, no `outputSchema` | V Pydantic return models for 34/35 | absent | V `outputSchema` for all 4 + contract test (`src/output-schemas.ts`) | yes, additive | M | schema snapshot test per tool |
| Toolset profiles | V `AUTOCAD_MCP_TOOLSETS`, 10 toolsets | absent | absent | absent | yes | – | `tests/test_registry.py:72-78` |
| Capability resource | V `autocad://capabilities` | 1 resource `drawing://current` | UI resources (unused at runtime) | V `cad-mcp://query-help`, `mcp-capability://cad-core` | yes | S |
| **Compact command shorthand for batch input** | absent | absent | V `type\|p1\|p2\|...` lines (`src/mcp_tools/shorthand.py:1-14`) | absent | yes, as an *input format* for one typed batch tool, not as a replacement for typed tools | M | parser unit tests + round-trip tests |

### 1.3 Drawing, editing and annotation

| Capability | This project | R1 | R2 | R3 | Notes |
|---|---|---|---|---|---|
| Lines, circles, arcs, text, MTEXT, rectangles, polylines | V (arc, MTEXT included) | V (no MTEXT create) | V (`drawing_mixin.py`) | – | R1 lacks MTEXT creation; R2 lacks ellipse/hatch dispatch despite docs |
| Ellipse, spline, point | planned (`H`) | ellipse V, spline/point absent | spline V, ellipse absent in dispatch | – | cheap additions to both backends |
| Hatch | V with pattern read-back | V boundary polyline + delete on failure (`src/cad_controller.py:743-776`) | absent | – | this project's read-back is stronger |
| Dimensions | V aligned + linear, measured read-back | aligned only, hard-coded offset 5 (`src/cad_controller.py:868-872`) | dimension V | – | add angular/radial later |
| Leaders / multileaders | planned (`I`) | absent | V leader + mleader (`drawing.py:480-481`) | – | AutoCAD `AddLeader`/`AddMLeader` |
| Tables | planned | absent | V (`shorthand.py:107-118`) | – | AcadTable |
| Blocks + attributes | V insert/list/read/update attrs | **partial**: `create_block` makes an empty definition (`src/cad_controller.py:1367`) | V incl. `get_attrs`/`set_attrs` | – | R1's block claim is an overclaim |
| Editing transforms | V move/rotate/copy/scale/mirror/offset/array/delete/props | V + **polar array** (`src/cad_controller.py:1229`) + undo/redo tools | V copy/paste/move/rotate/scale/set layer/color/delete | – | polar array math in R1 is off by one step for sweeps ≠ 360° |
| Trim / extend / fillet / chamfer | planned | via `send_command` only | via `SendCommand` only | – | must be real COM methods, never a raw-command tool |
| Layer state (freeze/lock/off/color/linetype) | V properties only | create + set current | V on/off/delete/rename/color/info | – | R2 has the widest layer set |
| Layouts / viewports / paper space | list only (`output.py`) | absent | absent | – | greenfield for all four |
| Plot to PDF with on-disk verification | V (`tools/output.py`, `%PDF` + MediaBox) | via `send_command` only | file save as PDF | – | this project is strongest |
| DXF read/write | V (export live; full read/write headless) | SaveAs only | SaveAs `dwg/dxf/pdf` | absent | – |
| DWG read/write | live only (AutoCAD) | live only | live only | absent | – |

### 1.4 Inspection, measurement and verification

| Capability | This project | R1 | R2 | R3 | Notes |
|---|---|---|---|---|---|
| Entity listing with filters + pagination | V `list_entities` (limit+offset, `truncated`) | partial: limit, **no offset**, no truncated flag (`src/cad_controller.py:967-974`) | select + list | V find_entities with filters + pagination | this project's pagination is already correct |
| Entity detail by handle | V `get_entity` | V per-type properties (`src/cad_controller.py:993-1046`) | V | V entity ids | |
| Scan to SQLite + read-only SQL | V `src/db.py` | absent | absent | absent | uniquely this project |
| Distance / area measurement tools | **partial**: derived in QC/takeoff, no explicit measure tool | partial (Length/Area fields) | absent | V (2D-agnostic: distances, thickness, ray, section, curvature) | a first-class `measure` tool is a shared gap |
| Distance between two points/entities | absent | absent | absent | V `BRepExtrema_DistShapeShape` | 2D equivalent is cheap |
| **Screenshot of the live drawing** | **absent** (headless `render_preview` only, needs matplotlib, not installed) | **V window capture** `GetWindowRect` + `PIL.ImageGrab` (`src/cad_controller.py:1091-1093`), forces `Regen`, restores minimized window, steals focus, and is annotated `readOnlyHint=True` (`src/server.py:818`) although it mutates view state | V `_PNGOUT` via `SendCommand` (`view_mixin.py:206,221`) + **simulated mouse click** (`utility_mixin.py:413-457`) | – | adopt the idea (capture to file + SHA-256), never the mis-annotation; capture must be annotated as a write/external |
| Preview with handles drawn | planned (`U-006`) | absent | absent | – | |
| Before/after previews | planned (`U-008`) | absent | absent | – | |
| Read-back verification of each mutation | V `state.verified` per tool | **absent** (only reads Handle) (`src/server.py:616-626`) | absent | n/a (all read-only) | the project's key differentiator |
| Undo grouping per call | planned (`P-005`) | V `StartUndoMark`/`EndUndoMark` per op (`src/cad_controller.py:355-373`) | V undo/redo tools | – | adopt the mark idea (also in U-C4N, MIT) |
| Rollback of a partial failure | planned (`P-006`) | **absent**: partial array loops leave work done | absent | – | needs the mark + explicit `UNDO Back` |
| Idempotency / duplicate-call protection | absent | absent | absent | absent | out of scope for now |

### 1.5 Batch, data and exports

| Capability | This project | R1 | R2 | R3 | Notes |
|---|---|---|---|---|---|
| Batch drawing in one call | partial (generators emit a plan) | absent (arrays only) | V 7 tools × N ops per call | – | a typed batch runner is the natural home |
| Draw from CSV / tables | planned (`AG-006`) | absent | Excel/JSON **export** only | – | input side is unbuilt everywhere |
| Structured data export | V JSON/CSV/MD reports, SQLite scan | absent | V JSON + Excel (openpyxl, 3 sheets, all/selected) (`export_mixin.py`) | – | Excel export is the one thing R2 has that we lack |
| Evidence bundle (files + hashes) | partial: per-file SHA-256; no manifest | absent | absent | – | `U-007` |
| Template management | partial: `create_new_drawing` template | absent | absent | – | `AJ` |

### 1.6 Discipline features

| Domain | This project | R1 | R2 | R3 |
|---|---|---|---|---|
| Architecture / residential | V floor plans, walls, doors, windows, schedules, stairs, sheets | absent | absent | absent |
| Structural drafting | V column grids + marks | absent | absent | – |
| Civil / survey | planned (pure math feasible: traverses, volumes, contours) (catalog `Z`) | absent | absent | absent |
| Electrical / plumbing / HVAC / P&ID | planned (catalogued with tool-level detail) | absent | absent | absent |
| Mechanical / 3D solids | planned (`N`) | absent | absent | adjacent: STEP solids via OCCT |
| STEP model inspection | absent | absent | absent | **V** 4 tools: `inspect`, `find_entities`, `measure`, `diff` |
| Mass properties / inertia | absent | absent | absent | partial: volume + surface area only; **no mass/inertia** (grep) |

The discipline modules are **greenfield in all four projects**: no reference to
copy from, only the catalogued plans in `scripts/catalog/data_disciplines.py`.
That materially changes the risk profile — these are pure-logic features where
this project's `domain/` + test discipline is the right development model.

### 1.7 STEP / model inspection detail (R3, the only prior art)

| R3 capability | Evidence | Reusable here? |
|---|---|---|
| STEP import (AP203/AP214/AP242 via `STEPCAFControl_Reader`, XCAF assemblies) | V `occt/sidecar/cpp/sidecar.cpp:700-737` | Design only; code is C++/TS |
| Bbox, solid/face/edge/vertex counts, volume, surface area, validity | V `sidecar.cpp:197-231` | Design |
| Face/edge/vertex/body queries with type+size filters and pagination (limit ≤1000) | V `sidecar.cpp:585-657` | Design |
| Distances (pairwise, ≤100 000 pairs) | V `sidecar.cpp:233-257` | Design |
| Wall thickness by ray grid (spacing default 2 mm, statistics) | V `sidecar.cpp:441-555` | Design; deterministic and testable |
| Draft angle + undercut boolean (`draft<0`) | V `sidecar.cpp:502-512` | Design |
| Ray casting with sorted hits | V `sidecar.cpp:267-287` | Design |
| Point analysis: containment, face classification, closest point, curvature | V `sidecar.cpp:356-438` | Design |
| Section cut edges (cap 1000/entity, 5000/request) — **no area** | V `sidecar.cpp:303-322` | Design |
| Face continuity C0–CN | V `sidecar.cpp:513-522` | Design |
| Export of anything (STEP/STL/OBJ/PNG) | **absent** | – |
| Mass, density, inertia, centroid | **absent** (`VolumeProperties.Mass()` only) | – |
| Hole / fillet / pocket / slot recognition, interference check | **absent** | – |
| Units: output hard-coded mm, no conversion | V `src/tools/inspect.ts:56` etc. | Must not copy: this project requires explicit units |
| Protocol: 16-byte header + JSON ≤16 MiB / binary ≤64 MiB, request ids, timeouts 120 s/600 s | V `src/sidecar/protocol.ts:3-59`, `client.ts:87-95` | Design; a Python client is ~200 lines |
| Error model: 4-value union, kernel errors mostly `unknown` | V `src/utils/errors.ts` | Weaker than this project's envelope |
| Binaries shipped inside the npm tarball; only source-distributed via CI build | V `.github/workflows/release-please.yml:136-138` | Not directly obtainable as a wheel |

---

## 2. Claim verification (README vs source)

Mission rule: "Do not rely on README descriptions alone." Every claim audited
was checked against code.

### R1 `daobataotie/cad-mcp`

| Claim | Verdict | Evidence |
|---|---|---|
| 35 tools | **confirmed** | 35 `@mcp.tool` decorators |
| "All tools return structuredContent with an outputSchema" | **rejected** | `screenshot` has no return model (`src/server.py:818-829`) |
| "Progress notifications" | **rejected** | no `report_progress`; 3 `ctx.info` calls only |
| NLP action keywords work | **rejected** | editing keywords produced but no consumer (`src/nlp_processor.py:211-255`) |
| Block operations | **overclaim** | `create_block` creates an empty definition; no entity insertion |
| Mirror keeps the original | **UNVERIFIED** | comment only (`src/cad_controller.py:1177-1184`) |
| Multi-CAD support | **claimed, unverified** | ProgID map exists; no tests for GCAD/ZWCAD (`src/cad_controller.py:174-179`) |
| Tests | **none** | 0 test files; the only integration script is `.gitignore`d |

### R2 `AnCode666/multiCAD-mcp`

| Claim | Verdict | Evidence |
|---|---|---|
| "56 CAD commands" | **partial** | 52 dispatch entries + 4 export combos; leader/mleader share one handler |
| Docs internal counts 55 vs 56 | **inconsistent** | `README.md:19` vs `docs/02-ARCHITECTURE.md:8` |
| "FastMCP 2.0" | **stale** | dependency is `fastmcp>=3.1.0` |
| Natural-language commands | **rejected** | changelog says removed; README still advertises it |
| "Each file <500 lines" | **rejected** | drawing 767, export 802, block 555 |
| 181 tests | **count matches** | 182 `def test_` total: 181 under `tests/unit/`, 1 manual (`tests/manual/`); all `MagicMock`, no live CAD |
| Path-traversal guard | **shipped disabled** | `src/config.json:29` `allow_arbitrary_paths: true`, README instructs enabling; code default is False |
| "Up to 70 % less API overhead" | **unverified** | no benchmark in repo |
| UI / MCP Apps | **not wired** | HTML generators never called; only `resourceUri` strings |
| Dashboard | **unauthenticated** | FastAPI on `127.0.0.1:8888`, no auth (`src/web/api.py:78-113`) |

### R3 `mattmohandiss/cad-mcp-server`

| Claim | Verdict | Evidence |
|---|---|---|
| 4 tools, all read-only | **confirmed** | contract test asserts the set (`src/tests/tool-contract.test.ts:20-24`) |
| Deterministic kernel answers | **confirmed by design** | OCCT via a pinned sidecar; one numeric integration test |
| "inertia details" / grouping / `remember`-`recall` | **rejected** | no such code; `groups` hard-coded `[]` |
| Distance "AABB shortcut when apart" | **rejected** | code always runs `BRepExtrema` |
| Hole vs boss classification | **not in code** | faces are returned; the *model* classifies |
| Golden-file parity gate | **unmet** | named in `docs/SIDECAR-TOOL-CONTRACT.md:51`; no fixtures in repo |
| Eval results recorded | **no** | `eval/runs/` is gitignored |
| LGPL compliance | **gap** | static-linked OCCT 8.0.1; notices lack the LGPL text and OCCT copyright |

---

## 3. Compatibility, dependencies and platform restrictions

| Reference | Runtime deps | Platform | Fit with this project |
|---|---|---|---|
| R1 | `mcp>=1.12,<2` (older SDK generation), `pywin32>=306`, `pydantic>=2`, `Pillow>=10.0.0`; no lockfile | Windows only in practice (COM imported at module import) | The **idea** of a ProgID table and of a window screenshot transfer. Its SDK pin is incompatible with our `mcp>=2.3,<3`. |
| R2 | `fastmcp>=3.1`, `mcp>=1.24`, `pywin32>=300`, `openpyxl>=3.1`, `pillow>=10.0.0`, `fastapi`, `uvicorn`, `pydantic-settings`; `uv.lock` | Windows only in practice | The mixin/adapter **pattern** transfers conceptually; we already have the equivalent seam (`backends/base.py` + `targets.py`) without a second MCP framework. Its dashboard/HTTP surface conflicts with this project's stdio-only invariant. |
| R3 | `@modelcontextprotocol/server 2.3.1`, `pino`, `zod`; dev: vitest, TS 7, oxlint | Node ≥24; sidecar binaries for win/mac/linux, validated on Linux x64 per its own contract doc | Only the **protocol/bounds design** transfers to Python. Its tools are a separate capability class, not a drawing backend. |

Cross-cutting facts worth recording:

* None of the three runs a **headless DXF** path; this project is the only one
  of the four with a second, testable document backend.
* Two of three (R1, R2) ship a **raw command escape hatch** (`send_command` /
  `SendCommand`). This project's invariant 1 forbids that permanently. Both
  also send raw command strings to the AutoCAD command line for ordinary
  operations: R2 for copy/paste (`manipulation_mixin.py:180,211`), `_PNGOUT`
  (`view_mixin.py:206,221`) and `_undo`/`_redo` (`view_mixin.py:311,334`);
  R1 for its undo/redo tools (`cad_controller.py:1250,1263`).
* Two of three (R1, R2) have **no CMake/CI tests of drawing results**; R1 has no
  tests at all.
* R3 is the only one with typed output schemas enforced by a contract test —
  the cheapest idea to import (additive, no behaviour change).

---

## 4. What this audit means for the All-in-One plan

1. **Never adopt a pattern that breaks invariants.** Op-dispatch tools, silent
   backend fallback, raw command tools, unauthenticated listeners and
   unverified success reports appear in the references and must stay out.
2. **The multi-CAD seam is the backend descriptor, not the tool layer.** R1 and
   R2 both prove that the same ActiveX calls work across vendors; their
   difference is only management of the ProgID and of the target's
   capabilities. This project can get the same result by making the existing
   COM backend parameterised by a descriptor, with zero changes to the tools.
3. **Everything discipline-specific is greenfield.** No reference can be
   followed; the catalog in `scripts/catalog/data_disciplines.py` is the plan of
   record. Pure `domain/` modules + tests is the right (and only honest) way.
4. **Screenshots and measurements are real gaps here** and both references prove
   they are feasible over COM on Windows this machine already has (`PIL` and
   `win32gui` are installed here; Pillow would still be added as a declared
   optional extra — see `03-license-review.md` §4).
5. **STEP is a separate capability class**, best delivered as its own read-only
   backend family. R3 proves the shape of the answer (bounded queries, filters,
   pagination, statistics) and also proves what to avoid (hard-coded mm, no
   export, docs claiming features the code lacks).
