# Licence review (Phase 1: audit)

Scope: the licence position of this project, of the three mission reference
repositories, of every dependency a proposed feature would add, and the rules
that follow for the upgrade. Nothing here is legal advice; it records what the
files say and applies the policy already written in
[`../reuse-and-licensing.md`](../reuse-and-licensing.md).

---

## 1. This project

| Item | State | Evidence |
|---|---|---|
| `LICENSE` file | **absent** | repository root listing |
| `pyproject.toml` licence field | **absent** | `pyproject.toml` |
| Effective position | All rights reserved by default; choosing a licence is the owner's decision | `README.md:274-278`, `../reuse-and-licensing.md:3-9` |

Consequences for the upgrade:

1. No third-party code may be *copied in* while the project has no licence,
   because the resulting combined work could not be distributed coherently.
   Reimplementation from documented behaviour remains the policy in force.
2. If the owner chooses a permissive licence later (MIT/Apache-2.0 are the
   natural candidates given the dependency set), then MIT/Apache-2.0 material
   could be copied with notices. Until then: **ideas only**.
3. This report recommends the owner decide (§5) before any milestone that
   would benefit from code reuse.

---

## 2. The three mission reference repositories

| | R1 `daobataotie/cad-mcp` | R2 `AnCode666/multiCAD-mcp` | R3 `mattmohandiss/cad-mcp-server` |
|---|---|---|---|
| Licence file | MIT, `LICENSE:1-3` | Apache-2.0, `LICENSE:2-4` | MIT, `LICENSE:1-3` |
| SPDX declaration | `pyproject.toml:7` (`license = { file = "LICENSE" }`) | `pyproject.toml:11`, `src/__version__.py:10` | `package.json:80` |
| Copyright holder | Cao Rui (`LICENSE:3`, 2025) | none in LICENSE; authors in `pyproject.toml:12-16` (AnCode666, SVF-GFA, JardiMargalefAgusti) | Matt Mohandiss (`LICENSE:3`, 2025) |
| NOTICE file | none | **none** (Apache-2.0 §4(d) applies only if one exists upstream) | `THIRD_PARTY_NOTICES.md` exists |
| Attribution duty if code were copied | keep copyright + permission notice | keep licence text; state changes; §4(d) NOTICE if one exists | keep the MIT notice + the third-party notices |
| Verdict for this project | **Reimplementation only** (policy stricter than the licence) | **Reimplementation only** | **Reimplementation only** |

### 2.1 Third-party components inside the references

| Component | Where | Licence | Reuse consequence |
|---|---|---|---|
| OCCT 8.0.1 (open CASCADE) | R3, statically linked into the `occt-sidecar` binary (`occt/sidecar/CMakeLists.txt:14,40-42`) | **LGPL-2.1** | Distributing the compiled sidecar triggers LGPL §6 (licence text, notices, relinkability). R3's own notices state the licence but **do not ship the LGPL text or OCCT's copyright line**, and R3 applies a source patch (`occt/sidecar/patches/occt-8.0.1-cosmopolitan.patch`) whose modified source is only available as a diff. |
| Cosmopolitan toolchain (cosmocc 4.0.2) | R3 build scripts, packaged APE launchers (`occt/sidecar/scripts/build.py:59-61`) | not documented in-repo; upstream is ISC-style — **UNVERIFIED from the clone** | Same reasoning as above: the notices file omits it |
| nlohmann/json 3.12.0 | R3, downloaded at build time (`occt/sidecar/scripts/build.py:49-50`) | MIT upstream; **not listed** in `THIRD_PARTY_NOTICES.md` | Notice gap in R3, not a blocker for ideas |
| `@modelcontextprotocol/server` 2.3.1 | R3 | Apache-2.0 | permissive |
| fastmcp, FastAPI, uvicorn, openpyxl, Pillow, pydantic, pydantic-settings | R2 | MIT / BSD / Apache-2.0 (fastapi) | permissive |
| `mcp`, `pywin32`, `pydantic`, `Pillow` | R1 | MIT, PSF, MIT, MIT-CMU | permissive |

