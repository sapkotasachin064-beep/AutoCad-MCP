"""Build docs/catalog/capabilities.json and docs/feature-catalog.md from the
domain data modules in this folder.

    python scripts/catalog/build_catalog.py          # write both files
    python scripts/catalog/build_catalog.py --check  # fail if they are stale

Entry statuses (never upgraded without evidence):
  planned      -- not implemented
  implemented  -- code exists, no automated test exercises it
  tested       -- automated tests exercise it (unit / mock_com / headless_dxf / stdio_e2e)
  verified     -- executed against a live AutoCAD in this project, with recorded evidence

A capability is not a tool: one MCP tool can serve several capabilities, and
internal capabilities (timeouts, error envelopes, pinning) have no tool of
their own. `exposed_by` names the public tools; `kind` says capability or
workflow.
"""

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from data_core import DOMAINS as CORE  # noqa: E402
from data_drafting import DOMAINS as DRAFTING  # noqa: E402
from data_disciplines import DOMAINS as DISCIPLINES  # noqa: E402
from data_delivery import DOMAINS as DELIVERY  # noqa: E402

STATUSES = ("planned", "implemented", "tested", "verified")
SAFETY = ("read", "session", "write", "destructive", "external")
BACKENDS = ("com", "dxf", "both", "pure", "civil3d", "map3d", "plant3d", "electrical", "lt_ipc", "dotnet", "accore", "client")
EVIDENCE = ("unit", "mock_com", "headless_dxf", "stdio_e2e", "golden_regression")


def _letter_key(domain):
    letter = domain[0]
    return (len(letter), letter)


def entries():
    out = []
    for letter, title, defaults, items in sorted(CORE + DRAFTING + DISCIPLINES + DELIVERY, key=_letter_key):
        for number, item in enumerate(items, start=1):
            (slug, description, problem, status, backend, safety, exposed_by, evidence, *rest) = item
            extra = rest[0] if rest else {}
            entry = {
                "id": f"{letter}-{number:03d}",
                "slug": slug,
                "category": f"{letter}. {title}",
                "description": description,
                "user_problem": problem,
                "status": status,
                "backend": backend,
                "app_version": extra.get("app_version", defaults.get("app_version", _app_version(backend))),
                "inputs": extra.get("inputs", defaults.get("inputs", [])),
                "outputs": extra.get("outputs", defaults.get("outputs", [])),
                "failure_modes": extra.get("failure_modes", defaults.get("failure_modes", [])),
                "safety": safety,
                "kind": extra.get("kind", "capability"),
                "exposed_by": list(exposed_by),
                "test_evidence": list(evidence),
                "reference": extra.get("reference", defaults.get("reference", "")),
                "overlaps": extra.get("overlaps", []),
            }
            out.append(entry)
    return out


def _app_version(backend):
    return {
        "com": "AutoCAD 2021+ (full AutoCAD, Windows; not LT)",
        "dxf": "any OS with Python + ezdxf (no AutoCAD)",
        "both": "AutoCAD 2021+ (live) or ezdxf (headless)",
        "pure": "no CAD engine needed",
        "civil3d": "Civil 3D 2021+ (not installed on the development machine)",
        "map3d": "Map 3D 2021+ (not installed)",
        "plant3d": "Plant 3D 2021+ (not installed)",
        "electrical": "AutoCAD Electrical 2021+ (not installed)",
        "lt_ipc": "AutoCAD LT 2024+ with an AutoLISP dispatcher (not installed)",
        "dotnet": "AutoCAD 2021+ with an in-process .NET plugin (not built)",
        "accore": "AutoCAD 2021+ accoreconsole.exe",
        "client": "MCP client side",
    }[backend]


