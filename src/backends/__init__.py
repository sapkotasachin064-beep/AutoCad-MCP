"""Engine backends. The server is pinned to exactly one for its lifetime
(AUTOCAD_MCP_BACKEND=com|dxf); see core/session.py."""

from core import session


def get_backend():
    """The backend this process is pinned to (created on first use)."""
    global _instance
    if _instance is None:
        name = session.backend_name()
        if name == "com":
            from backends.com import ComBackend

            _instance = ComBackend()
        else:
            from backends.dxf import DxfBackend

            _instance = DxfBackend()
    return _instance


def _reset_for_tests() -> None:
    global _instance
    _instance = None
    session._reset_backend_for_tests()


_instance = None
