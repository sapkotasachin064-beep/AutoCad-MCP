"""Typed errors with stable codes, and the envelope a client actually sees.

MCP SDK 2.x withholds the message of any exception that is not a ToolError:
the client only receives "Error executing tool <name>". So every expected
failure here is a CadError carrying a stable `code`, whether retrying can help
(`recoverable`), what to do next (`recommended_action`) and structured
`details`; server.py turns it into a ToolError whose text is the JSON envelope
from `error_envelope`.

The classes also inherit from the built-in exception the code raised before
V0.3.0 (ValueError for bad input, RuntimeError for AutoCAD state), so existing
`except ValueError` / `except RuntimeError` callers and tests keep working.
"""

import json

# code -> (recoverable, recommended_action). Recoverable means retrying the
# same call can succeed once the named condition is fixed outside the call
# (e.g. AutoCAD started); False means the call itself must change.
ERROR_CODES = {
    "E_INVALID_INPUT": (False, "correct_the_arguments_named_in_the_message"),
    "E_INVALID_CONFIG": (False, "fix_the_environment_variable_named_in_the_message_and_restart_the_server"),
    "E_QUERY_REJECTED": (False, "send_exactly_one_read_only_select_statement"),
    "E_AUTOCAD_NOT_INSTALLED": (False, "install_autocad_2021_or_newer_full_version_not_lt"),
    "E_AUTOCAD_NOT_RUNNING": (True, "call_autocad_launch_application_then_retry"),
    "E_AUTOCAD_NOT_RESPONDING": (True, "close_modal_dialogs_or_finish_the_active_command_in_autocad_then_retry"),
    "E_AUTOCAD_UNSUPPORTED_RELEASE": (False, "use_autocad_2021_or_newer"),
    "E_NO_ACTIVE_DOCUMENT": (True, "call_autocad_create_new_drawing_or_autocad_open_drawing"),
    "E_DOCUMENT_CHANGED": (True, "activate_the_pinned_drawing_in_autocad_or_call_autocad_unpin_document"),
    "E_DOCUMENT_PINNED": (False, "call_autocad_unpin_document_first_or_pass_pin_true"),
    "E_DOCUMENT_NOT_FOUND": (False, "call_autocad_list_drawings_and_use_a_listed_identity"),
    "E_UNSAVED_CHANGES": (False, "save_the_drawing_first_or_pass_discard_changes_true"),
    "E_ENTITY_NOT_FOUND": (False, "list_or_rescan_entities_to_get_current_handles"),
    "E_LAYER_NOT_FOUND": (False, "create_the_layer_or_use_a_listed_layer"),
    "E_BLOCK_NOT_FOUND": (False, "call_autocad_list_blocks_and_use_a_defined_block"),
    "E_LAYOUT_NOT_FOUND": (False, "call_autocad_list_layouts_and_use_a_listed_layout"),
    "E_UNSUPPORTED_BACKEND": (False, "call_autocad_get_capabilities_to_see_what_this_backend_supports"),
    "E_UNSUPPORTED_ENTITY": (False, "use_an_entity_type_listed_in_the_message"),
    "E_DEPENDENCY_MISSING": (False, "install_the_optional_dependency_named_in_the_message"),
    "E_OUTPUT_PATH_REJECTED": (False, "choose_a_normal_local_path_outside_system_folders_and_inside_allowed_dirs"),
    "E_OUTPUT_EXISTS": (False, "pass_overwrite_true_or_choose_a_new_path"),
    "E_FILE_NOT_FOUND": (False, "check_the_path"),
    "E_UNITS_MISMATCH": (False, "call_autocad_set_drawing_units_or_pass_the_matching_unit"),
    "E_COM_BUSY": (True, "retry_after_the_running_autocad_call_finishes"),
    "E_COM_TIMEOUT": (True, "inspect_the_drawing_before_retrying_because_the_timed_out_call_may_still_complete"),
    "E_COM_ERROR": (True, "read_the_com_message_then_retry_or_change_the_call"),
    "E_VERIFICATION_FAILED": (False, "inspect_the_drawing_state_before_continuing"),
    "E_PLOT_FAILED": (True, "check_the_layout_plot_area_and_the_dwg_to_pdf_device"),
    "E_INTERNAL": (False, "report_a_bug_with_the_server_log"),
}


