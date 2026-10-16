# Architecture

How this server is built (V0.3.0). Reference material about other projects
lives in [`analysis/`](analysis/); the reasons for each decision are in
[`analysis/rebuild-plan.md`](analysis/rebuild-plan.md).

## Layers

```
MCP client (Claude Code, OpenCode, Codex, Claude Desktop, ...)
   | stdio, JSON-RPC
src/server.py ............ MCP surface: 64 tools, 3 resources, 3 prompts (@cad_tool boundary)
   |
src/backends/ ............ one Backend per engine, chosen once per process
   |-- base.py             every operation refuses (E_UNSUPPORTED_BACKEND) unless overridden
   |-- com.py              live AutoCAD: runs src/tools/* on the COM thread, with a timeout
   |-- dxf.py              headless: one ezdxf document held by the server
   `-- targets.py          emits a domain Plan into a COM document, an ezdxf document, or a recorder
   |
src/tools/ ............... live COM implementations (one module per area)
src/domain/ .............. pure engineering logic: units, plans, floor plans, grids, stairs,
   |                       sheets, QC rules, takeoff, comparison -- no COM, no ezdxf
src/core/ ................ errors, COM executor, session (backend + pin + notices),
   |                       registry (toolsets, annotations, capabilities), paths, evidence, reports
src/cad_engine.py ........ COM connection, launch, document access, units policy, identity
src/db.py ................ SQLite cache of entity scans + read-only query guard
src/utils/ ............... input validation (geometry.py, validation.py), constants
```

Dependency direction: `server -> backends -> tools -> cad_engine/core/domain/utils`.
`domain/`, `core/` (except `com_executor`'s optional `pythoncom`), `utils/`,
`backends/dxf.py` and `backends/targets.py` import no pywin32 code; a test
(`tests/test_server_surface.py`) blocks those imports and loads them.

## The tool boundary (`server.cad_tool`)

Every public tool is a small function decorated with `@cad_tool(toolset=,
kind=, title=, operation=)`:

1. A `ToolSpec` is recorded in `core.registry` -- the source of
   `autocad_get_capabilities`, `autocad://capabilities` and `docs/tools.md`.
2. MCP `ToolAnnotations` are derived from `kind`:

   | kind | readOnlyHint | destructiveHint | meaning |
   |---|---|---|---|
   | `read` | true | false | never changes a drawing or a file (the SQLite scan cache aside) |
   | `session` | false | false | changes server state only (pin, unpin) |
   | `write` | false | false | adds to or changes the drawing or AutoCAD's state, never removes work |
   | `destructive` | false | true | can remove or overwrite work (delete, close, save over) |
   | `external` | false | false | writes files or starts processes outside the drawing |

3. Results gain `backend` and, for `write`/`destructive`/`external` tools, a
   `state` block (below).
4. Any exception becomes an error envelope (below). MCP clients receive it as
   an `is_error` result whose text is exactly the JSON; Python callers of the
   decorated function get a `ToolError` with the same text.
5. If the tool's toolset is disabled by `AUTOCAD_MCP_TOOLSETS`, it is not
   registered with MCP (the Python function still exists).

### Errors

```json
{"ok": false,
 "error": {"code": "E_DOCUMENT_CHANGED",
           "message": "The active drawing is 'path:c:\\b.dwg', but this session is pinned to 'path:c:\\a.dwg'. Nothing was changed.",
           "recoverable": true,
           "recommended_action": "activate_the_pinned_drawing_in_autocad_or_call_autocad_unpin_document",
           "details": {"pinned_document": "path:c:\\a.dwg", "active_document": "path:c:\\b.dwg"}},
 "tool": "autocad_draw_line", "backend": "com"}
```

Codes are listed in `src/core/errors.py` (`ERROR_CODES`). Before V0.3.0 the
MCP SDK replaced every message with `Error executing tool <name>` (defect D1).
`recoverable: true` means the same call can succeed once the named condition
changes outside it (AutoCAD started, dialog closed); `false` means the call
itself must change. COM `HRESULT`s are decoded (`RPC_E_CALL_REJECTED` ->
`E_AUTOCAD_NOT_RESPONDING`, ...). Tracebacks never leave the server.

### The `state` block

```json
"state": {"accepted": true, "preflight_passed": true, "executed": true, "verified": true, "saved": false}
```

