"""Packaging metadata stays consistent with the code (defect D3)."""

import re
import sys
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")  # Python 3.11+; the server itself supports 3.10

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from version import __version__  # noqa: E402

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_version_matches_single_source():
    assert PYPROJECT["project"]["version"] == __version__


def test_mcp_dependency_requires_sdk_v2():
    deps = PYPROJECT["project"]["dependencies"]
    mcp = next(d for d in deps if d.startswith("mcp"))
    assert re.search(r">=\s*2\.", mcp), mcp


def test_every_src_package_and_module_is_packaged():
    src = ROOT / "src"
    packages = {p.name for p in src.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    modules = {p.stem for p in src.glob("*.py") if p.stem != "__init__"}
    setuptools_cfg = PYPROJECT["tool"]["setuptools"]
    assert set(setuptools_cfg["packages"]) == packages
    assert set(setuptools_cfg["py-modules"]) == modules


def test_console_entry_point_targets_server_main():
    assert PYPROJECT["project"]["scripts"]["autocad-mcp"] == "server:main"
    import server

    assert callable(server.main)
