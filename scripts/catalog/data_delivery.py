"""Catalog data: validation, DXF/DWG exchange, plotting, evidence, quantities,
sheets, batch work, drawing understanding, comparison, standards,
deliverables, security, client setup, developer tooling."""

T = ["unit"]
TH = ["unit", "headless_dxf"]
MH = ["mock_com", "headless_dxf"]
H = ["headless_dxf"]
M = ["mock_com"]
N = []

Q = ("Q", "Drawing validation, audit, cleanup and diagnostics", {"inputs": ["rules", "limits"], "outputs": ["findings with handles"],
     "failure_modes": ["E_INVALID_INPUT"], "reference": "drafting hygiene checks, not code compliance"}, [
    ("zero_length", "Find zero-length lines and polylines", "Invisible junk geometry", "tested", "both", "read", ["autocad_check_drawing"], TH),
    ("degenerate_polylines", "Find polylines with fewer than two distinct vertices", "Broken outlines", "tested", "both", "read", ["autocad_check_drawing"], T),
    ("duplicates", "Find duplicate entities, reversed lines included", "Double-drawn linework inflates quantities", "tested", "both", "read", ["autocad_check_drawing"], T),
    ("empty_text", "Find TEXT/MTEXT with no visible characters", "Stray empty annotation", "tested", "both", "read", ["autocad_check_drawing"], T),
    ("layer_zero", "Find geometry drawn on layer 0", "Layer discipline", "tested", "both", "read", ["autocad_check_drawing"], T),
    ("open_wall_outlines", "Find open polylines on wall layers", "Walls that will not hatch or measure", "tested", "both", "read", ["autocad_check_drawing"], T),
    ("layer_naming", "Check layer names against a regex", "Office layer standards", "tested", "both", "read", ["autocad_check_drawing"], T),
    ("text_height_variety", "Flag too many different text heights", "Inconsistent annotation", "implemented", "both", "read", ["autocad_check_drawing"], N),
    ("tiny_circles", "Find circles and arcs with near-zero radius", "Accidental clicks", "implemented", "both", "read", ["autocad_check_drawing"], N),
    ("bounded_findings", "Cap findings per call and report truncation", "Large drawings stay readable", "implemented", "both", "read", ["autocad_check_drawing"], N),
    ("dxf_file_validation", "Validate a DXF file in recover mode with auditor errors and fixes", "Check files from others before use", "tested", "dxf", "read", ["autocad_validate_dxf_file"], H),
    ("qc_report", "Save check results as JSON, CSV or Markdown with SHA-256", "Evidence for a submission", "tested", "both", "external", ["autocad_save_report"], H),
    ("audit_live", "Run AutoCAD's AUDIT in report-only mode", "Database integrity", "planned", "com", "read", [], N),
    ("purge_dry_run", "Purge unused layers, blocks and styles with a dry-run list", "Smaller, cleaner files", "planned", "both", "destructive", [], N),
    ("overkill", "Remove overlapping duplicate linework with a dry run", "Clean imported drawings", "planned", "both", "destructive", [], N),
    ("dangling_ends", "Find dangling line ends and near-miss gaps", "Unclosed boundaries", "planned", "both", "read", [], N),
    ("self_intersections", "Find self-intersecting polylines", "Bad area calculations", "planned", "both", "read", [], N),
    ("off_standard_layers", "Find entities on layers outside the project standard", "Standards enforcement", "planned", "both", "read", [], N),
    ("bylayer_overrides", "Find colour/linetype overrides that are not ByLayer", "Predictable plotting", "planned", "both", "read", [], N),
    ("proxy_objects", "Detect proxy objects and missing object enablers", "Files from vertical products", "planned", "both", "read", [], N),
    ("missing_fonts", "Detect missing fonts and SHX files", "Garbled text", "planned", "com", "read", [], N),
    ("scale_anomalies", "Detect geometry far from the origin or out of scale", "Wrong-unit imports", "planned", "both", "read", [], N),
    ("dws_standards", "Check against a .dws standards file", "CAD standards audits", "planned", "com", "read", [], N),
    ("quality_score", "Weighted quality score over check results", "Track drawing quality", "planned", "pure", "read", [], N),
])

