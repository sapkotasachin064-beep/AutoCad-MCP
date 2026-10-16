import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "MCP"))

from autocad.connection import _parse_release, is_installed
from autocad.config import get_output_dir


def test_parse_release_2021():
    assert _parse_release("24.0s (LMS Tech)") == 24.0


def test_parse_release_2024():
    assert _parse_release("24.3.1234.0") == 24.3


def test_parse_release_garbage():
    assert _parse_release("not a version") is None
    assert _parse_release("") is None


def test_is_installed_returns_bool():
    # Reads the real registry; result depends on the machine, so only the
    # type is asserted here (no AutoCAD on this dev machine either way).
    assert isinstance(is_installed(), bool)


def test_get_output_dir_default():
    os.environ.pop("AUTOCAD_MCP_OUTPUT_DIR", None)
    out = get_output_dir()
    assert out.endswith(os.path.join("Documents", "AutoCAD MCP Output"))


def test_get_output_dir_env_override(monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_OUTPUT_DIR", r"C:\custom\out")
    assert get_output_dir() == r"C:\custom\out"
