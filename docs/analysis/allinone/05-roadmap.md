# Implementation roadmap and prioritized backlog (Phases 2 and 4)

Inputs: [`01-audit-report.md`](01-audit-report.md) (baseline, debt, risks),
[`02-reference-feature-matrix.md`](02-reference-feature-matrix.md),
[`03-license-review.md`](03-license-review.md),
[`04-target-architecture.md`](04-target-architecture.md).

Status: **proposal, no code written.** Work starts only after the owner approves
this document and answers the open decisions in §7.

Estimates are coarse and deliberately unflattering: **S** ≈ 1–2 days,
**M** ≈ 3–10 days, **L** ≈ 2–5 weeks, **XL** > 5 weeks of focused work by one
person, including tests and docs. They exclude time waiting for a CAD seat to
test against.

---

## 1. Phase 2 capability map (requested → where it lands)

| Requested capability area | Today | Milestone | Deliverable |
|---|---|---|---|
| Core drawing, geometry creation and editing | parts of it (7 primitives, 12 editors) | **M2**, **M4** | ellipse/point/spline, polar array, trim/extend/fillet/chamfer, move/copy between layers and spaces |
| Entity inspection, properties, selection, measurement | strong for listing, weak for measurement | **M3** | `autocad_measure`, entity-property set/get extension, saved selection sets, spatial filters |
| Layers, blocks, attributes, dimensions, annotations | partial | **M2**, **M4** | layer states (freeze/lock/off), block redefinition, dynamic blocks, leaders/multileaders, angular/radial dimensions, tables, text styles |
| Drawing lifecycle, document identity, units, coordinate systems | strong | **M1** | UCS/DCS reporting, unit-aware transforms, identity in every result, template management |
| Batch operations and efficient multi-step workflows | plan generators only | **M4** | `autocad_run_plan` (typed, validated, one undo group, per-op verification), CSV/table input, workflow replay |
| Screenshot / preview feedback and drawing verification | headless render only | **M3** | `autocad_capture_screenshot` (live window), before/after pairs, evidence bundle with hashes |
| DWG/DXF handling, PDF/image/data exports | good for DXF/PDF, no DWG offline | **M4** | DWG export via AutoCAD, DXF read/validate extension, Excel/JSON data export, ODA detection (optional, user-supplied) |
| Headless DXF creation and validation | implemented | **M1**, **M4** | parity test harness, split of `dxf.py`, more entity types, validation report |
| Multi-CAD adapters for applications that can be supported | single hard-coded ProgID | **M5** | descriptor-driven ActiveX backend (AutoCAD live-tested; BricsCAD/ZWCAD/GstarCAD declared `never_run`), `accoreconsole` batch backend, LT file-IPC backend (needs LT) |
| STEP model inspection and geometric measurement | absent | **M8** | separate read-only model-backend family with golden numeric fixtures |
| Architecture / structural / civil / survey / MEP / mechanical modules | architecture only | **M6**, **M7** | discipline packages with pure planners, schedules and deterministic checks; each switchable by toolset |
| Engineering calculations and drawing checks — only deterministic, tested ones | QC + takeoff + stairs | **M6**, **M7** | unit-tested formulas with stated assumptions and limits, never a code-compliance verdict |

Rule applied to every "calculation" in M6/M7: it ships only with (a) an explicit
formula, (b) a stated unit, (c) a test with a hand-computed expected value,
(d) a statement that it is a drafting aid, not a design or code check.

---

## 2. Milestones (dependency ordered)

### M0 — Protect what exists (must be first)
**Goal:** a frozen contract and a trustworthy baseline before any feature work.

| Item | Detail |
|---|---|
| Scope | contract snapshot test for all 64 tools (name, required args, annotations, toolset); record baseline `272 passed, 19 skipped`; fix doc drift A1–A3; add `docs/testing.md` run-log template; branch policy `feat/allinone-*`; keep `main` releasable |
| Depends on | nothing |
| Acceptance | (1) `python -m pytest tests -q` → ≥272 passed, 19 skipped, exit 0; (2) a new test fails if any V0.3.0 tool name/required argument/annotation changes; (3) README/test counts and `docs/compatibility.md:54` match reality; (4) `python scripts/build_tool_docs.py --check` and the catalog `--check` pass |
| Regression tests | the snapshot test itself; the existing 291 |
| Effort | S |
| Risk | Low. This protects against exactly the regression class the mission fears |

