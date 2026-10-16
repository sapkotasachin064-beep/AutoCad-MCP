# Architecture comparison (reference analysis)

How the reference codebases connect an MCP client to a CAD engine, what each
approach costs, and what this project takes from them. Evidence levels follow
[`feature-matrix.md`](feature-matrix.md): **V** = implementation read,
**D** = docs only. Nothing here was executed.

## 1. Engine transports

| # | Pattern | Seen in | Evidence | Strengths | Costs / risks |
|---|---|---|---|---|---|
| 1 | **Direct COM from the tool thread**: `CoInitialize` per call, `GetActiveObject` per call | this project (baseline), most small repos | V | No extra moving parts; nothing to install in AutoCAD | MCP SDK v2 runs sync handlers on AnyIO worker threads, so every call pays apartment setup; **no timeout**: a modal dialog blocks the call forever; concurrent tool calls hit COM concurrently |
| 2 | **Dedicated single-thread COM executor** with per-call timeout | U-C4N `ComBackend._run` (V), beiming183 `ComStaExecutor` (V), best-cad-mcp async facade (V) | V | Serialises every COM call; a hung AutoCAD costs one timeout, not the server | A blocked COM call cannot be cancelled: the worker must be abandoned and rebuilt (U-C4N) or quarantined (beiming183); the abandoned call may still land, so retries must be idempotency-aware |
| 3 | **AutoLISP file IPC**: JSON command file, `(c:mcp-dispatch)` typed into AutoCAD via `PostMessage(WM_CHAR)`, result file polled | puran-water `file_ipc.py` (V), beiming183, thewisekape, autocadplant3d | V | Works on **AutoCAD LT 2024+** (no COM there); no plugin build | Keystroke injection into the command line; depends on window discovery by title; the dispatcher `.lsp` must be loaded/trusted; JSON parsing in LISP; 10 s default timeout; `execute_lisp` runs arbitrary code |
| 4 | **LISP file bridge on Linux** (xdotool trigger) | lambdacad-mcp (BricsCAD) | D | Linux CAD support | Same trust model as 3; BricsCAD-specific |
| 5 | **In-process .NET plugin** + local transport (named pipe / TCP, NDJSON) | dwg-mcp (D: token auth, loopback, transactions), new-acad (D: TCP JSON-RPC :8080), MCP_AutocadMap3D (D: named pipe), cad-mcp (D: Roslyn C# execution), beiming183 `native/` (C) | D/C | Full .NET API: real transactions, Civil 3D / Map 3D object models, `LockDocument`, far faster than COM | A plugin build per AutoCAD generation (references cite .NET Framework 4.8 for 2021-2024, .NET 8 for 2025-2026, .NET 10 for 2027); NETLOAD / trusted locations; an extra local listener that must be authenticated (dwg-mcp does this with a per-start token; new-acad's ports are unauthenticated per its README) |
| 6 | **Headless DXF** with ezdxf | U-C4N (C), puran-water (C), beiming183 (C) | C | Cross-platform, no AutoCAD licence, deterministic tests, golden files | Not AutoCAD: no DWG write without the ODA converter, no ACIS solids, no plotting engine; undo needs snapshots; a timed-out ezdxf call keeps mutating the shared document (U-C4N `quarantine.py`, V) |
| 7 | **accoreconsole** batch | andagni Rust `autocad-mcp-3`, `autocad-mcp-8`, `autocad-mcp-9` | marker hits only | Real AutoCAD engine without UI on DWG files | Not inspected here; script-driven, file-at-a-time; licence/version coupling to the installed AutoCAD |

### Backend selection

U-C4N (docs), puran-water (`config.detect_backend`, V) and thewisekape (docs)
all **fall back automatically** to the headless engine when the live one is
unavailable. For a user who believes they are editing an open drawing, that
silently redirects writes into an in-memory DXF. This project rejects that:
the backend is chosen explicitly at startup, defaults to the live COM engine,
and every result names the backend that produced it.

## 2. Tool-surface designs

| Design | Example | Evidence | Trade-off |
|---|---|---|---|
| Per-task typed tools | this project (22), U-C4N (~247), best-cad-mcp (300+) | V | Clear schemas and validation; large catalogs cost client context, so the big ones add profiles |
| Operation-dispatch tools (`operation: str`, `data: dict`) | puran-water (8), thewisekape (22) | V | Few tools, but untyped `data` dicts defeat schema validation and hide required fields in prose |
| Profiles / packs / include-exclude lists | U-C4N `TOOL_PROFILE`/`TOOL_PACKS` (V config), best-cad-mcp `CAD_MCP_TOOLS_INCLUDE/EXCLUDE` (V) | V | Lets a constrained client advertise a lean subset |
| Search + call proxy | U-C4N `DISCOVERY_MODE=search` (V config) | V (config) | Two advertised tools; extra round trip per call; harder for clients that plan from the tool list |
| Agent inside CAD exposing 2 tools | new-acad | D | Out of scope for an MCP server |

## 3. Safety models

| Control | Example | Evidence | Notes |
|---|---|---|---|
| Output path validation + allow-list | U-C4N `security.validate_path` | V | Rejects traversal, `\\?\`/UNC anchors, system dirs; optional `ALLOWED_PATHS` |
| Command / LISP denylist, opt-in bypass | U-C4N `sanitize_command`/`sanitize_lisp` | V | The code itself says it is "a guardrail against accidental destruction, not a security boundary" |
| LISP execution refused outright | dwg-mcp | D | Strongest stance; C# execution remains a full-trust opt-in |
| Per-start auth token on the local listener | dwg-mcp discovery file | D | Prevents other local processes driving the plugin |
| Unauthenticated localhost listeners | new-acad (:8080/:3000/:19876), multiCAD dashboard (:8888) | D/V config | Any local process can drive CAD |
| Symbol names validated before macro interpolation | U-C4N `sanitize_symbol_name` | V | Newline/`;` in a name would start a second command inside `SendCommand` |

## 4. Reliability models

| Mechanism | Example | Evidence |
|---|---|---|
| Undo **Mark** before `StartUndoMark` group; rollback = `EndUndoMark` + `_.UNDO _B` | U-C4N `transaction_begin/rollback` | V. Its comment records that `_UNDO B` with no Mark prompts "undo everything?" and blocks `SendCommand` |
| `CMDACTIVE` check before typing commands | U-C4N | V |
| Plot with `BACKGROUNDPLOT=0`, honour `PlotToFile`'s boolean, verify the file exists | U-C4N `drawing_export_pdf` | V (comment records a measured AutoCAD 2026 failure mode) |
| Idempotency journal: accepted / committed / failed, request hash, replay | beiming183 `journal.py` | V |
| Document leases with revision fencing | beiming183 `session.py` | V |
| Error codes carrying `recoverable` + `recommended_action` | beiming183 `errors.py` | V |
| STA quarantine after timeout; cross-process COM mutex | beiming183 `com_sta.py` | V |
| Screenshots returned as file path + SHA-256, response byte ceiling | beiming183 incident doc | D |
| Capability parity test (every refusal key declared in every backend's map) | U-C4N `test_capability_contract.py` | C |

## 5. What this project adopts

Decisions are recorded in [`rebuild-plan.md`](rebuild-plan.md); licence
handling in [`reuse-and-licensing.md`](reuse-and-licensing.md). In short:

1. Keep pattern 1's simplicity but move every COM call onto **one dedicated
   COM thread with a per-call timeout** (pattern 2), written independently.
2. Add pattern 6 (**ezdxf headless**) as an *explicitly selected* second
   backend for offline drafting, validation and tests -- never as a fallback.
3. Typed per-task tools with MCP annotations, grouped into toolsets that can
   be switched off; no untyped `data: dict` operation tools.
4. Structured, client-visible errors with stable codes and recovery hints.
5. Document pinning, one undo group per mutating call, output-path
   validation, no raw command/LISP execution tool.
6. Patterns 3, 5 and 7 are documented as future backends; none is built in
   this pass (LT and Civil 3D are not installed on the development machine, and
   a .NET plugin needs a per-release build pipeline).