R = ("R", "DXF import/export and format conversion", {"inputs": ["paths"], "outputs": ["files with evidence"],
     "failure_modes": ["E_OUTPUT_EXISTS", "E_OUTPUT_PATH_REJECTED", "E_FILE_NOT_FOUND"]}, [
    ("export_dxf_copy", "Export a DXF copy without renaming the open drawing", "Share DXF while keeping the DWG open", "tested", "both", "external", ["autocad_export_dxf"], MH),
    ("read_dxf_headless", "Read DXF files headlessly", "Work without AutoCAD", "tested", "dxf", "read", ["autocad_open_drawing"], H),
    ("write_dxf_headless", "Write DXF files headlessly in the document's DXF version", "Produce drawings without AutoCAD", "tested", "dxf", "destructive", ["autocad_save_drawing"], ["headless_dxf", "stdio_e2e"]),
    ("reread_verification", "Verify written DXF files by re-reading them", "Proof the file is readable", "tested", "dxf", "read", [], H),
    ("dxf_header_units", "Write units into the DXF header", "Recipients see correct units", "tested", "dxf", "write", [], H),
    ("dxf_version_convert", "Convert DXF files between versions", "Old software compatibility", "planned", "dxf", "external", [], N),
    ("dxf_import_merge", "Import (merge) a DXF into the active drawing", "Combine drawings", "planned", "both", "write", [], N),
    ("binary_dxf", "Read and write binary DXF", "Smaller exchange files", "planned", "dxf", "external", [], N),
    ("geojson_export", "Export linework to GeoJSON", "GIS exchange", "planned", "both", "external", [], N),
    ("csv_to_dxf", "Create DXF points and labels from CSV", "Survey data exchange", "planned", "dxf", "external", [], N),
    ("layer_filtered_export", "Export only selected layers", "Send consultants what they need", "planned", "both", "external", [], N),
])

S = ("S", "DWG interoperability", {"inputs": ["paths"], "outputs": ["files"], "failure_modes": ["E_UNSUPPORTED_BACKEND"]}, [
    ("dwg_open_live", "Open DWG files on the live backend", "Edit DWG directly", "tested", "com", "write", ["autocad_open_drawing"], M, {"overlaps": ["E-005"]}),
    ("dwg_refused_headless", "Refuse DWG on the headless backend and name the conversion route", "Clear guidance instead of a crash", "tested", "dxf", "read", ["autocad_open_drawing"], H),
    ("oda_conversion", "DWG<->DXF conversion through the ODA File Converter when installed", "DWG without AutoCAD", "planned", "dxf", "external", [], N),
    ("dwg_version_report", "Report a DWG file's version from its header without opening it", "Know if recipients can open it", "planned", "pure", "read", [], N),
    ("dwg_batch_convert", "Batch DWG to DXF or PDF with accoreconsole", "Convert archives", "planned", "accore", "external", [], N),
    ("etransmit", "Package a DWG with its references", "Send complete drawing sets", "planned", "com", "external", [], N),
    ("dwg_compare", "Compare the open drawing against a DWG revision", "Revision review", "planned", "com", "read", [], N),
])