### M1 — Core CAD reliability
**Goal:** every mutation is atomic, bounded and truthfully reported.

| Item | Detail |
|---|---|
| Scope | undo group per mutating call + rollback on failure (`StartUndoMark`/`EndUndoMark`/`UNDO Back`); per-operation timeouts (plot 300 s, launch +30 s, model import 600 s) with the value reported in the error; shrink the legacy error-substring shim; `core/logging.py` (stderr, per-call record); extend verification helpers; split `backends/dxf.py` into cohesive modules without changing behaviour; add a COM↔DXF **parity test harness** (same call sequence → same result keys) |
| Depends on | M0 |
| Acceptance | (1) a 50-primitive generator call leaves exactly one undo step in AutoCAD (live test); (2) a deliberately failing plan leaves the model space unchanged (fake + live); (3) killing a COM call at the timeout reports `E_COM_TIMEOUT` and the next call succeeds on a fresh worker; (4) parity harness passes for every operation both backends implement; (5) no new substring mapping added to `errors.py`; (6) stdout carries only protocol bytes |
| Regression tests | all M0; new fake-COM undo tests; new live undo/rollback test; parity suite; `test_server_surface.py` (no pywin32 in headless imports) |
| Effort | M–L |
| Risk | Medium. Undo marks interact with user commands; `CMDACTIVE` handling must stay. Mitigation: undo group is a context manager that degrades to today's behaviour when `UNDO` state is unavailable, and says so in a notice |

### M2 — Annotation, entity and layer completeness (general CAD, not residential)
**Goal:** the "all-in-one drafting" surface: everything a drafter expects, on both backends where possible.

| Item | Detail |
|---|---|
| Scope | ellipse, point, spline (DXF+LWPOLYLINE where degenerate); polar array; trim/extend/fillet/chamfer via real COM methods; leaders and multileaders; angular/radial/diameter dimensions; tables; text and dimension styles; layer state (off/freeze/lock/plot), layer filters; block redefinition, dynamic-block property listing, attribute visibility; group/selection sets |
| Depends on | M1 |
| Acceptance | each new tool: validation test (no COM on bad input), fake-COM behaviour test, headless-DXF result test where supported, catalogue entry with honest status |
| Regression tests | contract snapshot (M0) extended; golden floor plan unchanged; catalog/doc regeneration |
| Effort | L (split into two PRs if needed: annotations; then entities/layers/blocks) |
| Risk | Medium. Trim/extend/fillet are difficult to verify headlessly — they are COM-only and must be live-tested or reported `implemented`, not `verified` |

### M3 — Inspection, measurement and visual verification
**Goal:** a model can see and measure what it changed.

| Item | Detail |
|---|---|
| Scope | `autocad_measure` (distance, angle, area, polyline length, bbox, minimum distance between two entities) with units and tolerance; `autocad_capture_screenshot` (live window → PNG + SHA-256, `external` kind, no keystrokes, focus changes reported as notices); before/after capture helper; evidence bundle (`U-007`) with a manifest; entity detail extension (all common properties, effective layer/linetype/colour); spatial filter (window/crossing by rectangle) |
| Depends on | M1 (undo/logging not required but shares helpers), M2 (entity coverage) |
| Acceptance | (1) measurement of a 3-4-5 triangle returns 5.0 within a stated tolerance, in both backends; (2) screenshot writes a PNG whose header and size are verified and whose SHA-256 is reported; (3) the screenshot tool declares `external`, not `read`; (4) evidence bundle lists every file with hash and does not overwrite without `overwrite=true` |
| Regression tests | measurement unit tests against hand-computed values; headless render test (skip-with-reason if matplotlib absent); live screenshot test optional with a visible window |
| Effort | M |
| Risk | Medium. Window capture is fragile when AutoCAD is minimised/occluded; report it, never claim a picture proves geometry (R1 and R2 both hide this) |

