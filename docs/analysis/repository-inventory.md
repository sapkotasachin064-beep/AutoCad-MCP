# Repository inventory (reference collection)

Reference analysis only. Nothing in this folder describes this project's own
implementation -- see `docs/architecture.md` for that.

- **Collection root:** `%USERPROFILE%\Desktop\AutoCads Mcp Servers` (read-only; nothing in it was modified or executed).
- **Scan date:** 2026-10-16.
- **Machine-readable version:** [`repository-inventory.json`](repository-inventory.json) (same data plus per-repo branch, commit, line counts per language, backend/domain marker hits).

## How the inventory was built

| Step | Method | What it proves |
|---|---|---|
| Discovery | Directory listing + `.git` detection, including the nested `not-autocad-mcp/` folder | 83 repositories: 66 git clones (52 top level + 14 under `not-autocad-mcp/`) and 17 extracted archives (no `.git`) |
| Identity | Clones: `origin` URL read from `.git/config`. Archives: upstream named in README / pyproject / package.json, checked by hand | Folder names are **not** identities (e.g. `autocad-mcp-main4` is puran-water, `Autocad-MCP-19` is U-C4N) |
| Branch / commit | `.git/HEAD` + refs read as files (no git process) | All clones are shallow (`--depth 1`) |
| Dirty state | `git --no-optional-locks -c core.fsmonitor=false status --porcelain` (does not write the index) | All clones clean except `acad-mcp-loop` (1 modified file, `LoopHost/LoopHost.csproj`) |
| License | First 700 bytes of the top-level `LICENSE`/`COPYING` file | `NONE` means no top-level license file: all rights reserved by default |
| Forks / duplicates | SHA-1 of CRLF-normalised source files, Jaccard overlap | Git clones are checked out with CRLF and archives with LF, so raw hashes under-report forks; normalised hashes are used |
| Markers | Regex hits over source files (MCP SDK, backend, domain keywords) | **Triage indicators only.** A hit means a keyword appears, not that a feature works |
| Inspection depth | Manual reading, recorded per repo | `deep`/`medium` findings are cited as implementation evidence; `skim` = README/LICENSE level; `inventory-only` = automated scan only |

Nothing in the collection was installed, built, or run. No test suite from a
reference repository was executed, so no reference test result is claimed.

## Summary

| | Count |
|---|---|
| Repositories discovered | 83 |
| AutoCAD/DWG-related (top level) | 69 |
| Not AutoCAD (`not-autocad-mcp/`: SolidWorks, FreeCAD, SketchUp, NX, Inventor, ...) | 14 |
| Empty or README-only | 4 (`HHH`, `autocad-mcp-server-4`, `cadbridge-autocad-mcp-server`, `mcp-connector-skills` has skills only) |
| Inspected `deep` (implementation code read) | 3 distinct codebases (U-C4N, puran-water, beiming183) + 4 hash-identical copies |
| Inspected `medium` | 8 |
| Inspected `skim` | 17 |
| Inventory-only (automated scan) | 51 |

### License mix (top-level license file)

| License | Repos |
|---|---|
| MIT | 40 |
| Apache-2.0 | 10 |
| GPL-3.0 | 2 (`autocad-mcp-3` andagni/autocad-mcp, `not-autocad-mcp/Siemens_NX_File_Renamer`) |
| AGPL-3.0 | 2 (`AUTOCAD-ELECTRICAL-MCP-main`, `not-autocad-mcp/sketchup-mcp-server`) |
| Proprietary | 2 (`autocad-mcp-master` xstaar, `autocad-mcp-13` paulseongminpark "CAD OS") |
| Custom / other | 1 (`not-autocad-mcp/SwpilotCLI`) |
| No license file | 26 |

### Fork and duplicate families (hash-verified)

