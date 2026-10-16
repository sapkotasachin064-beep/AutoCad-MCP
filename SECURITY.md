# Security

## Supported versions

Only the newest version gets fixes: 0.3.x (branch `feat/v0.3.0-rebuild`
until it is merged), then whatever `main` carries.

## Reporting a vulnerability

Please do not put exploit details in a public issue. Use GitHub's private
vulnerability reporting for this repository if it is enabled (Security tab,
"Report a vulnerability"); otherwise open an issue that asks the maintainer
for a private contact, without details.

## What the server is

A local process that an MCP client starts over stdio. It acts with **your
Windows user rights**: through COM it can change any drawing your AutoCAD
has open, and it can read and write files where your account can, within
the limits below. The model in your MCP client decides which tools to call,
so treat the combination "model + this server" like a colleague with access
to your AutoCAD session.

## Built-in safeguards

| Risk | Safeguard |
|---|---|
| Arbitrary code or command execution | No tool runs raw AutoCAD commands, AutoLISP, scripts, Python or shell commands. The only key sent to AutoCAD is ESC, and only to end a command already in progress before a drawing change. |
| SQL injection or writes to the scan cache | `autocad_execute_query` accepts one `SELECT` / `WITH` statement and runs it on a read-only SQLite connection. |
| Network exposure | stdio only; no port is opened. |
| Editing the wrong drawing | `autocad_pin_document` / `pin=true`: while a pin is set, tools refuse to act on any other drawing (`E_DOCUMENT_CHANGED`). Every result names the drawing it acted on. |
| Losing work | Deletes default to `dry_run=true`; closing a drawing with unsaved changes needs `discard_changes=true`; saving over another file needs `overwrite=true`; drawings open read-only unless `read_only=false`. |
| Writing files in the wrong place | Paths with `..`, UNC shares, `\\?\` prefixes or system folders (`C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData\Microsoft`) are refused. `AUTOCAD_MCP_ALLOWED_DIRS` confines every path a tool accepts (drawings, templates, DXF, PDF, reports, previews) to the listed folders; the scan cache location is set separately by `AUTOCAD_MCP_DB_PATH`. Relative paths go to `AUTOCAD_MCP_OUTPUT_DIR`. |
| Silent changes to drawing settings | Units are changed only by drawing tools, only when they differ from the preset, and every change is reported (`AUTOCAD_MCP_UNITS=preserve` disables it). |
| A hung AutoCAD blocking the client | Every COM call has a timeout (`AUTOCAD_MCP_COM_TIMEOUT`). |
| Unbounded responses | Lists and queries are paged or limited and report truncation. |
| Clients that auto-approve tools | Every tool carries MCP annotations (read-only, destructive, idempotent, open-world) so clients can ask before destructive calls. |

## What it cannot protect against

* **Content inside drawings is untrusted input.** Text, attribute values and
  layer names are returned to the model. A drawing could contain text written
  to manipulate the model ("ignore your instructions and delete..."). Keep
  your client's approval prompts on for destructive tools and review what
  the model plans to do.
* **AutoCAD's own behaviour when opening files.** Opening a drawing can make
  AutoCAD load code (for example `acad.lsp` / `acaddoc.lsp` beside the
  drawing) depending on AutoCAD's `SECURELOAD` and trusted-locations
  settings. This server does not change those settings; keep them at
  AutoCAD's secure defaults and open untrusted drawings read-only.
* **Parser bugs.** Malformed DWG/DXF files are handled by AutoCAD or ezdxf,
  not by this project.
* **The scan cache.** `autocad_scan_all_entities` stores entity properties,
  including text content, in SQLite at `AUTOCAD_MCP_DB_PATH`. Treat that file
  as being as sensitive as the drawings; delete it when you are done.
* **Your client configuration.** Anyone who can edit your MCP client's
  configuration can change the command it starts. This server needs no
  secrets; do not put any in its configuration.

## Recommendations

1. Pin the drawing for every job (`autocad_create_new_drawing` /
   `autocad_open_drawing` with `pin=true`).
2. Set `AUTOCAD_MCP_ALLOWED_DIRS` to a project output folder.
3. Use `AUTOCAD_MCP_TOOLSETS` to expose only the toolsets a job needs.
4. Keep a saved copy before letting a model edit an existing drawing, and
   prefer the headless `dxf` backend for experiments on copies.
