"""Error classification and the client-visible envelope (core/errors.py)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import db
from core import errors
from utils import geometry


def test_every_code_has_recoverable_flag_and_action():
    for code, (recoverable, action) in errors.ERROR_CODES.items():
        assert code.startswith("E_")
        assert isinstance(recoverable, bool)
        assert action and " " not in action


def test_unknown_code_is_a_programming_error():
    with pytest.raises(ValueError):
        errors.CadError("x", code="E_NOT_A_CODE")


def test_validation_error_is_still_a_value_error_and_classifies_as_invalid_input():
    exc = geometry.ValidationError("radius must be positive, got -1.0")
    assert isinstance(exc, ValueError)
    assert errors.classify(exc).code == "E_INVALID_INPUT"


def test_query_rejected_is_still_a_value_error_and_has_its_own_code():
    exc = db.QueryRejected("only read-only SELECT")
    assert isinstance(exc, ValueError)
    assert errors.classify(exc).code == "E_QUERY_REJECTED"


@pytest.mark.parametrize(
    "message,code",
    [
        ("AutoCAD is not running. Call autocad_launch_application first.", "E_AUTOCAD_NOT_RUNNING"),
        ("No document is open in AutoCAD.", "E_NO_ACTIVE_DOCUMENT"),
        ("No entity found with handle '2A': ...", "E_ENTITY_NOT_FOUND"),
        ("Entity creation could not be verified: ...", "E_VERIFICATION_FAILED"),
        ("Connected, but AutoCAD release '23.1' is below the minimum supported release", "E_AUTOCAD_UNSUPPORTED_RELEASE"),
        ("something else entirely", "E_COM_ERROR"),
    ],
)
def test_legacy_runtime_errors_are_classified(message, code):
    assert errors.classify(RuntimeError(message)).code == code


def test_com_error_is_classified_with_hresult():
    import pywintypes

    exc = pywintypes.com_error(-2147418111, "Call was rejected by callee.", None, None)
    classified = errors.classify(exc)
    assert classified.code == "E_AUTOCAD_NOT_RESPONDING"
    assert classified.details["hresult_hex"] == "0x80010001"
    assert classified.recoverable is True


def test_com_error_uses_excepinfo_description():
    import pywintypes

    excepinfo = (0, "AutoCAD.Application", "Key not found", None, 0, -2145386476)
    exc = pywintypes.com_error(-2147352567, "Exception occurred.", excepinfo, None)
    classified = errors.classify(exc)
    assert classified.code == "E_COM_ERROR"
    assert "Key not found" in classified.message


def test_unexpected_exception_is_internal_and_named():
    classified = errors.classify(KeyError("boom"))
    assert classified.code == "E_INTERNAL"
    assert "KeyError" in classified.message


@pytest.mark.parametrize(
    "exc",
    [
        PermissionError(13, "Access is denied", r"C:\out\locked.dxf"),
        OSError(22, "Invalid argument", "C:\\out\\" + "a" * 300 + ".dxf"),
    ],
)
def test_filesystem_error_naming_a_path_is_a_path_error_not_an_internal_error(exc):
    # Found by the V0.3.0 headless test campaign: exporting onto a read-only file, or to an over-long file
    # name, came back as E_INTERNAL ("report a bug").
    classified = errors.classify(exc)
    assert classified.code == "E_OUTPUT_PATH_REJECTED"
    assert classified.details["path"] == exc.filename
    assert classified.recoverable is False


def test_oserror_without_a_filename_keeps_the_internal_mapping():
    # COM start-up failures are OSErrors that name no file; they must not become path errors.
    assert errors.classify(OSError("[WinError -2147221005] Invalid class string")).code == "E_INTERNAL"


def test_missing_file_is_still_file_not_found_not_a_path_error():
    assert errors.classify(FileNotFoundError(2, "No such file or directory", "x.dxf")).code == "E_FILE_NOT_FOUND"


def test_envelope_shape_is_parseable_json():
    text = errors.error_text(geometry.ValidationError("bad"), tool="autocad_draw_line", backend="com")
    envelope = json.loads(text)
    assert envelope == {
        "ok": False,
        "error": {
            "code": "E_INVALID_INPUT",
            "message": "bad",
            "recoverable": False,
            "recommended_action": errors.ERROR_CODES["E_INVALID_INPUT"][1],
        },
        "tool": "autocad_draw_line",
        "backend": "com",
    }


def test_details_are_included_when_present():
    exc = errors.CadStateError("pinned elsewhere", code="E_DOCUMENT_CHANGED", details={"pinned_document": "a"})
    payload = errors.error_envelope(exc)["error"]
    assert payload["details"] == {"pinned_document": "a"}
    assert payload["recoverable"] is True


def test_unsupported_operation_names_operation_and_backend():
    exc = errors.UnsupportedOperationError("plot_pdf", "dxf", "needs AutoCAD")
    payload = exc.to_payload()
    assert payload["code"] == "E_UNSUPPORTED_BACKEND"
    assert payload["details"] == {"operation": "plot_pdf", "backend": "dxf"}
    assert "needs AutoCAD" in payload["message"]