T_ = ("T", "PDF plotting, publishing and print configuration", {"inputs": ["layout, paper, style"], "outputs": ["PDF with evidence"],
      "failure_modes": ["E_PLOT_FAILED", "E_LAYOUT_NOT_FOUND", "E_OUTPUT_EXISTS"]}, [
    ("plot_model_fit", "Plot model space to PDF fitted to the paper", "Quick PDFs", "tested", "com", "external", ["autocad_plot_pdf"], M),
    ("plot_layout", "Plot a paper-space layout at 1:1", "Sheet PDFs", "implemented", "com", "external", ["autocad_plot_pdf"], N),
    ("foreground_plot", "Force foreground plotting and restore BACKGROUNDPLOT", "The PDF exists when the call returns", "tested", "com", "external", ["autocad_plot_pdf"], M),
    ("quiet_errors", "Suppress plot error dialogs during the plot and restore the setting", "No modal dialog blocks the server", "implemented", "com", "external", ["autocad_plot_pdf"], N),
    ("paper_match", "Match paper by canonical media name, rejecting ambiguous matches with candidates", "Right paper size", "tested", "com", "read", ["autocad_plot_pdf"], M),
    ("pdf_verification", "Verify the PDF header and report the paper size from /MediaBox", "Proof of what was plotted", "tested", "com", "read", ["autocad_plot_pdf"], M),
    ("plot_atomic", "Plot to a temporary file and replace the target only on success", "A failed plot keeps the old PDF", "tested", "com", "external", ["autocad_plot_pdf"], M),
    ("plot_settings_restored", "Restore the layout's plot settings after plotting", "Plotting does not alter the drawing", "tested", "com", "write", ["autocad_plot_pdf"], M),
    ("plot_style", "Apply a plot style table for the plot", "Monochrome output", "implemented", "com", "external", ["autocad_plot_pdf"], N),
    ("batch_plot", "Plot every layout to PDFs", "Whole sets at once", "planned", "com", "external", [], N),
    ("multi_sheet_pdf", "Publish a multi-sheet PDF", "One file per set", "planned", "com", "external", [], N),
    ("plot_window", "Plot a window area at a scale", "Partial plots", "planned", "com", "external", [], N),
    ("plot_exact_scale", "Plot model space at an exact scale such as 1:100", "Measurable prints", "planned", "com", "external", [], N),
    ("raster_plot", "Plot to PNG", "Images for reports", "planned", "com", "external", [], N),
    ("plot_styles_list", "List installed plot style tables", "Choose CTB/STB files", "planned", "com", "read", [], N),
    ("plot_devices_list", "List plot devices (PC3)", "Choose printers", "planned", "com", "read", [], N),
    ("plot_stamp", "Plot stamp with file, date and user", "Traceable prints", "planned", "com", "external", [], N),
])

U = ("U", "Screenshots, previews and evidence generation", {"inputs": ["path"], "outputs": ["file evidence"], "failure_modes": ["E_DEPENDENCY_MISSING"]}, [
    ("file_evidence", "Report size, SHA-256 and timestamp of every written file", "Prove what was produced", "tested", "both", "read", [], MH),
    ("verification_fields", "Every mutating result says whether and how it was verified", "No false 'done'", "tested", "both", "read", [], ["unit", "mock_com", "headless_dxf"]),
    ("headless_preview", "Headless PNG/PDF/SVG preview of model space", "See headless drawings", "implemented", "dxf", "external", ["autocad_render_preview"], N),
    ("window_capture", "Capture the AutoCAD window to a PNG returned as path and hash", "Visual check of the live drawing", "planned", "com", "external", [], N),
    ("zoom_extents", "Zoom extents or window before a capture", "Useful screenshots", "planned", "com", "write", [], N),
    ("handle_overlay", "Preview with entity handles drawn on it", "Ground visual review in handles", "planned", "dxf", "external", [], N),
    ("evidence_bundle", "Evidence bundle: drawing, PDF, report and hashes in a manifest", "Submission-ready evidence", "planned", "both", "external", [], N),
    ("before_after", "Before/after previews of a change", "Review edits visually", "planned", "dxf", "external", [], N),
])

