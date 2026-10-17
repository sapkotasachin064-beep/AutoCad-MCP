# Target architecture for the All-in-One CAD MCP (Phase 3)

Design constraints taken as fixed (they are this project's identity, and the
audit found all three references violating at least one):

1. One stable MCP interface, one process, stdio only.
2. No tool may execute raw CAD commands, AutoLISP, shell or arbitrary SQL.
3. Backends and documents are never switched silently; every result names the
   engine that produced it.
4. Nothing is reported `verified` without a read-back; nothing `saved` without
   reading the file back.
5. Units are explicit; no hard-coded inches or millimetres outside `domain.units`.
6. Bounded outputs; typed errors; generated docs kept in step by tests.

The design below adds capability without adding a second architecture.

---

## 1. Layers

```
MCP client (Claude Code, OpenCode, Codex, Claude Desktop, ...)
   | stdio
src/server.py ................ MCP surface only: tool functions, resources, prompts
   |  @cad_tool boundary (registry, annotations, error envelope, state block)
src/core/ ................... services shared by every module
   |  errors  session  registry  paths  evidence  com_executor  logging  verify
   |
src/cad/ .................... drawing-document services (engine independent)
   |  documents (identity, pin, units policy)
   |  geometry (measure/construct, pure)
   |  validation (read-back helpers, plan checks)
   |  snapshot (normalised entity list)
   |
src/backends/ ............... one adapter per engine, chosen once per process
   |  base.py      the operation contract (unchanged in spirit, extended)
   |  com.py       ActiveX adapter parameterised by a descriptor  <-- generalised
   |  dxf.py       ezdxf headless (split into modules, see §6)
   |  targets.py   ComTarget / DxfTarget / RecordingTarget (unchanged)
   |  model/       STEP class: read-only model inspection (new family, §5)
   |
src/disciplines/ ............ optional, independently switchable modules
   |  architecture/ structural/ civil/ survey/ mep/ mechanical/
   |  each: tools (thin) + plans (pure) + schedules (pure) + tests
   |
src/domain/ ................. pure engineering logic used by disciplines
   |  units  plan  floorplan  grids  stairs  sheets  qc  takeoff  diff
   |  (discipline-owned modules move under src/disciplines/<name>/ later or stay,
   |   by owner preference; the import direction stays: domain has no engine)
   |
src/utils/ .................. geometry validation, constants
src/db.py ................... SQLite scan cache (unchanged)
src/cad_engine.py ........... becomes src/backends/com/engine.py (COM plumbing only)
```

Dependency direction stays one-way:
`server -> disciplines -> backends -> cad -> core/domain/utils`.
No discipline imports another discipline. No backend imports a discipline.
`logging` and `verify` under `core/` are **new** modules: nothing with those
names exists today (`core/logging.py` is also marked new in §4 and §7).

**What is deliberately *not* added:** a plugin loader with entry points, an
event bus, a dependency-injection container, a schema-codegen pipeline, a
second MCP framework (R2 ships `fastmcp` *and* `mcp`; that is a liability, not a
feature), or an HTTP transport. Tools are discovered from code, not from
configuration.

---

## 2. Multi-CAD adapters done safely (the R1/R2 idea, reimplemented)

R1 and R2 both prove the ActiveX surface is shared across AutoCAD-family CADs;
both also silently fall back between vendors. This project takes the first
half and refuses the second.

```python
# backends/com/descriptor.py   (new, small)
@dataclass(frozen=True)
class ActiveXTarget:
    key: str                      # "autocad", "bricscad", "zwcad", "gstarcad"
    prog_ids: tuple[str, ...]     # ordered; first that answers wins, all in-vendor
    process_names: tuple[str, ...]
    release_map: dict[str, int]   # "24.3" -> 2024
    min_release: str
    known_limits: frozenset[str]  # operations this vendor is known not to support
    verification_status: str      # "live_tested" | "never_run" | "refused"
```

* Selection is explicit and single-valued:
  `AUTOCAD_MCP_BACKEND=com` + `AUTOCAD_MCP_CAD=autocad|bricscad|zwcad|gstarcad`,
  or the abbreviated form `com:zwcad`. An unknown `AUTOCAD_MCP_CAD` value
  raises `E_INVALID_CONFIG` at startup — never a fallback (contrast R1
  `cad_controller.py:180`).
* `autocad_get_status` and every result gain `target: {key, prog_id,
  release_year, verification_status}`. A vendor that has never been run here
  reports `verification_status: "never_run"` and the catalog keeps its entries
  at `implemented`, never `verified`.
* `known_limits` feeds `UNSUPPORTED_REASONS`, so a vendor-specific gap is a
  typed refusal (`E_UNSUPPORTED_BACKEND`) instead of a COM error.
* The `tools/*` COM implementations are unchanged: they already operate on
  document objects, and the descriptor only changes which application object
  the executor acquires.