### M4 — Batch operations and exports
**Goal:** long workflows in one call, with one undo step, and deliverables out.

| Item | Detail |
|---|---|
| Scope | `autocad_run_plan`: a bounded, typed list of registered operations (validated against the registry — never raw commands), executed in one undo group, per-operation `executed/verified/rollback` reporting, dry run by default; CSV/table input for repetitive drawing (`AG-006`); Excel + JSON export of schedules/takeoff (openpyxl optional extra); DWG export through AutoCAD (SaveAs with evidence); DXF validation extension; PDF/plot improvements (paper size, window area, multiple layouts); template management (`AJ`) |
| Depends on | M1 (undo + verification), M2 |
| Acceptance | (1) a 3-operation plan that fails at operation 3 reports ops 1–2 as rolled back and model space is unchanged; (2) plan members are refused if any operation name or argument is unknown **before** anything is drawn; (3) exported files carry size + SHA-256 and are re-readable by ezdxf/openpyxl where applicable; (4) `limit`/`truncated` on every list in the response |
| Regression tests | batch fake-COM suite; headless end-to-end batch producing a DXF re-read and asserted; contract test for the batch tool's schema |
| Effort | M–L |
| Risk | High if the batch tool grows into a raw-command escape hatch. Mitigation: the tool accepts only registry operation names + typed args; a test asserts that unknown/keyword names are refused and that no string ever reaches `SendCommand` |

### M5 — Additional CAD backends
**Goal:** drive what can actually be supported, and refuse what cannot.

| Item | Detail |
|---|---|
| Scope | descriptor-driven ActiveX backend (`com:autocad` live; `com:bricscad`, `com:zwcad`, `com:gstarcad` declared `never_run`); `accoreconsole.exe` batch backend (owner decision needed, §7); LT file-IPC backend **only if** LT is available; .NET plugin channel stays out of scope (per-release build pipeline, licence exposure) |
| Depends on | M1 (timeouts/logging), M3 (screenshot differs per vendor) |
| Acceptance | (1) `AUTOCAD_MCP_CAD=unknown` fails at startup with `E_INVALID_CONFIG`, never falls back; (2) every result names the target and its `verification_status`; (3) capability map derived per target; (4) for each non-AutoCAD vendor: either a live test or an explicit `never_run` label everywhere it appears (status, catalog, docs) |
| Regression tests | descriptor unit tests; fake-COM tests parameterised over descriptors; a live AutoCAD test proving the descriptor path did not change AutoCAD behaviour; startup-refusal test |
| Effort | M for the descriptor; L per additional vendor actually tested |
| Risk | Medium-high. Unknown vendors can fail in vendor-specific ways. Mitigation: unknown operation → typed refusal; unknown COM error → `E_COM_ERROR` with the HRESULT and a "this vendor is not live-tested" note |

### M6 — Discipline modules I: structural and survey (deterministic first)
**Goal:** prove the discipline-module contract with the two domains that need no extra engine.

| Item | Detail |
|---|---|
| Scope | **structural**: beam lines + marks, footing outlines and schedule, slab panel outlines, rebar detail from user-supplied bars, bar bending schedule, steel section outlines from dimensions; **survey**: traverse with closure error, bearing/distance line drawing, point import/export (CSV), area from coordinates, levelling reduction (rise-and-fall and height-of-instrument), grid cut/fill volumes, setting-out tables |
| Depends on | M4 (batch, exports), architecture docs (`04-target-architecture.md` §6) |
| Acceptance | (1) each formula has a unit test against a hand-computed value and a stated assumption list; (2) planners are pure and emit `Plan`s; (3) tools are hidden by `AUTOCAD_MCP_TOOLSETS`; (4) each discipline has ≥1 headless end-to-end test producing real entities; (5) no tool text claims code compliance |
| Regression tests | discipline unit tests; headless e2e; catalog entries; toolset isolation test |
| Effort | L |
| Risk | Medium. The risk is product scope, not code: every added formula invites "check my design". Mitigation: a documentation test that forbids compliance language in tool descriptions |

