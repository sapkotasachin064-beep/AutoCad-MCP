# Feature matrix (reference analysis)

Compares this project as it stood at commit `3cf9254` (V0.2.3, the baseline of
this rebuild) against the reference codebases that were read in depth. See
[`repository-inventory.md`](repository-inventory.md) for how each repository
was identified and how deeply it was read.

## Legend

| Mark | Meaning |
|---|---|
| **V** | Verified: the implementing code was read during this audit |
| **C** | Claimed in the repo's own docs and a matching module exists; code not read here |
| **D** | Claimed in docs/README only |
| **-** | Not found |
| **n/a** | Does not apply to that architecture |

"Verified" means the implementation was read, **not** that it was run: no
reference repository's code or tests were executed. Target (baseline) entries
are verified by reading this repo's code and running its test suite (85 passed,
11 live-AutoCAD tests skipped because AutoCAD was not running).

## Verified comparison (deep / medium codebases)

Columns: **T** = this project at baseline V0.2.3; **U** = U-C4N AutoCAD MCP
Pro 1.6.0 (F1); **P** = puran-water (F2 root); **B** = beiming183-cloud
AutoCAD-MCP 4.0 (F2 rewrite); **L** = LokmenoWer best-cad-mcp 1.7.2;
**W** = thewisekape autocad-mcp 5.0; **M** = AnCode666 multiCAD-mcp;
**λ** = lambdacad-mcp; **G** = bimwright dwg-mcp.

| Capability | T | U | P | B | L | W | M | λ | G |
|---|---|---|---|---|---|---|---|---|---|
| Live full AutoCAD over COM | V | V | - | V | V | C | V | - | - |
| AutoCAD LT via AutoLISP file IPC | - | - | V | V | - | C | - | D (BricsCAD) | - |
| Headless DXF backend (ezdxf) | - | C | C | C | - | C | - | - | - |
| In-process .NET plugin channel | - | - | - | C | - | - | - | - | D |
| Backend chosen explicitly, never silently swapped | n/a | - (falls back to ezdxf, per docs) | - (falls back to ezdxf, V) | ? | n/a | - (fallback chain, D) | n/a | n/a | n/a |
| Dedicated COM/STA worker thread + per-call timeout | - | V | n/a | V | V (async facade on loop thread) | ? | ? | n/a | n/a |
| Cross-process COM turn mutex | - | - | - | V | - | - | - | - | - |
| Machine-readable capability map + typed refusal | - | V | partial V | partial | ? | partial | - | - | ? |
| Stable error codes with recovery hint | - | partial V | - | V | ? | - | ? | D | ? |
| Error text actually reaches the MCP client | **- (defect D1)** | V | V | V | V (wrapper) | ? | ? | ? | ? |
| Idempotency journal for mutations | - | - | - | V | - | - | - | - | - |
| Drawing identity reported per result | V | partial V | - | V | ? | - | - | D | - |
| Document pinning / revision fencing | - | partial V (scope reset) | - | V (leases) | ? | - | - | D (warns on change) | - |
| One undo group per operation / rollback | - | V (UNDO Mark + group) | partial V (undo op) | C | ? | ? | ? | D | D (transactions) |
| Output path allow-list / traversal guard | - | V | - | partial V | ? | - | - (`allow_arbitrary_paths: true`) | - | ? |
| Raw command / LISP / code execution | - (not exposed) | V guarded, opt-in | V unguarded | C | C guarded | C | ? | D by design | D (LISP refused) |
| Lines, polylines, circles, text | V | C | V | C | C | C | V | D | D |
| Arcs, ellipses, MTEXT, splines | partial (MTEXT internal) | C | V | C | C | C | C | D | D |
| Dimensions / leaders | - | C | V | C | C | C | ? | D | D |
| Hatch | - | C | V | C | C | C | ? | D | ? |
| Blocks and attributes | - | C | V | C | C | C | C | D | ? |
| Layer create / properties / state | partial V | C | V | C | C | C | C | D | D |
| Layouts, viewports, paper space | - | C | - | C | C | C | ? | D | ? |
| PDF plot with output verification | - | V | partial V | C | C | C | ? | D | - |
| DXF / DWG export | partial (DWG save in test tool) | C | V | V (with export checks) | C | C | ? | D | ? |
| Screenshot / render evidence | - | C | V | V (path + SHA-256, D) | C | C | ? | D | ? |
| Entity query with filters / pagination | partial V | C | partial V | C | C | C | ? | D | D |
| Scan to SQLite + read-only SQL | V | - | - | - | C | - | - | - | - |
| Drawing QC / validation report | - | C | - | V (delivery checks) | C | D | - | D | - |
| Walls / doors / windows | V | C | - | - | ? | - | - | - | - |
| Floor-plan generation | V (fixed 2x3 grid) | C (`arch_plan_from_spec`) | - | - | ? | - | - | - | - |
| Room areas computed from geometry | - | C | - | - | ? | - | - | - | - |
| Stairs (rule-of-thumb check) | - | C (Blondel, not a code check) | - | - | - | - | - | - | - |
| Structural grid / columns | - | C (`arch_grid`) | - | - | - | - | - | - | - |
| Schedules / tables | - | C | - | - | ? | D | - | - | - |
| Sheet frame / title block | - | C | - | - | ? | D | - | D | - |
| Quantity takeoff | - | C (pipe/cable) | - | - | - | D (BOM) | - | - | - |
| P&ID | - | C | V | C | - | C | - | - | - |
| Electrical | - | C (cable takeoff) | - | - | - | D (NEC calcs) | - | - | - |
| Civil 3D objects | - | - | - | - | - | - | - | - | - |
| Drawing diff / revision compare | - | C | - | - | ? | - | - | - | - |
| Batch drawing in one call | partial (floor-plan macro) | C (`cad_batch`) | - | - | ? | D | V (shorthand) | D (one undo group) | D |
| Tool profiles / packs / search discovery | - | V (config) | - (8 op-dispatch tools) | - | V (lean/full, include/exclude) | - | - | - | D (toolsets, `--read-only`) |
| MCP tool annotations (read-only/destructive hints) | - | ? | partial V | ? | V | ? | ? | ? | ? |
| Test files (not run here) / CI workflows | 8 / 0 | 178 / 4 | 3 / 0 | 22 / 1 | 37 / 1 | 8 / 0 | 6 / 0 | 2 / 0 | 87 / 1 |

