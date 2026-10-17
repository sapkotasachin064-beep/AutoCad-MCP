"""Regenerate the generated files from code: docs/capabilities.json and the
marked blocks in README.md (capability summary + tool reference).

    python scripts/build_capabilities.py          # write both
    python scripts/build_capabilities.py --check  # fail if either is stale

The README blocks live between HTML comment markers:
    <!-- generated:start summary -->  ...  <!-- generated:end summary -->
    <!-- generated:start tools -->    ...  <!-- generated:end tools -->
Edit those blocks only by running this script.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("AUTOCAD_MCP_TOOLSETS", None)  # document every toolset
os.environ.pop("AUTOCAD_MCP_BACKEND", None)

import server  # noqa: E402
from core import catalog, registry  # noqa: E402

KIND_TEXT = {
    "read": "read-only",
    "session": "session state only",
    "write": "changes the drawing or AutoCAD's state, never removes work",
    "destructive": "can remove or overwrite work",
    "external": "writes files or starts processes",
}

MARKERS = {
    "summary": ("<!-- generated:start summary -->", "<!-- generated:end summary -->"),
    "tools": ("<!-- generated:start tools -->", "<!-- generated:end tools -->"),
}


def _type(schema: dict) -> str:
    if "anyOf" in schema:
        return " | ".join(_type(s) for s in schema["anyOf"])
    t = schema.get("type", "any")
    if t == "array":
        return f"list[{_type(schema.get('items', {}))}]"
    if t == "object" and "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        return f"dict[str, {_type(schema['additionalProperties'])}]"
    return {"null": "null", "number": "number", "integer": "integer", "string": "string",
            "boolean": "boolean", "object": "object"}.get(t, t)


def capabilities_document() -> str:
    items = catalog.entries()
    problems = catalog.validate(items)
    if problems:
        raise SystemExit("\n".join(problems))
    doc = {"schema_version": 1, "statuses": list(catalog.STATUSES),
           "summary": catalog.summary(items), "capabilities": items}
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _tools_list():
    return {t.name: t for t in asyncio.run(server.server.list_tools())}


def summary_block(items) -> str:
    stats = catalog.summary(items)
    by_status = stats["by_status"]
    tools = asyncio.run(server.server.list_tools())
    return (
        f"**{len(tools)} MCP tools** in {len(registry.TOOLSETS)} toolsets; "
        f"**{stats['total']} catalogued capabilities**: "
        f"{by_status.get('verified', 0)} verified live, {by_status.get('tested', 0)} tested, "
        f"{by_status.get('implemented', 0)} implemented, {by_status.get('planned', 0)} planned. "
        "Status words mean exactly what `docs/capabilities.json` says: only a live AutoCAD test "
        "promotes a capability to `verified`."
    )


def tools_block() -> str:
    tools = _tools_list()
    specs = registry.specs()
    caps = {t["name"]: t for t in registry.tools_list()}
    by_set = {}
    for name, spec in specs.items():
        by_set.setdefault(spec.toolset, []).append(name)
    lines = [
        f"{len(tools)} tools in {len(registry.TOOLSETS)} toolsets. Argument schemas are generated "
        "from typed signatures; every parameter carries a description. ",
        "",
        "| Toolset | Tools | Purpose |",
        "|---|---|---|",
    ]
    for toolset, description in registry.TOOLSETS.items():
        lines.append(f"| `{toolset}` | {len(by_set.get(toolset, []))} | {description} |")
    for toolset in registry.TOOLSETS:
        lines += ["", f"### `{toolset}`", "",
                  "| Tool | Kind | Backends | Description |", "|---|---|---|---|"]
        for name in sorted(by_set.get(toolset, [])):
            spec, tool, cap = specs[name], tools[name], caps[name]
            backends = ", ".join(cap["backends"]) or "none"
            description = " ".join((tool.description or "").split())
            lines.append(f"| `{name}` | {KIND_TEXT[spec.kind]} | {backends} | {description} |")
    return "\n".join(lines)


def _replace_block(readme: str, key: str, body: str) -> str:
    start, end = MARKERS[key]
    if readme.count(start) != 1 or readme.count(end) != 1:
        raise SystemExit(f"README.md must contain exactly one {start} / {end} pair")
    before, rest = readme.split(start, 1)
    _, after = rest.split(end, 1)
    return f"{before}{start}\n{body}\n{end}{after}"


def readme_text(readme: str) -> str:
    readme = _replace_block(readme, "summary", summary_block(catalog.entries()))
    readme = _replace_block(readme, "tools", tools_block())
    return readme


def main(check: bool) -> int:
    json_text = capabilities_document()
    json_path = ROOT / "docs" / "capabilities.json"
    readme_path = ROOT / "README.md"
    readme_new = readme_text(readme_path.read_text(encoding="utf-8"))
    if check:
        stale = []
        if not json_path.exists() or json_path.read_text(encoding="utf-8") != json_text:
            stale.append(str(json_path))
        if readme_path.read_text(encoding="utf-8") != readme_new:
            stale.append(f"{readme_path} (generated blocks)")
        if stale:
            print("stale: " + ", ".join(stale))
            return 1
        print("generated files up to date")
        return 0
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_text, encoding="utf-8", newline="\n")
    readme_path.write_text(readme_new, encoding="utf-8", newline="\n")
    stats = catalog.summary(catalog.entries())
    print(f"wrote {json_path} ({stats['total']} capabilities: {stats['by_status']}) and README blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