### M7 — Discipline modules II: civil, MEP, mechanical
**Goal:** the remaining drafting domains, with engine-dependent parts honestly refused.

| Item | Detail |
|---|---|
| Scope | **civil**: drainage layout with manholes and user gradients, pipe long sections, contours from spot levels (TIN), boundary plans; Civil 3D objects only where Civil 3D is installed (typed refusal otherwise); **mep**: plumbing runs + fixtures, drainage with gradient checks against user minimums, fixture-unit tally with user values, electrical points/circuits/panels with load tally, HVAC duct runs and diffuser layout, P&ID symbols + tag parsing + line/valve/instrument lists; **mechanical**: part views, fastener symbols, weld symbols, surface-finish and GD&T frames as annotation |
| Depends on | M6 (module contract proven), M4 |
| Acceptance | as M6, plus: every engine-dependent feature either live-tested or `planned`/`implemented` — never mocked |
| Regression tests | as M6 |
| Effort | XL (split per discipline; each discipline is its own PR and can ship independently) |
| Risk | Medium. Risk is sprawl. Mitigation: one discipline per PR, toolset-gated, catalogued honestly |

### M8 — 3D solids and STEP inspection
**Goal:** the advanced tier, clearly separated from 2D drafting.

| Item | Detail |
|---|---|
| Scope | **3D in drawings**: box/cylinder/cone/sphere/wedge/torus, extrude/revolve/sweep/loft, boolean union/subtract/intersect, slice, mass properties (volume, centroid, surface area), 3D views, visual styles, export STL; **STEP**: separate read-only model backend — import, inspect (bbox, volume, area, counts, validity), entity queries with filters + pagination, measurement (distance, wall thickness statistics, draft angle, ray casting, section edges), diff of two models, golden numeric fixtures |
| Depends on | M4 (batch/exports), owner licence decision for the kernel |
| Acceptance | (1) licence path chosen and recorded in `03-license-review.md`; (2) every numeric result carries a unit and, for STEP, whether the unit was declared or assumed; (3) golden fixtures assert bbox/volume/distance to a stated tolerance; (4) capabilities report the kernel name+version, or an `E_DEPENDENCY_MISSING` refusal; (5) 3D solid creation requires explicit opt-in (`N-016`) |
| Regression tests | golden geometry fixtures (generated by our script); kernel-absent path test; solid creation fake-COM test; live test for solids where AutoCAD is available |
| Effort | XL (the STEP family alone is L; 3D solids are L) |
| Risk | High. Kernel dependency, licence exposure, numeric tolerance design, and large-file memory. Mitigation: ship the STEP family as an optional extra with its own bounded limits, and keep it out of the drawing backend's capability set |

---

## 3. Feature matrix (milestone → capability → evidence required to claim "verified")

| Milestone | Feature | Backend(s) | Evidence required |
|---|---|---|---|
| M0 | contract snapshot, docs truth | n/a | test run recorded |
| M1 | undo group + rollback | com | live AutoCAD test + fake test |
| M1 | timeouts per operation | com | unit test on executor + live timeout test |
| M1 | logging | all | stdout-purity test |
| M2 | ellipse/point/spline | com+dxf | headless file re-read + fake COM |
| M2 | trim/extend/fillet/chamfer | com | live test (else `implemented`) |
| M2 | leaders, angular dims, tables | com (+dxf where ezdxf supports) | headless re-read + fake |
| M2 | layer states, block redefinition | com | live test |
| M3 | measure | com+dxf | unit test with hand-computed values |
| M3 | screenshot | com | live test with PNG header/hash checks |
| M3 | evidence bundle | all | file system assertions |
| M4 | batch runner | com+dxf | rollback test + headless e2e |
| M4 | CSV/Excel/JSON export | pure | file re-read with openpyxl/json/ezdxf |
| M4 | DWG export | com | live test, file header check |
| M5 | ActiveX descriptor | com | startup refusal test + live AutoCAD regression |
| M5 | other vendors | com | live test per vendor, else `never_run` everywhere |
| M6 | structural/survey formulas | pure + both | hand-computed unit tests + headless e2e |
| M7 | civil/MEP/mechanical | pure + both (+Civil 3D where installed) | as M6 |
| M8 | 3D solids | com | live test |
| M8 | STEP inspect/measure | model | golden fixtures with tolerances |

