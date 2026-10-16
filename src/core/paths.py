"""Path policy for every file this server reads or writes on a caller's behalf.

Rejected outright: empty paths, NUL bytes, `..` components, Windows
extended-length / device prefixes (`\\\\?\\`, `\\\\.\\`), UNC shares, and
anything inside the Windows / Program Files folders. If AUTOCAD_MCP_ALLOWED_DIRS
is set (separated by `;` or the OS path separator), paths must also resolve
inside one of those directories. Relative paths are resolved against the
output directory (AUTOCAD_MCP_OUTPUT_DIR), never against the server's
working directory.

Writes additionally refuse to replace an existing file unless the caller
passed overwrite=True, and require the parent directory to exist (it is
created only when it is the server's own output directory).
"""

import os
from pathlib import Path, PureWindowsPath

from core.errors import CadError
from utils.constants import get_output_dir

_SYSTEM_DIRS = ("C:/Windows", "C:/Program Files", "C:/Program Files (x86)", "C:/ProgramData/Microsoft")


def _reject(message: str, path: str) -> CadError:
    return CadError(message, code="E_OUTPUT_PATH_REJECTED", details={"path": path})


def allowed_dirs() -> list[Path]:
    raw = os.environ.get("AUTOCAD_MCP_ALLOWED_DIRS", "").strip()
    if not raw:
        return []
    parts = [p.strip() for chunk in raw.split(";") for p in chunk.split(os.pathsep)]
    return [Path(p).expanduser().resolve() for p in parts if p]


def _check_text(path) -> str:
    if not isinstance(path, str) or not path.strip():
        raise _reject("path must be a non-empty string", str(path))
    if "\x00" in path:
        raise _reject("path contains a NUL byte", path)
    text = path.strip()
    if text.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise _reject("extended-length and device paths (\\\\?\\, \\\\.\\) are not accepted", path)
    if text.startswith(("\\\\", "//")):
        raise _reject("network (UNC) paths are not accepted; use a local drive path", path)
    if ".." in PureWindowsPath(text).parts or ".." in Path(text).parts:
        raise _reject("'..' path components are not accepted; pass an absolute path", path)
    return text


def _resolve(text: str) -> Path:
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path(get_output_dir()) / candidate
    return candidate.resolve()


def _check_location(resolved: Path, original: str) -> None:
    for system_dir in _SYSTEM_DIRS:
        try:
            if resolved.is_relative_to(Path(system_dir).resolve()):
                raise _reject(f"{resolved} is inside a system folder ({system_dir})", original)
        except ValueError:
            continue
    dirs = allowed_dirs()
    if dirs and not any(resolved.is_relative_to(d) for d in dirs):
        raise _reject(
            f"{resolved} is outside AUTOCAD_MCP_ALLOWED_DIRS ({'; '.join(str(d) for d in dirs)})",
            original,
        )


def _check_suffix(resolved: Path, suffixes, original: str) -> None:
    if suffixes and resolved.suffix.lower() not in suffixes:
        raise CadError(
            f"file extension must be one of {sorted(suffixes)}, got {resolved.suffix or '(none)'!r}",
            code="E_INVALID_INPUT",
            details={"path": original},
        )


def output_path(path: str, *, suffixes=(), overwrite: bool = False) -> Path:
    """Validate a path the server will write. Returns the resolved Path."""
    text = _check_text(path)
    resolved = _resolve(text)
    _check_location(resolved, text)
    _check_suffix(resolved, {s.lower() for s in suffixes}, text)
    if resolved.exists():
        if resolved.is_dir():
            raise _reject(f"{resolved} is a directory", text)
        if not overwrite:
            raise CadError(
                f"{resolved} already exists; pass overwrite=true to replace it",
                code="E_OUTPUT_EXISTS",
                details={"path": str(resolved)},
            )
    parent = resolved.parent
    if not parent.exists():
        if parent == Path(get_output_dir()).resolve():
            parent.mkdir(parents=True, exist_ok=True)
        else:
            raise CadError(
                f"folder {parent} does not exist; create it first or choose another path",
                code="E_FILE_NOT_FOUND",
                details={"path": text},
            )
    return resolved


def input_path(path: str, *, suffixes=()) -> Path:
    """Validate a path the server will read. Returns the resolved Path."""
    text = _check_text(path)
    resolved = _resolve(text)
    _check_location(resolved, text)
    _check_suffix(resolved, {s.lower() for s in suffixes}, text)
    if not resolved.is_file():
        raise CadError(f"{resolved} does not exist or is not a file", code="E_FILE_NOT_FOUND",
                       details={"path": text})
    return resolved