AE = ("AE", "Bill of quantities, material takeoffs and quantity reports", {"inputs": ["layers", "wall height"], "outputs": ["quantities per layer"],
      "failure_modes": ["E_INVALID_INPUT"], "reference": "measurements of drawn geometry; not a professional bill of quantities"}, [
    ("lengths_by_layer", "Line, polyline and arc lengths per layer", "Linear quantities", "tested", "both", "read", ["autocad_quantity_takeoff"], TH),
    ("closed_areas", "Count, area and perimeter of closed shapes per layer", "Area quantities", "tested", "both", "read", ["autocad_quantity_takeoff"], TH),
    ("circles", "Circle counts and areas per layer", "Columns, piles, holes", "tested", "both", "read", ["autocad_quantity_takeoff"], T),
    ("wall_length", "Wall length from wall outline polylines", "Wall quantities", "tested", "both", "read", ["autocad_quantity_takeoff"], TH),
    ("wall_volume", "Wall face area and volume from a wall height", "Masonry estimates", "tested", "both", "read", ["autocad_quantity_takeoff"], T),
    ("metric_quantities", "Quantities converted to metres when units are known", "Consistent reporting", "tested", "both", "read", ["autocad_quantity_takeoff"], TH),
    ("takeoff_csv", "Takeoff report as CSV", "Spreadsheet-ready quantities", "tested", "both", "external", ["autocad_save_report"], H),
    ("rates", "Apply user-supplied rates to quantities (estimate)", "Rough cost estimates", "planned", "pure", "read", [], N),
    ("opening_deductions", "Deduct openings from wall areas", "Net wall areas", "planned", "pure", "read", [], N),
    ("room_floor_areas", "Floor finish areas by room", "Flooring quantities", "planned", "both", "read", [], N),
    ("brickwork", "Brick and mortar quantities from wall volumes and user mix data", "Masonry materials", "planned", "pure", "read", [], N),
    ("concrete", "Concrete volumes for drafted footings, columns and slabs", "Concrete quantities", "planned", "both", "read", [], N),
    ("steel_weights", "Steel weights from a bar bending schedule", "Reinforcement quantities", "planned", "pure", "read", [], N),
    ("plaster_paint", "Plaster and paint areas from walls and heights", "Finishes", "planned", "pure", "read", [], N),
    ("excavation", "Excavation volumes for footings", "Earthwork for foundations", "planned", "pure", "read", [], N),
    ("boq_xlsx", "BOQ workbook (XLSX)", "Office-ready BOQs", "planned", "pure", "external", [], N),
    ("measurement_sheet", "Measurement sheet with item descriptions and dimensions", "Traceable quantities", "planned", "pure", "external", [], N),
])

AF = ("AF", "Title blocks, sheet sets, revisions and drawing standards", {"inputs": ["paper, scale, fields"], "outputs": ["sheet geometry"],
      "failure_modes": ["E_INVALID_INPUT"]}, [
    ("sheet_border", "Sheet border at paper size times scale (ISO A, ANSI, ARCH)", "Correctly sized sheets in model space", "tested", "both", "write", ["autocad_draw_sheet"], TH),
    ("drawing_frame", "Drawing frame with a binding margin", "Standard sheet margins", "tested", "both", "write", ["autocad_draw_sheet"], T),
    ("title_block", "Title block with nine labelled fields", "Identify every sheet", "tested", "both", "write", ["autocad_draw_sheet"], TH),
    ("scaled_title_text", "Title text heights in paper millimetres times the scale", "Text plots at the right size", "tested", "pure", "write", ["autocad_draw_sheet"], T),
    ("drawing_area", "Report the usable drawing area for placing views", "Fit content inside the frame", "tested", "pure", "read", ["autocad_draw_sheet"], H),
    ("revision_table", "Revision table with clouds", "Track revisions", "planned", "both", "write", [], N),
    ("sheet_numbering", "Sheet numbering across a set", "Consistent numbering", "planned", "pure", "write", [], N),
    ("sheet_sets", "Sheet set (DST) management", "Large sets", "planned", "com", "write", [], N),
    ("attribute_title_block", "Title blocks as attribute blocks", "Editable title data", "planned", "both", "write", [], N),
    ("logo", "Insert a logo image into the title block", "Branded sheets", "planned", "com", "write", [], N),
    ("standards_profile", "Project standards profile (layers, styles, text heights) loaded from a file", "Per-project standards", "planned", "pure", "read", [], N),
    ("watermark", "'Preliminary / not for construction' watermark", "Avoid misuse of drafts", "planned", "both", "write", [], N),
])