---

## 4. Regression protection (applies to every milestone)

1. `python -m pytest tests -q` must stay at or above the M0 baseline
   (272 passed / 19 skipped without AutoCAD).
2. The M0 contract snapshot must never be edited to make a change pass; a
   deliberate contract change requires a compatibility note in
   `CHANGELOG.md` + `docs/compatibility.md`, per `AGENTS.md` invariant 11.
3. Generated artefacts (`docs/tools.md`, catalog, feature catalog) regenerate in
   the same change; their `--check` tests must pass.
4. Every behavioural change to an existing tool is listed in
   `docs/compatibility.md#migration-from-v023`.
5. Live tests are added per milestone; a milestone whose live test cannot run
   here is recorded as `implemented`/`tested`, never `verified`, and the skip
   reason is in `docs/testing.md`.
6. Nothing is committed to `main`; each milestone is a branch with its own PR
   summary, and `main` stays releasable.

## 5. Prioritized backlog

### P0 — unblock the plan (no feature work before these)
| # | Item | Effort | Gate |
|---|---|---|---|
| 1 | Owner approves roadmap; answers §7 decisions | – | approval |
| 2 | M0 contract snapshot + doc drift fixes | S | – |
| 3 | Choose project licence (or confirm all-rights-reserved) | – | owner |
| 4 | Decide whether a live AutoCAD seat can be used for milestone testing | – | owner + AutoCAD |

### P1 — highest value, lowest risk (priority order below; M1 → M3 → M4 lead)
| # | Item | Effort | Why now |
|---|---|---|---|
| 5 | Undo group per call + rollback | L | Every later mutation tool depends on it; makes batch safe |
| 6 | `autocad_measure` | M | Shared gap of all four projects; cheap; deterministic tests |
| 7 | `autocad_capture_screenshot` + evidence bundle | M | Converts "the model says it drew it" into "a human can look" |
| 8 | `autocad_run_plan` (typed batch, one undo group) | M | The mission's efficiency goal; audit shows no safe prior art |
| 9 | Annotation entity completion (leaders, angular dims, tables) | M | Expected by any drafter |
| 10 | Layer states + block redefinition | M | Completes the layer/block story that R1/R2 also leave broken |
| 11 | Output schemas for tools that declare them | S–M | Cheap contract win from R3's design; additive |

### P2 — expansion (after P1 is verified)
| # | Item | Effort | Note |
|---|---|---|---|
| 12 | ActiveX descriptor + multi-vendor declaration | M | Only AutoCAD testable here; others labelled |
| 13 | Structural + survey disciplines | L | Deterministic, no extra engine |
| 14 | CSV/Excel export and import | M | openpyxl already present; closes the one R2 advantage |
| 15 | Civil/MEP/mechanical disciplines | XL | One PR per discipline |
| 16 | DXF module split + parity harness | M | Already partly in M1; finish before discipline sprawl |

### P3 — advanced / engine-dependent (owner gates)
| # | Item | Effort | Gate |
|---|---|---|---|
| 17 | STEP model backend | L | kernel licence decision |
| 18 | 3D solids in drawings | L | AutoCAD seat; solids opt-in |
| 19 | Civil 3D objects | XL | Civil 3D installed |
| 20 | AutoCAD LT backend | L | LT installed |
| 21 | `accoreconsole` batch backend | M | owner decision on starting a second process |
| 22 | .NET plugin channel | XL | per-release build pipeline; not recommended yet |

## 6. Proposed execution order (first 6 PRs)

1. **PR-1 (M0):** contract snapshot test, doc-drift fixes, testing-log template.
2. **PR-2 (M1a):** undo group + rollback + notices, with fake and live tests.
3. **PR-3 (M1b):** per-operation timeouts, logging module, error-shim shrink.
4. **PR-4 (M3a):** measure tool (both backends) + tests.
5. **PR-5 (M3b):** screenshot + evidence bundle (COM, external kind).
6. **PR-6 (M4a):** typed batch runner with fail-before-draw validation.