`verified` is copied from the tool's own read-back (`verification` names
what was checked, e.g. `modelspace_count_plus_one_and_object_name`,
`bounding_box_shifted_by_displacement`, `pdf_on_disk_with_pdf_header`) and is
`null` when a tool cannot verify. `saved: false` means the drawing still has
to be saved. A dry run reports `executed: false`. Failures before execution
never produce a state block -- they produce an error envelope.

## Backends

See [backends.md](backends.md). The backend is fixed for the life of the
process by `AUTOCAD_MCP_BACKEND` (`com` default, or `dxf`). There is no
`auto` mode: falling back from a live drawing to a DXF file without the user
noticing is the failure the reference survey found in three other servers.

### The COM thread

`core/com_executor.py` runs every live call on one dedicated thread that has
called `CoInitialize` once. Callers wait up to `AUTOCAD_MCP_COM_TIMEOUT`
(default 120 s; plotting at least 300 s; launch = its own wait + 30 s):

* still queued when the time runs out -> cancelled, `E_COM_BUSY`, nothing was sent;
* started but not finished -> the worker is abandoned (a blocked COM call cannot
  be interrupted), the next call gets a fresh worker, and `E_COM_TIMEOUT` says
  the abandoned call may still complete inside AutoCAD.

`cad_engine._retry_com` additionally retries `RPC_E_CALL_REJECTED` and the
transient `AttributeError` dynamic dispatch raises under load (V0.2.x).

### Document access, pinning and units

Every live tool reaches the drawing through `cad_engine.get_active_document(app, for_write=...)`:

1. no document -> `E_NO_ACTIVE_DOCUMENT`;
2. a pinned session and a different active drawing -> `E_DOCUMENT_CHANGED`, before anything else;
3. `for_write=True` only: cancel a pending command if `CMDACTIVE` shows one,
   then apply the units preset (`AUTOCAD_MCP_UNITS`, or the one chosen with
   `autocad_set_drawing_units`), skipping variables that already match;
4. `for_write=False` (read-only tools): no keystrokes, no variable changes; an
   active command is only reported.

Unrequested side effects are returned as `notices` (`units_changed`,
`pending_command_cancelled`, `autocad_command_active`).

Drawing identity is `path:<full path, lower-case>` for saved drawings and
`unsaved:<name>` otherwise (AutoCAD documents have no GUID; `FullName` is the
reliable saved/unsaved signal -- verified on AutoCAD 2024 in V0.2.x).

## Generators: plans, dry runs, verification

`domain/` planners (`floorplan`, `grids`, `stairs`, `sheets`) return a `Plan`:
the layers they need and an ordered list of primitives, each with a stable
tag. Nothing is drawn by a planner. `backends/targets.emit(plan, target)`
draws the primitives into a `ComTarget`, `DxfTarget` or `RecordingTarget`,
returns `{tag: handle}`, and raises `E_VERIFICATION_FAILED` unless model space
grew by exactly the number of primitives. The same plan therefore produces the
same drawing on both backends, every generator supports `dry_run=true`, and
generators are unit-testable without AutoCAD. Plans are built in the drawing's
own `INSUNITS`, so the V0.2.3 inch floor plan is reproduced entity-for-entity
in an inch drawing (golden test) and converted in a metric one.

## Read-only analysis

`snapshot_entities` (both backends) produces one normalised list of entity
dicts (`handle`, `type`, `layer`, points, centre/radius, text, length, area...).
`domain/qc.py`, `domain/takeoff.py` and `domain/diff.py` are pure functions of
that list, so checks, quantities and comparisons behave identically live and
headless.

## Output safety

`core/paths.py` validates every path the server writes or reads for a caller:
no `..`, UNC, `\\?\` or device paths, nothing under Windows/Program Files, an
optional allow-list (`AUTOCAD_MCP_ALLOWED_DIRS`), relative paths resolved into
`AUTOCAD_MCP_OUTPUT_DIR`, existing files replaced only with `overwrite=true`.
Exports, plots, reports and headless saves write to a temporary name and
replace the target only after success, then report size and SHA-256 read
back from disk (`core/evidence.py`).

## What is deliberately absent

* No raw command, LISP or code-execution tool (a test enforces this).
* No network listener: stdio only.
* No automatic backend fallback.
* No undo-group/transaction tool yet (catalogued as planned; see the
  reference notes on `UNDO` marks in `analysis/architecture-comparison.md`).