def validate(items):
    problems = []
    ids = Counter(e["id"] for e in items)
    problems += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    slugs = Counter((e["category"], e["slug"]) for e in items)
    problems += [f"duplicate slug {s}" for s, n in slugs.items() if n > 1]
    descriptions = Counter(e["description"].lower() for e in items)
    problems += [f"duplicate description {d!r}" for d, n in descriptions.items() if n > 1]
    for e in items:
        if e["status"] not in STATUSES:
            problems.append(f"{e['id']}: bad status {e['status']}")
        if e["safety"] not in SAFETY:
            problems.append(f"{e['id']}: bad safety {e['safety']}")
        if e["backend"] not in BACKENDS:
            problems.append(f"{e['id']}: bad backend {e['backend']}")
        if any(x not in EVIDENCE for x in e["test_evidence"]):
            problems.append(f"{e['id']}: bad evidence {e['test_evidence']}")
        if e["status"] == "tested" and not e["test_evidence"]:
            problems.append(f"{e['id']}: tested without evidence")
        if e["status"] == "planned" and (e["test_evidence"] or e["exposed_by"]):
            problems.append(f"{e['id']}: planned entry claims tools or tests")
        if e["status"] == "verified":
            problems.append(f"{e['id']}: 'verified' needs recorded live evidence, none exists yet")
    return problems


def summary(items):
    by_status = Counter(e["status"] for e in items)
    by_category = {}
    for e in items:
        row = by_category.setdefault(e["category"], Counter())
        row[e["status"]] += 1
        row["total"] += 1
    tools = sorted({t for e in items for t in e["exposed_by"]})
    return {"total": len(items), "by_status": dict(by_status), "by_category": {k: dict(v) for k, v in by_category.items()},
            "public_tools_referenced": len(tools)}


def markdown(items, stats):
    lines = [
        "# Feature catalog",
        "",
        "Generated by `python scripts/catalog/build_catalog.py` from `scripts/catalog/data_*.py`; do not edit by hand.",
        "Machine-readable version: [`catalog/capabilities.json`](catalog/capabilities.json).",
        "",
        "## How to read the counts",
        "",
        "- A **capability** is one distinct thing a user can get done; a **public MCP tool** can serve several, and",
        "  internal capabilities (timeouts, error envelopes, pinning) have no tool of their own. Tool count and",
        "  capability count are therefore different numbers and are reported separately.",
        "- **planned**: not implemented. **implemented**: code exists, no automated test. **tested**: exercised by",
        "  automated tests (unit, fake-COM, headless DXF, stdio end-to-end or golden regression).",
        "  **verified**: run against a live AutoCAD in this project with recorded evidence -- none yet, because",
        "  AutoCAD was not running during this rebuild.",
        "- Planned entries are a roadmap, not a promise; aliases and parameter variations are not counted.",
        "",
        "## Totals",
        "",
        f"- Catalogued capabilities: **{stats['total']}**",
    ]
    for status in STATUSES:
        lines.append(f"- {status}: {stats['by_status'].get(status, 0)}")
    lines += [f"- Public MCP tools referenced: {stats['public_tools_referenced']}", "", "## By category", "",
              "| Category | Total | planned | implemented | tested | verified |", "|---|---|---|---|---|---|"]
    for category, row in stats["by_category"].items():
        lines.append(f"| {category} | {row['total']} | {row.get('planned', 0)} | {row.get('implemented', 0)} | "
                     f"{row.get('tested', 0)} | {row.get('verified', 0)} |")
    current = None
    for e in items:
        if e["category"] != current:
            current = e["category"]
            lines += ["", f"## {current}", "", "| ID | Capability | Status | Backend | Safety | Tools |", "|---|---|---|---|---|---|"]
        tools = ", ".join(f"`{t}`" for t in e["exposed_by"]) or ("internal" if e["status"] != "planned" else "")
        lines.append(f"| {e['id']} | {e['description']} | {e['status']} | {e['backend']} | {e['safety']} | {tools} |")
    lines.append("")
    return "\n".join(lines)


def main(check: bool) -> int:
    items = entries()
    problems = validate(items)
    if problems:
        print("\n".join(problems))
        return 1
    stats = summary(items)
    doc = {"schema_version": 1, "statuses": list(STATUSES), "summary": stats, "capabilities": items}
    json_text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    md_text = markdown(items, stats)
    json_path = ROOT / "docs" / "catalog" / "capabilities.json"
    md_path = ROOT / "docs" / "feature-catalog.md"
    if check:
        stale = [p for p, t in ((json_path, json_text), (md_path, md_text))
                 if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale:
            print("stale: " + ", ".join(str(p) for p in stale))
            return 1
        print(f"catalog up to date: {stats['total']} capabilities")
        return 0
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_text, encoding="utf-8", newline="\n")
    md_path.write_text(md_text, encoding="utf-8", newline="\n")
    print(f"wrote {stats['total']} capabilities: {stats['by_status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