| Family | Members | Relationship |
|---|---|---|
| F1 U-C4N "AutoCAD MCP Pro" v1.6.0 | `Autocad-MCP-19` (clone), `Autocad-MCP-main` (zip), `autocad_mcp_pro-1.6.0` (PyPI sdist) | 373/373 source files identical: one codebase, counted once |
| F2 puran-water lineage | root `autocad-mcp-main4`; identical copies `autocad-mcp-main-2` (ks40-academy), `autocad-mcp-11` (MuriloM676) | 18/18 identical |
| | derivatives: `vn-autocad-claude` (61% shared), `AutoCAD-MCP-Server` (61%), `autocad-mcp` thewisekape (NOTICE credits it), `NXChieu-Autocad-MCP` (superset), `autocadplant3d-mcp` (78%), `greenloom_CAD_MCP` (22%), `AutoCAD-MCP-main-1` beiming183 (heavily rewritten, same LICENSE line) | |
| F3 multiCAD | root `multiCAD-mcp-main` (AnCode666); `multiCAD-mcp` (ewuiyud) | modified fork, Jaccard 0.52 |
| F4 codesknight | `AutoCAD-MCP-1` | every file also in `NXChieu-Autocad-MCP` |
| F5 Easy-MCP | root `Easy-MCP-AutoCad-main` (zh19980811); `autocad-mcp-server1` | 4/4 files from the root |
| F6 architectural server | `autocad-mcp-server-1` (AntiApus), `autocad-mcp-server-main` (archive, README placeholder) | same structure, small diffs; the archive may be thepiruthvirajan/autocad-mcp-server -- unverified |

After removing identical copies, the collection holds **77 distinct codebases**
(83 - 2 extra F1 copies - 2 extra F2 copies - 2 empty folders).

## Research leads from the task brief

| Lead | Local folder | Verified? |
|---|---|---|
| puran-water/autocad-mcp | `autocad-mcp-main4` | yes (README clone URL), `deep` |
| U-C4N/Autocad-MCP | `Autocad-MCP-19`, `Autocad-MCP-main`, `autocad_mcp_pro-1.6.0` | yes (git remote, badges), `deep` |
| AnCode666/multiCAD-mcp | `multiCAD-mcp-main` (+ fork `multiCAD-mcp`) | yes (README, pyproject), `medium` |
| thepiruthvirajan/autocad-mcp-server | possibly `autocad-mcp-server-main` | **unverified** -- archive names no upstream |
| beiming183-cloud/AutoCAD-MCP | `AutoCAD-MCP-main-1` | yes (badges, pyproject), `deep` |
| LokmenoWer/best-cad-mcp | `best-cad-mcp-master` | yes (README, pyproject), `medium` |
| Jjo37/new-acad | `new-acad-main` | partly (LICENSE holder "Jjo"; archive names no repo URL), `skim` |
| xstaar/autocad-mcp | `autocad-mcp-master` | yes (README), `medium` (license read: proprietary) |
| thewisekape/autocad-mcp | `autocad-mcp` | yes (git remote), `medium` |
| Psalmustrack/lambdacad-mcp | `lambdacad-mcp` | yes (git remote), `medium` |

## All repositories

`lines` = non-blank-agnostic newline count over recognised source files
(`.py .ts .js .cs .lsp .rs ...`), vendored/build folders excluded. `tests` =
files named like tests. `family` = fork family above.

