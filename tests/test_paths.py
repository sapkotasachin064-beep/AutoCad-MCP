"""Output/input path policy (core/paths.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import paths
from core.errors import CadError


@pytest.fixture(autouse=True)
def _output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.delenv("AUTOCAD_MCP_ALLOWED_DIRS", raising=False)
    return tmp_path


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "C:\\safe\\..\\Windows\\x.dxf",
        "\\\\server\\share\\x.dxf",
        "//server/share/x.dxf",
        "\\\\?\\C:\\temp\\x.dxf",
        "//?/C:/temp/x.dxf",
        "C:\\Windows\\x.dxf",
        "C:\\Program Files\\x.dxf",
        "a\x00b.dxf",
    ],
)
def test_rejected_paths(bad):
    with pytest.raises(CadError) as info:
        paths.output_path(bad, suffixes=(".dxf",))
    assert info.value.code in ("E_OUTPUT_PATH_REJECTED",)


def test_relative_path_lands_in_output_dir(_output_dir):
    resolved = paths.output_path("plan.dxf", suffixes=(".dxf",))
    assert resolved == (_output_dir / "out" / "plan.dxf").resolve()
    assert resolved.parent.is_dir()  # the server's own output dir is created on demand


def test_wrong_suffix_is_invalid_input(tmp_path):
    with pytest.raises(CadError) as info:
        paths.output_path(str(tmp_path / "plan.txt"), suffixes=(".dxf",))
    assert info.value.code == "E_INVALID_INPUT"


def test_existing_file_needs_overwrite(tmp_path):
    target = tmp_path / "plan.dxf"
    target.write_text("x")
    with pytest.raises(CadError) as info:
        paths.output_path(str(target), suffixes=(".dxf",))
    assert info.value.code == "E_OUTPUT_EXISTS"
    assert paths.output_path(str(target), suffixes=(".dxf",), overwrite=True) == target.resolve()


def test_missing_parent_folder_is_not_created(tmp_path):
    with pytest.raises(CadError) as info:
        paths.output_path(str(tmp_path / "nope" / "plan.dxf"), suffixes=(".dxf",))
    assert info.value.code == "E_FILE_NOT_FOUND"


def test_allowed_dirs_restrict_writes(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("AUTOCAD_MCP_ALLOWED_DIRS", str(allowed))
    assert paths.output_path(str(allowed / "a.dxf"), suffixes=(".dxf",)).parent == allowed.resolve()
    with pytest.raises(CadError) as info:
        paths.output_path(str(tmp_path / "a.dxf"), suffixes=(".dxf",))
    assert info.value.code == "E_OUTPUT_PATH_REJECTED"


def test_input_path_must_exist(tmp_path):
    with pytest.raises(CadError) as info:
        paths.input_path(str(tmp_path / "missing.dxf"), suffixes=(".dxf",))
    assert info.value.code == "E_FILE_NOT_FOUND"
    existing = tmp_path / "there.dxf"
    existing.write_text("0\nEOF\n")
    assert paths.input_path(str(existing), suffixes=(".dxf",)) == existing.resolve()
