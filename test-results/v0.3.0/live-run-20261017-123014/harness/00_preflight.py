"""Step 0 - record the environment BEFORE AutoCAD is started. Touches nothing, launches nothing.

Writes evidence/preflight.json and a SHA-256 manifest of the repo's src/ and tests/ folders
(compared again at the end: this campaign must not change them).
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_harness as h  # noqa: E402
import com_probe as cp  # noqa: E402

REPO = h.REPO
EV = h.EVIDENCE


def manifest(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            out[str(p.relative_to(REPO)).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def git(*args) -> str:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(REPO), *args], capture_output=True, text=True, timeout=60).stdout.strip()


def main():
    EV.mkdir(parents=True, exist_ok=True)
    info = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "windows": platform.platform(),
        "system_python": sys.version,
        "system_python_exe": sys.executable,
        "acad_exe_pids_before_run": cp.acad_pids(),
        "git_branch": git("branch", "--show-current"),
        "git_head": git("log", "-1", "--format=%H %s"),
        "git_status_short": git("status", "--short").splitlines(),
    }
    try:
        from importlib.metadata import version
        info["packages"] = {d: version(d) for d in ("mcp", "pywin32", "pytest", "ezdxf", "pillow", "pdfplumber")}
    except Exception as exc:  # pragma: no cover
        info["packages_error"] = repr(exc)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"AutoCAD.Application\CurVer") as key:
            info["registry_ProgID_CurVer"] = winreg.QueryValue(key, "")
    except OSError as exc:
        info["registry_ProgID_CurVer"] = f"not found: {exc}"
    acad = Path(r"C:\Program Files\Autodesk\AutoCAD 2024\acad.exe")
    info["acad_exe_exists"] = acad.exists()
    ver = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-Item '{acad}').VersionInfo | Select-Object FileVersion,ProductVersion,ProductName | ConvertTo-Json -Compress"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    info["acad_exe_file_version"] = json.loads(ver) if ver else None
    h.dump(EV / "preflight.json", info)

    before = {"src": manifest(REPO / "src"), "tests": manifest(REPO / "tests")}
    h.dump(EV / "src_tests_manifest_before.json", before)
    (EV / "git_status_before.txt").write_text(git("status", "--short") + "\n\n" + git("diff", "--stat") + "\n", encoding="utf-8")
    print(json.dumps(info, indent=2, ensure_ascii=False))
    print(f"manifest: {len(before['src'])} src files, {len(before['tests'])} tests files")


main()