Sequencing note: BricsCAD/ZWCAD/GstarCAD cannot be tested on this machine.
The milestone therefore ships the descriptor, the AutoCAD descriptor tested
live, and the other descriptors marked `never_run` with a live-test skip reason.

---

## 3. Typed contracts at the tool boundary

Today every tool returns a dict and the envelope is documented, not typed.
The audit's cheapest high-value idea from R3 is *machine-readable output
schemas*; adopting them must not break existing clients.

Proposal, in three steps:

1. Add `output_schema` to `ToolSpec` (optional, default `None`) and emit MCP
   `outputSchema` only for tools that declare it. Existing tools are unaffected.
2. Introduce a small typed result core reused by every tool:
   `Result = {status, state?, notices?, evidence?, warnings?, truncated?, totals?}`,
   represented as plain dicts built by helpers in `core/reports.py` — no
   framework, no pydantic models at the boundary (the payloads are already
   stable; typing them with pydantic would add a dependency and churn).
3. A schema-snapshot test asserts that a tool's declared `output_schema`
   matches the keys its tests produce, so the schema cannot drift.

Rejected alternative: one generic `operation`-dispatch tool (R2's design, 7
tools / 56 operations). It shrinks the advertised surface but destroys schema
validation, per-operation annotations and per-operation capabilities — the
audit's own comparison table records that trade-off
([`../architecture-comparison.md:34`](../architecture-comparison.md)).

---

## 4. Reliability services (new but small)

| Service | Purpose | Where | Design source |
|---|---|---|---|
| **Undo group per mutating call** | one Ctrl+Z per tool call; rollback on partial failure | `backends/com/undo.py`: `with undo_group(label): ...` using `StartUndoMark`/`EndUndoMark` and `UNDO Back` on exception | idea: U-C4N (MIT), R1 (`cad_controller.py:355-373`) |
| **Verification helpers** | one place that reads state back and raises `E_VERIFICATION_FAILED` | new `core/verify.py`: `expect_modelspace_delta`, `expect_property`, `expect_file`, `expect_handle_set` | same checks exist today only inline in `tools/_common.py:91` and `targets.py:210` |
| **Typed batch runner** | N validated operations in one call, one undo group, per-operation results | `server.autocad_run_plan` + `domain/batch.py` | idea: R2 shorthand (as input format only) |
| **Measurement tools** | distance/area/angle/polyline length from geometry, not from CAD query strings | `cad/geometry.py` + `server.autocad_measure` | idea: R3 `measure` kinds (2D subset) |
| **Screenshot** | capture the live drawing window to a PNG file with SHA-256 | `tools/output.py` extension + `server.autocad_capture_screenshot` | idea: R1 `screenshot` (fixed: annotated as `external`/write, opt-in focus, no keystroke injection) |
| **Evidence bundle** | drawing + PDF + report + hashes in one manifest | `core/evidence.py` extension | catalog `U-007` |
| **Structured logging** | one logger, stderr only, per-call record (tool, args hash, duration, outcome, ids) | `core/logging.py` (new) | R1 does stderr+file logging (`server.py:32-59`); R2 calls `logger.<level>(...)` at 327 sites without a taxonomy. Ours must never print to stdout. |

Ordering constraint: **undo groups must land before the batch runner**, because
a batch without an undo group turns a failed 50-primitive plan into 50 orphan
entities. The roadmap enforces this dependency.

---

## 5. STEP / model inspection as a separate capability class

STEP files are not drawings and must not masquerade as one.

```
src/backends/model/            (new family; read-only, no document mutation)
    base.py                    ModelBackend: probe/import/inspect/query/measure
    step_occt.py               optional extra: OCP or cadquery-ocp
    capabilities.py            derived capability map, same rule as drawings
tools: autocad_model_inspect, autocad_model_find_entities, autocad_model_measure,
       autocad_model_diff        (names finalised in the milestone)
```

Rules that keep it honest:

* All four tools are `kind="read"` — a model backend cannot mutate a drawing.
* Units: every numeric result carries `unit: "mm"` **and** the source file's
  declared unit when the file declares one; a file without a unit declaration
  reports `unit_source: "assumed"` and the assumption is visible. (R3 hard-codes
  mm and never converts — not acceptable here.)
* Feature detection is limited to what is deterministic and testable: surface
  type per face, radii, axis directions, draft angle relative to a supplied
  pull direction, ray hits, section edges, distances, wall thickness
  statistics. No inference labelled as a design conclusion.
* No manufacturing or compliance verdicts in any tool text.
* The backend is absent unless its extra is installed: the model tool lists
  only the `model` backend in `capability_map` (today `render_preview`
  likewise lists only `dxf`), and a call without the extra refuses with
  `E_DEPENDENCY_MISSING` naming the extra — the pattern
  `backends/dxf.py:1306-1308` already uses for matplotlib.
* Verification method: **golden numeric fixtures** — small STEP files whose
  bbox, volume and distances are asserted to a stated tolerance. R3's
  `repeated-instances.step` proves the approach works; our fixture must be
  generated by us (a script in `tests/golden/`) so it carries no third-party
  provenance.

