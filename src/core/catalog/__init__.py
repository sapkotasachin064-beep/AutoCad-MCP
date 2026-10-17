"""Capability catalog.

The data modules in this package hold one tuple per catalogued capability
(statuses are never upgraded without evidence). `entries()` flattens them into
the JSON entries written to `docs/capabilities.json` by
`scripts/build_capabilities.py`.

Status vocabulary, exactly:
  planned      -- no code
  implemented  -- code exists, no automated test
  tested       -- automated tests exercise it (unit / mock_com / headless_dxf /
                  stdio_e2e / golden_regression)
  verified     -- executed against a live AutoCAD in this project, with recorded
                  evidence (data_live.py, evidence kind live_autocad)

A capability is not a tool: one MCP tool can serve several capabilities, and
internal capabilities (timeouts, error envelopes, pinning) have no tool of
their own. `exposed_by` names the public tools; `kind` says capability or
workflow.
"""

from collections import Counter

from core.catalog.data_core import DOMAINS as CORE
from core.catalog.data_delivery import DOMAINS as DELIVERY
from core.catalog.data_disciplines import DOMAINS as DISCIPLINES
from core.catalog.data_drafting import DOMAINS as DRAFTING
from core.catalog.data_live import LIVE_RUN, LIVE_VERIFIED

STATUSES = ("planned", "implemented", "tested", "verified")
SAFETY = ("read", "session", "write", "destructive", "external")
BACKENDS = ("com", "dxf", "both", "pure", "civil3d", "map3d", "plant3d", "electrical", "lt_ipc", "dotnet",
            "accore", "client")
EVIDENCE = ("unit", "mock_com", "headless_dxf", "stdio_e2e", "golden_regression", "live_autocad")

APP_VERSIONS = {
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
}


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
                "app_version": extra.get("app_version", defaults.get("app_version", APP_VERSIONS[backend])),
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
            live = LIVE_VERIFIED.get(f"{letter}:{slug}")
            if live is not None:
                # Promotion only from recorded live evidence (data_live.py).
                entry["status"] = "verified"
                entry["test_evidence"].append("live_autocad")
                entry["live_evidence"] = {"test": live, "run": LIVE_RUN["date"], "autocad": LIVE_RUN["autocad"]}
            out.append(entry)
    return out


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
        if (e["status"] == "verified") != ("live_autocad" in e["test_evidence"]):
            problems.append(f"{e['id']}: 'verified' and live_autocad evidence must go together")
        if e["status"] == "verified" and e["backend"] not in ("com", "both"):
            problems.append(f"{e['id']}: verified live but backend is {e['backend']}")
    known = {f"{e['category'].split('.')[0]}:{e['slug']}" for e in items}
    problems += [f"data_live names unknown entry {k}" for k in LIVE_VERIFIED if k not in known]
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
