# Reuse and licensing review (reference analysis)

## This project's own licence

The repository has **no `LICENSE` file** and `pyproject.toml` declares no
licence, so today it is "all rights reserved" by default. Choosing a licence is
the owner's decision and is **not** made here. It matters for reuse: MIT and
Apache-2.0 material can be incorporated into almost any licence if its notices
are kept; GPL/AGPL material would impose its own terms on the whole project.

## Policy applied in this rebuild

1. **No reference code was copied into this repository.** Every reference
   finding was reimplemented from an understanding of the behaviour, written
   in this project's existing style and structure.
2. Rewriting does not by itself remove licence obligations, so the policy is
   stricter than "rewrite": only *ideas and documented behaviour* were taken,
   and only from MIT / Apache-2.0 repositories. Where an idea came from a
   specific repository, it is credited below and in the README.
3. Nothing at all -- not even ideas beyond what is common CAD practice -- is
   taken from GPL-3.0, AGPL-3.0, proprietary, or unlicensed repositories.
4. Third-party **dependencies** are a separate question: the only new one is
   `ezdxf` (MIT), as an optional extra.

### Verification that no code was copied

A line-level comparison (whitespace-normalised lines of 30+ characters,
imports and comments excluded) between this project's `src/` at the baseline
and every reference codebase found at most **6 shared lines out of 814**, all
idioms such as `deadline = time.monotonic() + timeout` and
`if isinstance(value, bool) or not isinstance(value, (int, float)):`.
Against `Easy-MCP-AutoCad` -- the unlicensed repository whose tool *names*
V0.2.0 mirrored (`draw_line`, `scan_all_entities`, `execute_query`, ...) --
the overlap is **zero lines**. Tool names and the idea of a tool are not the
same as its code; the README of V0.2.x already documented that these tools
were reimplemented, and this check supports it.

**Re-run after the V0.3.0 rebuild** (3,889 distinct lines in `src/`): the
largest overlap is 16 lines with U-C4N (MIT) and 14 with the proprietary
"CAD OS" repository (`autocad-mcp-13`, never read beyond its README). Every
shared line is an idiom (`except (OSError, subprocess.SubprocessError):`,
`if isinstance(value, (list, tuple)):`), a textbook formula (the polyline
bulge relations `theta = 4.0 * math.atan(bulge)` and
`radius = chord / (2.0 * math.sin(abs(theta) / 2.0))`), a fact about AutoCAD
class names (`"AcDbBlockReference": "INSERT",`) or ordinary ezdxf API usage.
Overlap with the GPL-3.0, AGPL-3.0, xstaar-proprietary and unlicensed
repositories (`autocad-mcp-3`, `AUTOCAD-ELECTRICAL-MCP-main`,
`autocad-mcp-master`, `Easy-MCP-AutoCad-main`, `cad-mcp`) is zero lines.

## Per-repository decisions

| Repository (folder) | Licence | Decision | What is used | Credit |
|---|---|---|---|---|
| U-C4N/Autocad-MCP (`Autocad-MCP-main`) | MIT | **Adapt ideas, independent implementation** | Single-thread COM executor with per-call timeout and rebuild; UNDO *Mark* before the `StartUndoMark` group; `BACKGROUNDPLOT=0` + verify the PDF on disk; path checks for `..`, `\\?\`, UNC and system folders; capability refusals as typed errors; validating symbol names before interpolating them into commands | README acknowledgements |
| beiming183-cloud/AutoCAD-MCP (`AutoCAD-MCP-main-1`) | MIT | **Adapt ideas** | Error codes that carry `recoverable` + `recommended_action`; the accepted / preflight / executed / verified / saved state vocabulary; document pinning against the active document; evidence files with SHA-256 | README acknowledgements |
| puran-water/autocad-mcp (`autocad-mcp-main4`) | MIT | **Idea recorded, not built** | AutoLISP file-IPC backend for AutoCAD LT (documented as a future backend); golden-DXF test fixtures | README acknowledgements (if/when built) |
| LokmenoWer/best-cad-mcp (`best-cad-mcp-master`) | MIT | **Observation used** | Confirmation that MCP SDK v2 runs sync handlers on worker threads, which COM must account for; tool annotations; include/exclude tool lists | README acknowledgements |
| thewisekape/autocad-mcp (`autocad-mcp`) | Apache-2.0 (+NOTICE) | **Ideas only** | QC check list (zero-length geometry, duplicates, layer standards); bulk operations by filter | README acknowledgements; no NOTICE obligation because no code or NOTICE text is redistributed |
| AnCode666/multiCAD-mcp (`multiCAD-mcp-main`) | Apache-2.0 | **Idea recorded, not built** | ProgID table for other COM-compatible CADs (ZWCAD, GstarCAD, BricsCAD) -- documented as untested | -- |
| Psalmustrack/lambdacad-mcp | Apache-2.0 (+NOTICE) | **Ideas only** | One batch = one undo group; verification by measurement rather than screenshots; "every reply names the drawing that answered" | README acknowledgements |
| bimwright/dwg-mcp (`dwg-mcp-master`) | Apache-2.0 | **Design input** for a future .NET backend | Per-start auth token on a loopback listener; refusing LISP execution | -- |
| Jjo37/new-acad (`new-acad-main`) | MIT | **Idea only** | Budget-capped drawing summary with an explicit truncation marker | README acknowledgements |
| xstaar/autocad-mcp (`autocad-mcp-master`) | **Proprietary** ("may NOT create derivative works") | **Rejected** | Nothing | -- |
| paulseongminpark/autocad-mcp "CAD OS" (`autocad-mcp-13`) | **Proprietary** | **Rejected**; not read beyond README/LICENSE | Nothing | -- |
| andagni/autocad-mcp (`autocad-mcp-3`, Rust) | GPL-3.0 | **Rejected** (reciprocal); not read beyond README | Nothing | -- |
| Igualguana/AUTOCAD-ELECTRICAL-MCP | AGPL-3.0 | **Rejected** (reciprocal, network clause) | Nothing | -- |
| 26 repositories with no licence file (incl. `Easy-MCP-AutoCad-main`, `cad-mcp`, `AEC-Agent`, `NXChieu-Autocad-MCP`) | none | **Rejected for code**; no idea taken that is not common CAD practice | Nothing | -- |
| Other MIT / Apache-2.0 repositories read at `skim` or `inventory-only` depth | MIT / Apache-2.0 | Not used | Nothing | -- |

## Dependency licences

| Dependency | Licence | Status |
|---|---|---|
| `mcp` (MCP Python SDK) | MIT | existing |
| `pywin32` | PSF | existing |
| `ezdxf` | MIT | **new, optional** (`pip install -e ".[dxf]"`) |
| `matplotlib` | PSF-based (matplotlib licence) | optional, only for headless PNG/PDF rendering; not installed on the development machine, so rendering is reported as unavailable there |
| `pytest` | MIT | dev only |

## Rules for future contributions

- Before bringing in anything from another repository, read its top-level
  licence file (not the README badge) and record the decision in this file.
- MIT / Apache-2.0 / BSD: allowed with the original copyright and permission
  notice kept next to the code (and Apache NOTICE text carried forward).
- GPL / AGPL / LGPL / proprietary / no licence: do not copy code, tests,
  docs or data from them.
- Prefer reimplementing documented behaviour, and say where the idea came from.