class CadError(Exception):
    """Base for every error this server raises on purpose."""

    code = "E_INTERNAL"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None,
                 recoverable: bool | None = None, recommended_action: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if self.code not in ERROR_CODES:
            raise ValueError(f"unknown error code {self.code!r}")
        default_recoverable, default_action = ERROR_CODES[self.code]
        self.message = message
        self.details = details or {}
        self.recoverable = default_recoverable if recoverable is None else recoverable
        self.recommended_action = recommended_action or default_action

    def to_payload(self) -> dict:
        payload = {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "recommended_action": self.recommended_action,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class InvalidInputError(CadError, ValueError):
    code = "E_INVALID_INPUT"


class ConfigError(CadError, ValueError):
    code = "E_INVALID_CONFIG"


class CadStateError(CadError, RuntimeError):
    """AutoCAD/document state prevents the call (not running, no document,
    pinned document changed, entity gone, ...). Pass the specific `code`."""

    code = "E_COM_ERROR"


class UnsupportedOperationError(CadError, RuntimeError):
    code = "E_UNSUPPORTED_BACKEND"

    def __init__(self, operation: str, backend: str, reason: str = ""):
        message = f"{operation} is not supported by the {backend!r} backend"
        if reason:
            message += f": {reason}"
        super().__init__(message, details={"operation": operation, "backend": backend})


class DependencyMissingError(CadError, RuntimeError):
    code = "E_DEPENDENCY_MISSING"


class ComTimeoutError(CadError, TimeoutError):
    code = "E_COM_TIMEOUT"


class VerificationError(CadError, RuntimeError):
    code = "E_VERIFICATION_FAILED"


# Messages raised as plain RuntimeError by pre-V0.3.0 code paths, mapped to
# codes so even an unconverted raise site reaches the client classified.
_LEGACY_PATTERNS = (
    ("not installed", "E_AUTOCAD_NOT_INSTALLED"),
    ("autocad is not running", "E_AUTOCAD_NOT_RUNNING"),
    ("not responding to com", "E_AUTOCAD_NOT_RESPONDING"),
    ("not yet answering com", "E_AUTOCAD_NOT_RESPONDING"),
    ("below the minimum supported release", "E_AUTOCAD_UNSUPPORTED_RELEASE"),
    ("no document is open", "E_NO_ACTIVE_DOCUMENT"),
    ("no entity found with handle", "E_ENTITY_NOT_FOUND"),
    ("could not be verified", "E_VERIFICATION_FAILED"),
    ("refusing to overwrite", "E_OUTPUT_EXISTS"),
)

_COM_HRESULTS = {
    -2147418111: ("E_AUTOCAD_NOT_RESPONDING", "RPC_E_CALL_REJECTED: AutoCAD is busy"),
    -2147417846: ("E_AUTOCAD_NOT_RESPONDING", "RPC_E_SERVERCALL_RETRYLATER: AutoCAD is busy"),
    -2147023174: ("E_AUTOCAD_NOT_RUNNING", "RPC_S_SERVER_UNAVAILABLE: the AutoCAD process went away"),
    -2147417848: ("E_AUTOCAD_NOT_RUNNING", "RPC_E_DISCONNECTED: AutoCAD disconnected"),
}


def _com_error_payload(exc) -> CadError:
    args = getattr(exc, "args", ()) or ()
    hresult = args[0] if args else None
    text = args[1] if len(args) > 1 else str(exc)
    detail = None
    if len(args) > 2 and args[2]:
        # (wcode, source, description, helpfile, helpcontext, scode)
        excepinfo = args[2]
        if isinstance(excepinfo, tuple) and len(excepinfo) > 2 and excepinfo[2]:
            detail = excepinfo[2]
    code, meaning = _COM_HRESULTS.get(hresult, ("E_COM_ERROR", None))
    message = f"AutoCAD COM call failed: {detail or text}"
    if meaning:
        message += f" ({meaning})"
    details = {"hresult": hresult}
    if hresult is not None:
        details["hresult_hex"] = f"0x{hresult & 0xFFFFFFFF:08X}"
    return CadError(message, code=code, details=details)


def classify(exc: BaseException) -> CadError:
    """Turn any exception into a CadError (unchanged if it already is one)."""
    if isinstance(exc, CadError):
        return exc
    exc_type = type(exc)
    if exc_type.__name__ == "com_error" and exc_type.__module__ in ("pywintypes", "pythoncom"):
        return _com_error_payload(exc)
    if exc_type.__name__ == "QueryRejected":
        return CadError(str(exc), code="E_QUERY_REJECTED")
    if isinstance(exc, ValueError):
        return CadError(str(exc), code="E_INVALID_INPUT")
    if isinstance(exc, FileNotFoundError):
        return CadError(str(exc), code="E_FILE_NOT_FOUND")
    if isinstance(exc, (RuntimeError, OSError)):
        lowered = str(exc).lower()
        for needle, code in _LEGACY_PATTERNS:
            if needle in lowered:
                return CadError(str(exc), code=code)
        return CadError(str(exc), code="E_COM_ERROR" if isinstance(exc, RuntimeError) else "E_INTERNAL")
    return CadError(f"{exc_type.__name__}: {exc}", code="E_INTERNAL")


def error_envelope(exc: BaseException, *, tool: str | None = None, backend: str | None = None) -> dict:
    error = classify(exc)
    envelope = {"ok": False, "error": error.to_payload()}
    if tool:
        envelope["tool"] = tool
    if backend:
        envelope["backend"] = backend
    return envelope


def error_text(exc: BaseException, *, tool: str | None = None, backend: str | None = None) -> str:
    """The ToolError text: compact JSON a client or a model can parse."""
    return json.dumps(error_envelope(exc, tool=tool, backend=backend), ensure_ascii=False, default=str)