---

## 6. Discipline modules

```
src/disciplines/
    __init__.py            registry of discipline packages
    architecture/          existing floor plans, walls, grids, stairs, sheets move here
    structural/            beams, footings, rebar details, bar bending schedule
    civil/                 gravity networks, grading, volumes (Civil 3D only where available)
    survey/                traverses, bearings, coordinates, levelling, grid cut/fill (pure)
    mep/                   plumbing, electrical, HVAC, P&ID drafting
    mechanical/            part views, fasteners, weld/GD&T symbols, 3D solids
```

Module contract (enforced by a test):

1. A discipline package exposes `TOOLSET` (the registry name), `register(server)`
   and nothing else public.
2. It may import `domain`, `cad`, `core`, `utils` — never another discipline and
   never `backends` directly (tools reach engines through the `@cad_tool`
   operation dispatch, exactly as today).
3. Every tool it registers carries `kind` and a declared operation; capability
   discovery stays code-derived.
4. `AUTOCAD_MCP_TOOLSETS=core,drawing,query` must hide whole disciplines; a
   disabled discipline may not appear in `autocad_get_capabilities`.
5. A discipline with no tests may not register tools (a test enforces one test
   module per discipline package).

Separation of concerns inside a discipline: `plans.py` (pure geometry →
`Plan`), `schedules.py` (pure entity list → tables), `tools.py` (thin tool
functions), `limits.py` (constants with the label "drafting default, not a
code requirement" — matching the existing `DraftingDefaults` pattern).

Priority: **structural** and **survey** first, because both are deterministic
(pure math + drafting with no external engine), which fits this project's test
model. Civil 3D and MEP follow, and any part that needs an unavailable engine is
catalogued `planned`, never mocked.

---

## 7. Errors, logging, timeouts, capability discovery

| Concern | Rule |
|---|---|
| Errors | One hierarchy (`core/errors.py`), one code per failure class, every code has `recoverable` + `recommended_action`. The legacy substring shim (`errors.py:122-132`) may shrink but must not grow; new raise sites use typed classes. |
| Timeouts | Every engine call runs through an executor with a timeout. New: per-operation defaults (plot 300 s, batch = sum of member budgets, model import 600 s), configurable per tool via env, reported in the error when exceeded. |
| Logging | New `core/logging.py`; stderr only; one line per tool call with `tool`, argument digest (never values), duration, outcome, error code, drawing identity, backend/target. stdout stays the protocol channel (a test asserts it). |
| Capability discovery | Unchanged rule: a capability is advertised iff the code implements it. Extended to report per target (vendor/release) and per optional extra (kernel present, matplotlib present). |
| Bounded output | Every listing and measurement tool takes `limit`/`offset`, returns `truncated` and totals. New tools inherit the helpers in `core/evidence.py`. |

## 8. Safe mutation policy (explicit)

| Operation class | Policy |
|---|---|
| Read | No keystrokes, no variable writes, no document activation. |
| Write | Runs inside an undo group; read-back required; `state.verified` true only on success. |
| Destructive | Dry run by default (`delete`, generators), `overwrite=true` to replace files, `discard_changes=true` to close dirty documents. |
| External | Paths validated; temp-file-then-replace; size + SHA-256 read back. |
| Batch | Every member validated *before* the first mutation (fail fast with **nothing drawn**), runs in one undo group, reports per-member `executed`/`verified` and rolls back on failure. |
| Screenshot | `external` (writes a file), never `read`; does not inject keystrokes; focus/window changes are reported as notices. |
| New engines | Explicit selection only; an unavailable engine is a typed refusal with a reason. |

## 9. Test strategy that verifies results, not responses

| Layer | Proves | New work |
|---|---|---|
| Unit (pure) | geometry, units, plans, schedules, checks | grows with disciplines |
| Fake-COM | the exact call sequence and checks this code sends | extended for the descriptor and undo groups |
| Headless DXF (real files, re-read with ezdxf) | drawing results on disk | the primary evidence for new drafting features |
| Golden regression | output identity across versions | new goldens per generator; **numeric goldens for STEP** |
| stdio e2e | discovery, schemas, envelopes, toolsets | extend for output schemas and batch |
| Live AutoCAD | real COM behaviour; only evidence allowed to say `verified` | one live test per new COM-backed milestone; skip with reason when AutoCAD is absent |
| Contract | tool names/args/annotations/output schemas stable | new: snapshot test per tool; `EXPECTED_V0_3_0_TOOLS` preserved |
| **Result-verification tests (new)** | that the *drawing* changed as claimed: re-open the artefact and assert geometry/units/units-header, not just `status: ok` | required for every new mutating tool before it may claim `verified` |

Rule kept from `AGENTS.md`: fake tests prove what we send, nothing about
AutoCAD; live results are recorded in `docs/testing.md` with the run output.