| folder | identity | kind | language | lines | license | tests | family | depth |
|---|---|---|---|---|---|---|---|---|
| `AEC-Agent` | jabluetooth/AEC-Agent | clone | Python | 99,698 | NONE | 39 | - | inventory-only |
| `AUTOCAD-ELECTRICAL-MCP-main` | Igualguana/AUTOCAD-ELECTRICAL-MCP (README clone URL) | archive | Python | 11,226 | AGPL-3.0 | 2 | - | skim |
| `AutoCAD-MCP-1` | codesknight/AutoCAD-MCP | clone | Python | 2,985 | MIT | 8 | F4 codesknight | inventory-only |
| `AutoCAD-MCP-10` | rhtmdgks/AutoCAD-MCP | clone | Python | 4,046 | NONE | 2 | - | inventory-only |
| `AutoCAD-MCP-Server` | StreetParkourZombie/AutoCAD-MCP-Server | clone | Python | 7,847 | MIT | 7 | F2 puran-water lineage | inventory-only |
| `AutoCAD-MCP-main-1` | beiming183-cloud/AutoCAD-MCP (README badges, pyproject UR... | archive | Python | 30,775 | MIT | 22 | F2 puran-water lineage | deep |
| `AutoCAD_MCP` | qq7995516/AutoCAD_MCP | clone | C# | 1,741 | NONE | 0 | - | inventory-only |
| `AutoCAD_MCP_archive-main` | ACKaraca/AutoCAD_MCP archive (README banner) | archive | Python | 63,346 | MIT | 43 | - | skim |
| `AutoCad-MCP-6` | Porta048/AutoCad-MCP | clone | Python | 2,650 | MIT | 0 | - | inventory-only |
| `AutoCadMcp-main` | unverified (README names no upstream; C# AutoCADMcpPlugin) | archive | C# | 472 | NONE | 0 | - | skim |
| `Autocad-MCP-15` | lfisher7401/Autocad-MCP | clone | Python | 221 | MIT | 1 | - | inventory-only |
| `Autocad-MCP-16` | mehmetsharma372/Autocad-MCP | clone | Python | 95 | MIT | 1 | - | inventory-only |
| `Autocad-MCP-17` | kazukim9869/Autocad-MCP | clone | Python | 165 | MIT | 1 | - | inventory-only |
| `Autocad-MCP-18` | malialvarez481/Autocad-MCP | clone | Python | 123 | MIT | 1 | - | inventory-only |
| `Autocad-MCP-19` | U-C4N/Autocad-MCP | clone | Python | 134,104 | MIT | 178 | F1 U-C4N AutoCAD MCP Pro | deep |
| `Autocad-MCP-main` | U-C4N/Autocad-MCP (README badges, pyproject URLs) | archive | Python | 134,340 | MIT | 178 | F1 U-C4N AutoCAD MCP Pro | deep |
| `BimOnMcp-main` | General-Soju/BimOnMcp (README) | archive | C# | 5,161 | MIT | 0 | - | skim |
| `CADx` | FuxuanNet/CADx | clone | Python | 4,466 | NONE | 9 | - | skim |
| `CadBridge` | moshouhot/CadBridge | clone | Python | 10,436 | NONE | 1 | - | inventory-only |
| `Codex-Integration-with-Creative-Industry-Software` | newvision798/Codex-Integration-with-Creative-Industry-Sof... | clone | Python | 26,666 | MIT | 43 | - | skim |
| `DeepBIM-MCP-Autocad-Plugin-main` | unverified (README names no upstream) | archive | C# | 4,013 | NONE | 0 | - | skim |
| `Easy-MCP-AutoCad-main` | zh19980811/Easy-MCP-AutoCad (target README cites it as V0... | archive | Python | 2,031 | NONE | 3 | F5 Easy-MCP lineage | skim |
| `HHH` | harishgatholiya-rgb/HHH | clone | - | 0 | NONE | 0 | - | inventory-only |
| `MCP_AutocadMap3D` | seb21-art/MCP_AutocadMap3D | clone | C# | 37,141 | MIT | 4 | - | skim |
| `NXChieu-Autocad-MCP` | hoangchieu91/NXChieu-Autocad-MCP | clone | Python | 14,473 | NONE | 12 | F2 puran-water lineage | skim |
| `acad-mcp-loop` | lianzheduohuanxi/acad-mcp-loop | clone | C# | 8,927 | MIT | 0 | - | inventory-only |
| `autocad-ai-mcp` | haianhdskt-boop/autocad-ai-mcp | clone | Python | 5,711 | NONE | 2 | - | inventory-only |
| `autocad-com-mcp` | ey2h/autocad-com-mcp | clone | Python | 1,402 | MIT | 0 | - | inventory-only |
| `autocad-mac-mcp` | medjbilou/autocad-mac-mcp | clone | Python | 543 | MIT | 0 | - | inventory-only |
| `autocad-mcp` | thewisekape/autocad-mcp | clone | Python | 20,804 | Apache-2.0 | 8 | F2 puran-water lineage | medium |
| `autocad-mcp-11` | MuriloM676/autocad-mcp | clone | Python | 5,828 | MIT | 3 | F2 puran-water lineage | deep |
| `autocad-mcp-12` | Aaradhya-Dev-Tamrakar/autocad-mcp | clone | Python | 498 | NONE | 1 | - | inventory-only |
| `autocad-mcp-13` | paulseongminpark/autocad-mcp | clone | Python | 224,528 | PROPRIETARY | 253 | - | skim |
| `autocad-mcp-14` | lucasqdn/autocad-mcp | clone | Python | 5,862 | NONE | 8 | - | inventory-only |
| `autocad-mcp-2` | moisesbritez92/autocad-mcp | clone | TypeScript | 10,765 | NONE | 0 | - | inventory-only |
| `autocad-mcp-3` | andagni/autocad-mcp | clone | Rust | 207,425 | GPL-3.0 | 0 | - | skim |
| `autocad-mcp-4` | Slacker-LLC/autocad-mcp | clone | Python | 3,230 | Apache-2.0 | 1 | - | inventory-only |
| `autocad-mcp-5` | C48H74/autocad-mcp | clone | Python | 8,887 | MIT | 19 | - | inventory-only |
| `autocad-mcp-7` | PeterPerez01/autocad-mcp | clone | Python | 1,713 | MIT | 0 | - | inventory-only |
| `autocad-mcp-8` | id0o0bi/autocad-mcp | clone | Python | 2,300 | MIT | 0 | - | inventory-only |
| `autocad-mcp-9` | Roy-y111/autocad-mcp | clone | Python | 4,547 | MIT | 0 | - | inventory-only |
| `autocad-mcp-main-2` | ks40-academy/autocad-mcp (README clone URL; Vietnamese co... | archive | Python | 5,828 | MIT | 3 | F2 puran-water lineage | deep |
| `autocad-mcp-main4` | puran-water/autocad-mcp (README clone URL) | archive | Python | 5,828 | MIT | 3 | F2 puran-water lineage | deep |
| `autocad-mcp-master` | xstaar/autocad-mcp (README) | archive | TypeScript | 3,179 | PROPRIETARY | 0 | - | medium |
| `autocad-mcp-server-1` | AntiApus/autocad-mcp-server | clone | Python | 1,843 | Apache-2.0 | 1 | F6 AntiApus architectural server | inventory-only |
| `autocad-mcp-server-2` | ranvirw18/autocad-mcp-server | clone | Python | 710 | MIT | 3 | - | inventory-only |
| `autocad-mcp-server-3` | vigneshpbmenon/autocad-mcp-server | clone | Python | 91 | MIT | 0 | - | inventory-only |
| `autocad-mcp-server-4` | nMetaloumin/autocad-mcp-server | clone | - | 0 | NONE | 0 | - | inventory-only |
| `autocad-mcp-server-main` | unverified (README placeholder URL; variant of AntiApus/a... | archive | Python | 1,840 | Apache-2.0 | 1 | F6 variant of AntiApus architectural server | medium |
| `autocad-mcp-server1` | hoangduong06052001/autocad-mcp-server1 | clone | Python | 1,161 | NONE | 0 | F5 Easy-MCP lineage | inventory-only |
| `autocad-mcp-ultra` | CaeliaEve/autocad-mcp-ultra | clone | C# | 103,208 | MIT | 9 | - | skim |
| `autocad-tarch-mcp` | unicronsmith/autocad-tarch-mcp | clone | Python | 6,683 | NONE | 0 | - | inventory-only |
| `autocad-trimble-mcp` | xuantinhnbs-rgb/autocad-trimble-mcp | clone | Python | 8,093 | MIT | 5 | - | skim |
| `autocad_mcp-1` | niaoAs2O3/autocad_mcp | clone | Python | 1,058 | NONE | 0 | - | inventory-only |
| `autocad_mcp_pro-1.6.0` | U-C4N/Autocad-MCP v1.6.0 PyPI sdist (PKG-INFO) | archive | Python | 134,340 | MIT | 178 | F1 U-C4N AutoCAD MCP Pro | deep |
| `autocadplant3d-mcp` | Romeraaa/autocadplant3d-mcp | clone | Python | 30,150 | MIT | 36 | F2 puran-water lineage | skim |
| `best-cad-mcp-master` | LokmenoWer/best-cad-mcp (README, pyproject) | archive | Python | 60,409 | MIT | 37 | - | medium |
| `cad-mcp` | shtirlitsDva/cad-mcp | clone | C# | 16,729 | NONE | 31 | - | skim |
| `cadbridge-autocad-mcp-server` | dimitrovakulenko/cadbridge-autocad-mcp-server | clone | - | 0 | NONE | 0 | - | inventory-only |
| `cadplot-mcp` | agadraphy/cadplot-mcp | clone | Python | 61,270 | MIT | 65 | - | medium |
| `dwg-mcp-master` | bimwright/dwg-mcp (README) | archive | C# | 39,223 | Apache-2.0 | 87 | - | medium |
| `greenloom_CAD_MCP` | softwelve/greenloom_CAD_MCP | clone | Python | 5,828 | MIT | 3 | F2 puran-water lineage | inventory-only |
| `lambdacad-mcp` | Psalmustrack/lambdacad-mcp | clone | Python | 5,274 | Apache-2.0 | 2 | - | medium |
| `mcp-autocad-api` | dimitrovakulenko/mcp-autocad-api | clone | Python | 1,821 | MIT | 1 | - | inventory-only |
| `mcp-connector-skills` | AUTOM8LABS/mcp-connector-skills | clone | Python | 674 | NONE | 1 | - | inventory-only |
| `multiCAD-mcp` | ewuiyud/multiCAD-mcp | clone | Python | 23,447 | Apache-2.0 | 9 | F3 multiCAD | inventory-only |
| `multiCAD-mcp-main` | AnCode666/multiCAD-mcp (README, pyproject) | archive | Python | 16,926 | Apache-2.0 | 6 | F3 multiCAD | medium |
| `new-acad-main` | Jjo37/new-acad per task brief; archive itself names no up... | archive | C# | 78,417 | MIT | 37 | - | skim |
| `not-autocad-mcp/Floorplan-Dimractor` | jasoncobra3/Floorplan-Dimractor | clone | Python | 668 | NONE | 1 | - | inventory-only |
| `not-autocad-mcp/LayerScape` | splrad/LayerScape | clone | C# | 16,136 | Apache-2.0 | 0 | - | inventory-only |
| `not-autocad-mcp/NX-Batch-Processing` | MohanDulam/NX-Batch-Processing | clone | C# | 670 | NONE | 0 | - | inventory-only |
| `not-autocad-mcp/Siemens_NX_File_Renamer` | nahidmubin/Siemens_NX_File_Renamer | clone | Python | 408 | GPL-3.0 | 0 | - | inventory-only |
| `not-autocad-mcp/SwpilotCLI` | arthurle3210/SwpilotCLI | clone | C# | 9,781 | OTHER-custom | 0 | - | inventory-only |
| `not-autocad-mcp/autoCAD-CSharp-templates` | Minso-xyz/autoCAD-CSharp-templates | clone | C# | 214 | NONE | 0 | - | inventory-only |
| `not-autocad-mcp/freecad-mcp` | contextform/freecad-mcp | clone | Python | 8,936 | NONE | 3 | - | inventory-only |
| `not-autocad-mcp/ipt-mcp` | bimwright/ipt-mcp | clone | C# | 13,243 | Apache-2.0 | 26 | - | inventory-only |
| `not-autocad-mcp/mechanical-cad-skills` | capwitf/mechanical-cad-skills | clone | Python | 1,322 | MIT | 0 | - | inventory-only |
| `not-autocad-mcp/openAI-to-freeCAD-workflow` | giuliano-t/openAI-to-freeCAD-workflow | clone | Python | 303 | MIT | 0 | - | inventory-only |
| `not-autocad-mcp/sketchup-mcp-server` | SidhNor/sketchup-mcp-server | clone | Ruby | 98,168 | AGPL-3.0 | 0 | - | inventory-only |
| `not-autocad-mcp/solidworks-GPT-plugin` | Erfouni/solidworks-GPT-plugin | clone | Python | 1,729 | MIT | 5 | - | inventory-only |
| `not-autocad-mcp/solidworks-api-mcp` | kilwizac/solidworks-api-mcp | clone | TypeScript | 4,315 | NONE | 4 | - | inventory-only |
| `not-autocad-mcp/solidworks-automation-skill` | wzyn20051216/solidworks-automation-skill | clone | Python | 75,867 | MIT | 97 | - | inventory-only |
| `vn-autocad-claude` | andyluu98/vn-autocad-claude | clone | Python | 6,045 | MIT | 3 | F2 puran-water lineage | inventory-only |

