# Backends

The server is pinned to one backend per process by `AUTOCAD_MCP_BACKEND`.
`autocad_get_capabilities` lists, per tool, which backends implement it; a
tool called on a backend that does not implement it returns
`E_UNSUPPORTED_BACKEND` with the reason.

| | `com` (default) | `dxf` |
|---|---|---|
| Engine | Running AutoCAD 2021+ (full, not LT), via COM/ActiveX | ezdxf, in-process |
| OS | Windows | any OS with Python 3.10+ (developed on Windows) |
| Needs | AutoCAD licence, `pywin32` | `pip install -e ".[dxf]"` |
| Documents | every drawing open in AutoCAD | one in-memory DXF document at a time |
| File formats | DWG and DXF (via AutoCAD) | DXF only (no DWG read/write) |
| PDF | `autocad_plot_pdf` (AutoCAD's DWG To PDF.pc3) | `autocad_render_preview` (needs matplotlib) |
| Highlighting | yes (display state) | no display -> refused |
| Launch | `autocad_launch_application` | refused |
| Verification | read-back over COM (counts, ObjectName, extents, properties) | re-reading the document/file |
| Live-verified in V0.3.0 | 19 live tests pass on AutoCAD 2024 (R24.3); see `docs/testing.md` | yes, by automated tests writing real files |

## `com` -- live AutoCAD

* Every call runs on one dedicated COM thread with a timeout
  (`AUTOCAD_MCP_COM_TIMEOUT`, default 120 s). See [architecture.md](architecture.md#the-com-thread).
* The server attaches to the running AutoCAD (`GetActiveObject`), or starts it
  only when `autocad_launch_application` is called.
* Release support: 2021 (R24.0) and newer. The release table maps 24.0-24.3 to
  2021-2024, 25.0 to 2025, 25.1 to 2026 and 26.0 to 2027; only 24.3 (2024) has
  been run against in this project.
* AutoCAD LT has no COM automation and is not supported (an LT file-IPC
  backend is catalogued as planned).

## `dxf` -- headless

* `autocad_create_new_drawing` makes an R2018 DXF in memory (with ezdxf's
  standard linetypes and styles); `autocad_open_drawing` reads a DXF in
  recover mode and reports the auditor's errors and fixes.
* The units preset is written to the DXF header (`$INSUNITS`, `$LUNITS`,
  `$LUPREC`, `$MEASUREMENT`).
* The backend holds one drawing; replacing it while it has unsaved changes is
  refused (`E_UNSAVED_CHANGES`).
* Saves are written to a temporary file and moved into place, then re-read to
  verify the entity count.
* Not supported headlessly: DWG, plotting, highlighting, launching AutoCAD,
  offset of bulged polylines/splines/ellipses (refused with the reason), hatch
  boundaries other than one closed straight-sided polyline or a circle.

## Planned backends (not implemented)

| Backend | Why | Status |
|---|---|---|
| AutoCAD LT via AutoLISP file IPC | LT has no COM | planned (design from puran-water, MIT) |
| In-process .NET plugin over a token-authenticated named pipe | real transactions, Civil 3D / Map 3D object models | planned (design from bimwright dwg-mcp, Apache-2.0) |
| `accoreconsole.exe` batch | process closed DWGs without the UI | planned |
| Other COM-compatible CADs (BricsCAD, ZWCAD, GstarCAD) | same ActiveX surface | planned, would be reported as untested |