**Net effect on the All-in-One plan:** no reference repository is under a
reciprocal licence in its own code, so *ideas* are free to take under this
project's policy. The only copyleft surface is the OCCT sidecar binary in R3.
Adopting OCCT for STEP would therefore require a deliberate owner decision and
one of these paths:

| Path | What it means | Licence effect |
|---|---|---|
| A. Python binding to a system-installed OCCT (e.g. `OCP`/`cadquery-ocp`) | user installs the wheel; we add an optional extra | LGPL obligations fall on whoever distributes the binding; this project only calls a library, and the binding ships its own notices. Standard practice for LGPL libraries. |
| B. Reuse R3's sidecar binary | download from npm tarball, ship it | We become a distributor of a statically-linked LGPL work **and** of a third-party build with incomplete notices. Highest duty; also pins us to their build. |
| C. Write our own minimal STEP parser/measurer | no kernel dependency | Feasible only for import + basic topology + measurement of planar/analytic surfaces; not for real B-rep measurement (volume, wall thickness, curvature). Should be rejected as a product decision, but is licence-clean. |
| D. Do not add STEP | – | Zero licence risk |

Recommendation: **A**, behind an optional extra, and only after the owner has
decided the project licence (§5). Report the kernel's identity and version in
`autocad_get_capabilities` so the LGPL boundary is visible to users.

---

## 3. Dependencies already in use

| Dependency | Licence | Status |
|---|---|---|
| `mcp` (MCP Python SDK) | MIT | required `>=2.3,<3` |
| `pywin32` | PSF | required |
| `ezdxf` | MIT | optional extra `[dxf]` |
| `matplotlib` | PSF-based | optional extra `[render]`; absent on this machine |
| `pytest` | MIT | dev only |

## 4. Dependencies a proposed feature would add

| Feature | Candidate dependency | Licence | Platform | Notes |
|---|---|---|---|---|
| Live screenshot capture | `Pillow` (MIT-CMU; installed here as `PIL` 12.3.0 but **not declared in this project** — would be added as an optional extra), `pywin32` `win32gui` (part of the already-required `pywin32`) | MIT-CMU / PSF | Windows | new **optional** declaration only; no new required dependency |
| Excel export of reports | `openpyxl` | MIT | any | already installed here (`openpyxl` present) |
| STEP read/measure | `OCP` / `cadquery-ocp` (optional extra) | LGPL-2.1 (kernel) + Apache-2.0 (binding) | wheels: win/mac/linux | see §2.1 path A |
| STEP without a kernel | — | — | — | §2.1 path C, limited |
| DXF↔DWG conversion | ODA File Converter (external binary) | proprietary EULA | Windows/Linux/macOS | cannot be bundled; must be user-installed and detected, never silently required |
| accoreconsole batch | part of installed AutoCAD | proprietary (AutoCAD licence) | Windows | already covered by the user's AutoCAD licence |

**No new required dependency is needed for any of the top-priority milestones**
(undo groups, batch runner, screenshots, measurement, discipline modules).
That is the strongest argument for the milestone ordering in
[`05-roadmap.md`](05-roadmap.md).

---

## 5. Decisions requested from the owner (not taken here)

1. **Choose a licence** for this repository (or keep all-rights-reserved).
   Everything else in this report works either way; the choice only changes
   whether code copying is ever allowed.
2. **Decide the STEP path** (§2.1 A–D) if the STEP milestone is approved.
3. **Decide whether the project may start a second process** (an OCCT sidecar,
   `accoreconsole.exe`) — this project's current invariants are stdio-only and
   in-process except for AutoCAD itself; the roadmap marks these as
   owner-approval gates.

## 6. Rules applied during this audit

* No reference file was copied into this repository.
* No reference repository was executed or installed.
* No code from a GPL/AGPL/proprietary/unlicensed source was read beyond
  licence and README material, and none was used.
* Attribution for every idea adopted later is listed in the roadmap's
  sources-and-credits section and must also appear in the README
  acknowledgements.