Each PR: tests + regenerated docs + catalog status update + compatibility note if
any existing behaviour changed.

## 7. Open decisions needed before implementation

1. **Licence**: choose one, or keep all-rights-reserved (§`03-license-review.md`).
2. **AutoCAD availability**: may milestones launch AutoCAD for live tests, and
   may they open scratch drawings only (recommended), or a real drawing?
3. **Second process**: may the server spawn a helper (`accoreconsole.exe`, an
   OCCT sidecar), or must everything stay in-process + stdio?
4. **STEP kernel**: LGPL binding via optional extra (recommended), reuse R3's
   built sidecar (not recommended), a limited in-house parser, or no STEP.
5. **Discipline scope order**: structural+survey before MEP, or a different
   order driven by the user's actual project mix?
6. **Tool budget**: at 64 tools today and ~40 more planned, does the client
   context budget allow the full surface, or should new discipline toolsets
   ship disabled by default? Today `AUTOCAD_MCP_TOOLSETS` defaults to `all`
   (all 10 toolsets; `core/registry.py:81-92`). The proposal: keep those 10
   enabled by default (`core,drawing,layers,editing,architecture,query,
   annotation,blocks,output,analysis`) and leave only the **new** discipline
   toolsets (structural, civil, survey, mep, mechanical) off unless named.

## 8. What this roadmap refuses to do

* No raw command / AutoLISP / SQL-write tool, in any backend, for any reason
  (R1 `send_command`, R2 `SendCommand`, R3 refusals are all considered).
* No silent backend, document, target or unit switching.
* No feature reported as verified without a read-back; no mock standing in for a
  live test.
* No unauthenticated network listener, no HTTP transport.
* No discipline "calculator" without a test and a stated assumption.
* No copying of third-party code before the licence decision and the notice
  requirements are recorded.

---

## 9. Sources and credits (ideas only)

Every idea this roadmap adopts from another project, with the licence that
allowed it to be read (policy: [`03-license-review.md`](03-license-review.md)
§6; positions in [`../reuse-and-licensing.md`](../reuse-and-licensing.md)).
No code is copied; each item is reimplemented against this project's invariants.
On adoption, the acknowledgement also goes into the README.

| Idea adopted (where) | Source | Licence |
|---|---|---|
| Explicit ProgID/descriptor table for multiple ActiveX CADs; refused their silent fallback (M5) | R1 `cad_controller.py:166-180`; R2 `src/config.json:4-25` | MIT / Apache-2.0 |
| Undo mark per operation (`StartUndoMark`/`EndUndoMark`, `UNDO Back` rollback) (M1) | U-C4N; R1 `_undo_group` (`cad_controller.py:355-373`) | MIT |
| Window screenshot to a file with a hash (M3); their read-only mis-annotation is **not** adopted | R1 `screenshot` (`cad_controller.py:1091-1093`); R2 `_PNGOUT` (`view_mixin.py:206,221`) | MIT / Apache-2.0 |
| Machine-readable output schemas + contract test (M0/P1) | R3 `src/output-schemas.ts`, `src/tests/tool-contract.test.ts` | MIT |
| Compact `type\|p1\|p2` input as an *input format* for one typed batch tool (M4) | R2 `src/mcp_tools/shorthand.py:1-14` | Apache-2.0 |
| Excel export of schedules via openpyxl (M4) | R2 `export_mixin.py` | Apache-2.0 |
| STEP inspection shape (bounded queries, filters, pagination, statistics) and the sidecar protocol design (M8) | R3 `occt/sidecar/cpp/sidecar.cpp`, `src/sidecar/protocol.ts` | MIT (OCCT sidecar itself is LGPL-2.1 — see §2.1 of the licence review) |
| Measurement kinds (distance/angle/area subset) (M3) | R3 `measure` tool | MIT |

Ideas already in this project before the audit (undo verification, path policy,
typed refusals) came from the earlier survey recorded in
`../reuse-and-licensing.md:54`.
