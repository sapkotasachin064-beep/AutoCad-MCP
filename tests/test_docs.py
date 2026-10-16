"""Generated documentation stays in sync with the code."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_tool_reference_is_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_tool_docs.py"), "--check"],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