Civil 3D domain objects (surfaces, alignments, corridors) appear only in
codebases read at `skim` depth -- `new-acad-main` (C# plugin, TCP JSON-RPC),
`MCP_AutocadMap3D` (C# plugin, named pipe), `cad-mcp` (Roslyn C# execution),
`autocad-mcp-ultra` -- and are therefore listed as **D** in
[`gap-analysis.md`](gap-analysis.md), not as verified prior art.

## Heuristic evidence matrix (all AutoCAD codebases)

Number of source files whose text matches a domain keyword pattern
(`.` = zero). Identical copies (`Autocad-MCP-19`, `autocad_mcp_pro-1.6.0`,
`autocad-mcp-main-2`, `autocad-mcp-11`) are omitted. **These are keyword hits,
not capabilities**: `dim` matches any file mentioning "dimension", `exec`
matches `exec(`/`eval(` in any form, and so on. Use them to decide what to read
next, never as proof that a feature works.

| folder | wall | room | stair | struct | hatch | dim | block | xref | layout | plot | dxf | shot | undo | select | 3d | table | title | qty | elec | plumb | pid | civil | survey | audit | diff | exec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `AEC-Agent` | 42 | 53 | 9 | 14 | 13 | 41 | 8 | 1 | 5 | 35 | 8 | 19 | 16 | 3 | . | 12 | 9 | 3 | 66 | 58 | 40 | 16 | 3 | 2 | 23 | 1 |
| `AUTOCAD-ELECTRICAL-MCP-main` | . | . | . | . | . | 2 | 3 | . | 4 | . | 1 | 1 | . | 1 | 1 | . | . | 1 | 29 | . | . | . | . | . | . | 1 |
| `AutoCAD-MCP-1` | . | . | . | . | 2 | 5 | 9 | . | 1 | 1 | 3 | 1 | . | 1 | . | . | . | . | . | . | . | 1 | . | . | . | . |
| `AutoCAD-MCP-10` | 8 | 3 | . | . | 1 | 2 | . | . | 3 | 1 | 2 | 1 | . | . | 2 | . | . | 7 | . | . | . | 1 | . | . | . | 1 |
| `AutoCAD-MCP-Server` | . | . | . | . | 4 | 9 | . | . | 4 | 5 | 11 | 12 | 7 | 2 | . | . | . | . | 2 | . | 11 | 1 | . | 5 | . | 4 |
| `AutoCAD-MCP-main-1` | . | . | . | . | 11 | 23 | 1 | . | 5 | 18 | 23 | 21 | 16 | 3 | 2 | 1 | 1 | . | 4 | 8 | 12 | 6 | 4 | 17 | 15 | 4 |
| `AutoCAD_MCP` | . | . | . | . | . | . | . | . | 1 | . | 1 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `AutoCAD_MCP_archive-main` | 2 | 2 | . | . | 2 | 20 | 1 | . | 26 | 3 | . | 3 | 9 | 7 | 5 | 1 | 2 | . | . | 1 | . | 16 | . | 2 | 7 | 11 |
| `AutoCad-MCP-6` | . | . | . | . | 3 | 3 | . | . | 1 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `AutoCadMcp-main` | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `Autocad-MCP-15` | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `Autocad-MCP-16` | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `Autocad-MCP-17` | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `Autocad-MCP-18` | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `Autocad-MCP-main` | 75 | 51 | 27 | 7 | 63 | 110 | 4 | 17 | 110 | 46 | 133 | 41 | 46 | 8 | 1 | 18 | 44 | 32 | 24 | 41 | 77 | 52 | 24 | 22 | 16 | 8 |
| `BimOnMcp-main` | 1 | 2 | . | . | . | 2 | 1 | . | 2 | . | . | . | 4 | 1 | . | 2 | . | . | 1 | 5 | . | 3 | . | . | . | 1 |
| `CADx` | 1 | 1 | . | . | . | 1 | . | . | 4 | 5 | . | . | . | 1 | . | . | . | . | . | . | . | . | . | . | 3 | 4 |
| `CadBridge` | . | . | . | . | . | 1 | . | . | 1 | . | . | . | 7 | 3 | . | . | . | . | . | 4 | 2 | 5 | 1 | 3 | 1 | 1 |
| `Codex-Integration-with-Creative-Industry-Software` | . | . | . | . | 4 | 10 | . | . | 2 | 7 | 16 | 29 | 4 | 1 | . | . | . | . | . | 1 | . | 1 | . | . | 1 | . |
| `DeepBIM-MCP-Autocad-Plugin-main` | . | . | . | . | . | . | 1 | . | 2 | 1 | 3 | . | 24 | . | . | . | . | . | . | . | . | . | 1 | . | . | . |
| `Easy-MCP-AutoCad-main` | . | . | . | . | . | . | . | . | . | 1 | 2 | . | . | 2 | . | . | . | . | . | . | . | . | . | . | . | 1 |
| `MCP_AutocadMap3D` | 1 | . | . | . | 7 | 19 | 7 | 4 | 20 | 7 | 32 | 4 | 54 | 3 | 9 | . | . | . | . | 11 | . | 29 | 30 | 5 | . | . |
| `NXChieu-Autocad-MCP` | 4 | 4 | . | . | 11 | 19 | 14 | . | 11 | 8 | 19 | 18 | 8 | 3 | . | . | . | . | 2 | . | 11 | 1 | . | 5 | . | 6 |
| `acad-mcp-loop` | . | . | . | . | . | . | . | . | 3 | 3 | . | 3 | 4 | . | . | . | . | . | . | 5 | . | . | . | . | 1 | . |
| `autocad-ai-mcp` | 10 | 8 | 7 | 1 | 5 | 13 | 5 | . | 6 | 10 | 9 | 4 | . | . | . | 1 | 2 | 3 | 1 | 5 | . | 3 | . | 7 | . | 1 |
| `autocad-com-mcp` | . | . | . | . | . | . | . | . | 2 | 3 | 2 | . | . | 2 | . | . | . | . | . | . | . | . | . | . | . | . |
| `autocad-mac-mcp` | . | . | . | . | 1 | . | . | . | . | 1 | 1 | 1 | 1 | 1 | . | . | . | . | . | . | . | . | . | . | . | 1 |
| `autocad-mcp` | 1 | 1 | . | . | 7 | 13 | 1 | 6 | 9 | 8 | 14 | 11 | 8 | 3 | . | 4 | 6 | . | 7 | 3 | 13 | 3 | . | 8 | . | 4 |
| `autocad-mcp-12` | 2 | . | . | . | . | . | . | . | . | 2 | . | . | . | . | . | . | . | . | . | . | . | 1 | . | . | . | . |
| `autocad-mcp-13` | 108 | 23 | 1 | 4 | 73 | 85 | 69 | 26 | 69 | 17 | 81 | 6 | 20 | 3 | 17 | 2 | 4 | 3 | 12 | 24 | 23 | 103 | 43 | 56 | 88 | 8 |
| `autocad-mcp-14` | 2 | . | . | . | 6 | 4 | 5 | 1 | 2 | 4 | 1 | . | 2 | . | . | . | . | . | . | 1 | . | 1 | . | 6 | . | 4 |
| `autocad-mcp-2` | 26 | 19 | . | . | 2 | 14 | 5 | 1 | 12 | 1 | 3 | 2 | 2 | 12 | . | . | . | . | 12 | 2 | . | 6 | . | 2 | . | 1 |
| `autocad-mcp-3` | 6 | . | . | . | 5 | 30 | 6 | 74 | 52 | 50 | 59 | 57 | 16 | 6 | 1 | 3 | 50 | . | . | 4 | 9 | 31 | 27 | 8 | 4 | 1 |
| `autocad-mcp-4` | . | . | . | . | . | 2 | 2 | . | 2 | 2 | 3 | 2 | . | . | . | . | . | 1 | . | . | . | 1 | . | . | . | . |
| `autocad-mcp-5` | . | . | . | . | 7 | 18 | 11 | 1 | 14 | 15 | 18 | 7 | 11 | 7 | . | . | 4 | . | . | 7 | 4 | 2 | 1 | 10 | . | 3 |
| `autocad-mcp-7` | 1 | 1 | . | 1 | . | 1 | . | . | . | . | . | . | 1 | . | . | . | . | . | 1 | 1 | . | . | . | . | . | . |
| `autocad-mcp-8` | 2 | 4 | . | . | 3 | 4 | . | . | 1 | 3 | 8 | 7 | 1 | 1 | . | 1 | 2 | . | 1 | . | . | 5 | 1 | 2 | . | 3 |
| `autocad-mcp-9` | 2 | 1 | . | 3 | 1 | 8 | 4 | . | 3 | . | 2 | . | . | 4 | . | 1 | . | . | . | . | . | 3 | . | . | . | . |
| `autocad-mcp-main4` | . | . | . | . | 4 | 9 | . | . | 4 | 5 | 10 | 10 | 6 | 2 | . | . | . | . | 2 | . | 11 | . | . | 5 | . | 4 |
| `autocad-mcp-master` | 5 | 2 | 4 | 1 | 4 | 5 | . | . | 2 | 2 | 3 | . | . | . | . | 1 | 1 | . | . | 1 | . | 4 | . | 1 | . | 2 |
| `autocad-mcp-server-1` | 1 | 1 | . | 1 | . | 1 | . | . | . | . | . | . | 1 | . | . | . | . | . | 1 | 1 | . | . | . | . | . | . |
| `autocad-mcp-server-2` | . | . | . | . | . | 4 | . | . | . | 3 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `autocad-mcp-server-3` | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `autocad-mcp-server-main` | 1 | 1 | . | 1 | . | 1 | . | . | . | . | . | . | 1 | . | . | . | . | . | 1 | 1 | . | . | . | . | . | . |
| `autocad-mcp-server1` | . | . | . | . | . | . | . | . | . | 1 | 1 | . | . | 1 | . | . | . | . | . | . | . | . | . | . | . | . |
| `autocad-mcp-ultra` | 10 | 1 | . | . | 26 | 51 | 11 | 2 | 69 | 10 | 36 | 85 | 180 | 7 | 13 | 4 | 11 | . | 2 | 8 | 12 | 236 | 28 | 14 | 8 | 8 |
| `autocad-tarch-mcp` | . | . | . | . | 6 | 7 | 1 | . | 7 | 4 | 10 | . | 1 | 4 | . | . | . | . | . | 2 | 1 | 1 | 2 | . | . | 4 |
| `autocad-trimble-mcp` | . | . | . | . | 3 | 4 | 3 | . | 4 | 3 | 2 | . | . | 1 | . | . | . | . | . | 3 | . | 2 | . | 2 | . | 2 |
| `autocad_mcp-1` | . | . | . | . | . | 4 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | 1 | . | . | . |
| `autocadplant3d-mcp` | . | . | . | . | 4 | 11 | . | . | 6 | 13 | 10 | 10 | 6 | 3 | . | 13 | 2 | 2 | 2 | 20 | 37 | 3 | 1 | 5 | . | 4 |
| `best-cad-mcp-master` | 8 | 5 | 2 | 2 | 18 | 32 | 10 | 7 | 16 | 13 | 9 | 10 | 14 | 5 | 2 | 4 | 9 | 1 | 4 | 1 | . | 15 | 8 | 12 | 2 | 3 |
| `cad-mcp` | 4 | . | . | . | 1 | 1 | 1 | . | 1 | . | 1 | 2 | 25 | . | . | 2 | . | . | 4 | 57 | . | 35 | . | 3 | . | . |
| `cadplot-mcp` | 1 | 3 | 1 | 1 | 2 | 12 | 7 | 3 | 37 | 55 | 5 | 13 | 14 | . | . | . | 6 | . | . | 17 | . | 8 | 1 | 38 | . | 2 |
| `dwg-mcp-master` | 2 | 3 | . | 1 | 3 | 20 | 10 | . | 35 | 1 | 6 | 21 | 61 | . | . | . | . | . | . | 14 | 1 | 17 | 2 | 10 | . | 14 |
| `greenloom_CAD_MCP` | . | . | . | . | 4 | 9 | . | . | 4 | 5 | 10 | 10 | 6 | 2 | . | . | . | . | 2 | . | 11 | . | . | 5 | . | 4 |
| `lambdacad-mcp` | 2 | 2 | . | . | 1 | 3 | 2 | . | 2 | 2 | 2 | 3 | 2 | 3 | . | . | 3 | 2 | 2 | . | 1 | . | 1 | 1 | 1 | 3 |
| `mcp-autocad-api` | . | . | . | . | . | 2 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | 1 |
| `mcp-connector-skills` | . | . | . | . | . | . | . | . | . | 1 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| `multiCAD-mcp` | 3 | 4 | 1 | 1 | 5 | 14 | 2 | . | 4 | 1 | 10 | 6 | 4 | 11 | . | 1 | . | 2 | 1 | 5 | . | 2 | 2 | 1 | 1 | 2 |
| `multiCAD-mcp-main` | 3 | 3 | . | . | 5 | 11 | 2 | . | 2 | 1 | 10 | 4 | 4 | 11 | . | 1 | . | . | . | 4 | . | 2 | . | 1 | . | . |
| `new-acad-main` | 4 | . | . | . | 18 | 12 | 5 | 4 | 23 | 27 | 49 | 17 | 58 | 1 | 1 | 1 | 12 | 17 | . | 41 | 2 | 108 | 31 | 16 | 4 | 5 |
| `vn-autocad-claude` | . | . | . | . | 4 | 9 | . | . | 4 | 5 | 10 | 10 | 6 | 2 | . | . | . | . | 2 | . | 11 | . | . | 5 | . | 4 |

