"""The capability catalog stays honest: valid, current, and consistent with
the tools that actually exist."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core import catalog, registry  # noqa: E402
from core.catalog.data_live import LIVE_VERIFIED  # noqa: E402
import server  # noqa: E402,F401  (registers every tool)

CATALOG = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))


def test_catalog_validates():
    assert catalog.validate(catalog.entries()) == []


def test_catalog_files_are_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_capabilities.py"), "--check"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_exposed_tools_exist():
    tools = set(registry.specs())
    for entry in CATALOG["capabilities"]:
        for tool in entry["exposed_by"]:
            assert tool in tools, f"{entry['id']} names unknown tool {tool}"


def test_every_public_tool_is_catalogued():
    referenced = {t for e in CATALOG["capabilities"] if e["status"] != "planned" for t in e["exposed_by"]}
    missing = set(registry.specs()) - referenced
    assert not missing, f"tools with no catalog entry: {sorted(missing)}"


def test_verified_entries_carry_recorded_live_evidence():
    verified = {f"{e['category'].split('.')[0]}:{e['slug']}" for e in CATALOG["capabilities"] if e["status"] == "verified"}
    assert verified == set(LIVE_VERIFIED)
    for entry in CATALOG["capabilities"]:
        assert (entry["status"] == "verified") == ("live_autocad" in entry["test_evidence"]), entry["id"]


def test_ids_are_stable_format_and_unique():
    ids = [e["id"] for e in CATALOG["capabilities"]]
    assert len(ids) == len(set(ids))
    assert all(i.split("-")[0].isalpha() and i.split("-")[1].isdigit() for i in ids)


def test_no_raw_execution_tool_is_exposed():
    banned = ("lisp", "send_command", "run_command", "execute_code", "exec_", "eval", "send_code", "script")
    # autocad_execute_query runs one read-only SELECT against the scan cache (two write guards);
    # it cannot reach AutoCAD or the file system, so it is not code execution.
    allowed = {"autocad_execute_query"}
    offenders = [t for t in registry.specs() if t not in allowed and any(b in t for b in banned)]
    assert offenders == []