AG = ("AG", "Batch operations and reusable drawing workflows", {"inputs": ["plans, lists"], "outputs": ["many entities"], "failure_modes": ["E_VERIFICATION_FAILED"]}, [
    ("one_session_plans", "Draw whole generated plans in one COM session", "Fast, consistent generation", "tested", "both", "write", [], ["golden_regression", "mock_com", "headless_dxf"]),
    ("plan_emitter", "One plan emitter for live and headless drawings", "Same output on both backends", "tested", "both", "write", [], ["unit", "headless_dxf"]),
    ("batch_draw", "Batch primitive drawing in one call", "Fewer round trips", "planned", "both", "write", [], N, {"reference": "lambdacad draw_batch idea (Apache-2.0)"}),
    ("batch_files", "Run a workflow over many drawings", "Bulk updates", "planned", "both", "write", [], N),
    ("recorder", "Record and replay tool sequences", "Repeatable jobs", "planned", "pure", "session", [], N),
    ("table_driven", "Draw from CSV or spreadsheet tables", "Data-driven drafting", "planned", "both", "write", [], N),
    ("parametric_templates", "Parametric drawing templates (house sizes, grid presets)", "Reuse proven layouts", "planned", "pure", "read", [], N),
    ("json_drawing_plan", "Validate and execute a JSON drawing plan (plan, dry run, execute)", "Reviewable automation", "planned", "both", "write", [], N),
])

AH = ("AH", "Semantic search and drawing understanding", {"inputs": ["drawing"], "outputs": ["interpretations with confidence"], "failure_modes": []}, [
    ("geometry_snapshot", "Normalised snapshot of model-space geometry for reasoning", "Tools reason over data, not screenshots", "tested", "both", "read", ["autocad_check_drawing", "autocad_quantity_takeoff"], MH),
    ("discipline_inference", "Infer each layer's discipline from its name", "Understand foreign drawings", "planned", "pure", "read", [], N),
    ("room_recognition", "Recognise rooms from labels and closed areas", "Areas from existing plans", "planned", "both", "read", [], N),
    ("symbol_recognition", "Recognise door and window symbols from geometry", "Schedules from old drawings", "planned", "both", "read", [], N),
    ("units_inference", "Infer real units from geometry when INSUNITS is wrong", "Fix mis-scaled drawings", "planned", "pure", "read", [], N),
    ("describe_drawing", "Plain-language description built from summary data", "Brief a reviewer", "planned", "pure", "read", [], N),
    ("find_by_description", "Find entities from a description such as 'the kitchen wall'", "Natural requests", "planned", "both", "read", [], N),
    ("dimension_binding", "Bind dimensions to the geometry they measure", "Detect stale dimensions", "planned", "both", "read", [], N),
    ("constraints", "Extract parallel, perpendicular and equal-length relations", "Design intent", "planned", "pure", "read", [], N),
    ("image_trace", "Trace raster images to linework for user review", "Digitise sketches", "planned", "both", "write", [], N),
])

AI = ("AI", "Diffing, change detection and revision reporting", {"inputs": ["two revisions"], "outputs": ["changes"], "failure_modes": ["E_FILE_NOT_FOUND"]}, [
    ("dxf_compare", "Compare two DXF files", "Review revisions", "tested", "pure", "read", ["autocad_compare_dxf"], TH),
    ("handle_matching", "Match entities by handle first", "Track the same objects", "tested", "pure", "read", ["autocad_compare_dxf"], T),
    ("rehandled", "Detect identical geometry under new handles", "Copy/paste is not a change", "tested", "pure", "read", ["autocad_compare_dxf"], T),
    ("changed_fields", "Report which fields of an entity changed", "Precise change notes", "tested", "pure", "read", ["autocad_compare_dxf"], T),
    ("live_vs_file", "Compare the live drawing against a saved DXF revision", "What changed since the last issue", "planned", "both", "read", [], N),
    ("cloud_markup", "Draw revision clouds around changes", "Marked-up revisions", "planned", "both", "write", [], N),
    ("scan_history", "Keep scan history to compare over time", "Change tracking", "planned", "pure", "read", [], N),
    ("change_report", "Markdown change report", "Transmittal notes", "planned", "pure", "external", [], N),
])

