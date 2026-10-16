import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cad_engine import _parse_release, get_active_document, is_installed, verify_connection
from utils.constants import get_output_dir


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


def test_verify_connection_supported_release():
    app = SimpleNamespace(Version="24.3.1234.0 (LMS Tech)", Documents=object())
    status = verify_connection(app)
    assert status.connected is True
    assert status.supported is True
    assert status.release_year == 2024


def test_verify_connection_rejects_release_below_2021():
    app = SimpleNamespace(Version="23.1.0", Documents=object())
    status = verify_connection(app)
    assert status.connected is True
    assert status.supported is False
    assert "below the minimum supported release" in status.message


def test_verify_connection_unparseable_version_is_unsupported():
    app = SimpleNamespace(Version="garbage", Documents=object())
    status = verify_connection(app)
    assert status.connected is True
    assert status.supported is False
    assert status.release_year is None


def test_get_active_document_raises_when_no_documents_open():
    app = SimpleNamespace(Documents=SimpleNamespace(Count=0))
    try:
        get_active_document(app)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "No document is open" in str(exc)


def test_get_active_document_returns_active_document():
    # get_active_document calls clear_pending_command(doc) and
    # set_engineering_units(doc) before returning it (cancels a pending
    # command-line prompt, forces LUNITS/LUPREC/INSUNITS/MEASUREMENT), so the
    # sentinel needs a SendCommand and SetVariable it can no-op through.
    sentinel = SimpleNamespace(SendCommand=lambda *a, **k: None, SetVariable=lambda *a, **k: None)
    app = SimpleNamespace(Documents=SimpleNamespace(Count=1), ActiveDocument=sentinel)
    assert get_active_document(app) is sentinel