AJ = ("AJ", "Template management and project standards", {"inputs": ["standards file"], "outputs": ["applied settings"], "failure_modes": []}, [
    ("generator_layers", "Generators create their own layers with standard names and colors", "Consistent output", "tested", "both", "write", [], H),
    ("template_library", "Template library: list and create from template", "Start projects consistently", "planned", "both", "write", [], N),
    ("template_from_drawing", "Save drawing settings as a template", "Capture good setups", "planned", "com", "external", [], N),
    ("standards_file", "Project standards file (JSON) for layers, styles, units, text heights", "Configurable standards", "planned", "pure", "read", [], N),
    ("standards_apply", "Apply a standards file to a drawing with a dry run", "Bring drawings to standard", "planned", "both", "write", [], N),
    ("standards_check", "Check a drawing against a standards file", "Standards audits", "planned", "both", "read", [], N),
    ("dimstyle_library", "Shared dimension style library", "Reuse styles", "planned", "both", "write", [], N),
    ("block_library", "Block library from a folder of DWG/DXF files", "Symbol libraries", "planned", "both", "write", [], N),
    ("linetype_library", "Custom linetype definitions", "Special linetypes", "planned", "both", "write", [], N),
])

AK = ("AK", "Export pipelines and deliverable packaging", {"inputs": ["format, path"], "outputs": ["files with evidence"], "failure_modes": ["E_OUTPUT_EXISTS"]}, [
    ("report_json", "Check/takeoff reports as JSON", "Machine-readable evidence", "tested", "both", "external", ["autocad_save_report"], H),
    ("report_markdown", "Check/takeoff reports as Markdown", "Readable evidence", "tested", "both", "external", ["autocad_save_report"], H),
    ("report_csv", "Check/takeoff reports as CSV", "Spreadsheet evidence", "tested", "both", "external", ["autocad_save_report"], H),
    ("package", "Package DWG/DXF/PDF/reports with a SHA-256 manifest", "Complete deliverables", "planned", "both", "external", [], N, {"reference": "beiming183 delivery manifest idea (MIT)"}),
    ("zip", "Zip a deliverable folder", "Easy sharing", "planned", "pure", "external", [], N),
    ("transmittal", "Transmittal sheet listing deliverables", "Formal issue", "planned", "pure", "external", [], N),
    ("xlsx", "XLSX reports", "Office workflows", "planned", "pure", "external", [], N),
    ("naming", "Deliverable file-naming convention checks", "Consistent file names", "planned", "pure", "read", [], N),
])

AL = ("AL", "Security, permissions, observability and diagnostics", {"inputs": ["configuration"], "outputs": ["refusals, logs"], "failure_modes": ["E_OUTPUT_PATH_REJECTED"]}, [
    ("path_validation", "Reject traversal, UNC, device and system-folder paths", "No writes to dangerous places", "tested", "pure", "read", [], T),
    ("allowed_dirs", "Optional output allow-list (AUTOCAD_MCP_ALLOWED_DIRS)", "Confine file writes", "tested", "pure", "read", [], T),
    ("no_raw_execution", "No raw command, LISP or code-execution tool", "The model cannot run arbitrary code in AutoCAD", "tested", "pure", "read", [], T),
    ("name_validation", "Reject command-separator characters in layer and linetype names", "Names cannot inject commands", "tested", "pure", "read", [], T),
    ("no_tracebacks", "Error envelopes carry messages, never tracebacks", "No internal details leak to clients", "tested", "pure", "read", [], T),
    ("stderr_logging", "Log to stderr only; stdout stays the protocol channel", "Logs never corrupt the protocol", "implemented", "pure", "read", [], N),
    ("audit_log", "Audit log of mutating calls without secrets", "Accountability", "planned", "pure", "session", [], N),
    ("read_only_mode", "Server-wide read-only mode", "Safe reviews of production drawings", "planned", "pure", "session", [], N),
    ("http_auth", "Token auth and loopback binding for HTTP transport", "Safe remote clients", "planned", "pure", "session", [], N),
    ("rate_limits", "Rate limits and screenshot budgets", "Protect the client and AutoCAD", "planned", "pure", "session", [], N),
    ("response_cap", "Hard cap on response size", "Clients cannot be flooded", "planned", "pure", "read", [], N),
    ("self_test", "Self-test tool: COM, ezdxf, paths, permissions", "Quick diagnosis", "planned", "pure", "read", [], N),
    ("dependency_report", "Report every dependency version", "Reproducible bug reports", "planned", "pure", "read", [], N),
])

AM = ("AM", "Client setup, onboarding and integration verification", {"inputs": [], "outputs": ["configs, docs"], "failure_modes": []}, [
    ("stdio_launch", "One launch command for every client: python src/server.py", "Simple setup", "tested", "pure", "read", [], ["stdio_e2e"]),
    ("entry_point", "autocad-mcp console entry point", "Run after pip install", "tested", "pure", "read", [], T),
    ("claude_code_config", "Claude Code config (claude mcp add / .mcp.json) checked with claude 2.1.300", "Claude Code users", "implemented", "client", "read", [], N, {"reference": "docs/client-integrations.md"}),
    ("opencode_config", "OpenCode config (opencode mcp add / opencode.json) checked with opencode 2.0.31", "OpenCode users", "implemented", "client", "read", [], N, {"reference": "docs/client-integrations.md"}),
    ("codex_config", "Codex CLI config.toml from the official docs (not tested: codex not installed)", "Codex users", "implemented", "client", "read", [], N, {"reference": "docs/client-integrations.md"}),
    ("claude_desktop_config", "Claude Desktop claude_desktop_config.json (documented, not tested)", "Claude Desktop users", "implemented", "client", "read", [], N, {"reference": "docs/client-integrations.md"}),
    ("env_reference", "Environment variable reference", "Configure without reading code", "implemented", "pure", "read", [], N, {"reference": "docs/installation.md"}),
    ("setup_script", "Setup script that writes client configs after confirmation", "One-step onboarding", "planned", "client", "external", [], N),
    ("doctor", "Doctor command checking Python, pywin32, ezdxf, AutoCAD and client configs", "Fast troubleshooting", "planned", "pure", "read", [], N),
    ("ide_configs", "VS Code / Cursor configuration examples", "IDE users", "planned", "client", "read", [], N),
    ("uvx_pipx", "Install and run via uvx or pipx", "No manual environments", "planned", "pure", "read", [], N),
])

AN = ("AN", "Developer tooling, tests, fixtures and compatibility checks", {"inputs": [], "outputs": ["test results"], "failure_modes": []}, [
    ("fake_com", "Recorded fake AutoCAD object model for behaviour tests", "Test COM code without AutoCAD", "tested", "pure", "read", [], T),
    ("golden_floor_plan", "Golden regression of the V0.2.3 floor plan from the git baseline", "Refactors cannot change output", "tested", "pure", "read", [], ["golden_regression"]),
    ("headless_tests", "Headless integration tests writing and re-reading real DXF files", "End-to-end without AutoCAD", "tested", "dxf", "read", [], H),
    ("stdio_tests", "stdio end-to-end tests with the official MCP client", "Prove real clients work", "tested", "pure", "read", [], ["stdio_e2e"]),
    ("live_tests", "Live AutoCAD tests that skip, never fake, without AutoCAD", "Honest live verification", "implemented", "com", "read", [], N),
    ("catalog_check", "Catalog generator with a staleness check", "Catalog stays true", "tested", "pure", "read", [], T),
    ("packaging_checks", "Packaging checks: version, dependencies, modules", "Installable releases", "tested", "pure", "read", [], T),
    ("ci", "CI workflow on Windows", "Every change tested", "planned", "pure", "read", [], N),
    ("lint", "Lint and format gates", "Consistent code", "planned", "pure", "read", [], N),
    ("coverage", "Coverage reporting", "Find untested code", "planned", "pure", "read", [], N),
    ("live_campaign", "Scripted live verification campaign with evidence capture", "Repeatable live verification", "planned", "com", "read", [], N),
    ("release_matrix", "Compatibility runs per AutoCAD release 2021-2027", "Know what works where", "planned", "com", "read", [], N),
    ("property_tests", "Property-based geometry tests", "Edge cases", "planned", "pure", "read", [], N),
    ("benchmarks", "Performance benchmarks on large drawings", "Scale limits", "planned", "both", "read", [], N),
])

DOMAINS = [Q, R, S, T_, U, AE, AF, AG, AH, AI, AJ, AK, AL, AM, AN]
