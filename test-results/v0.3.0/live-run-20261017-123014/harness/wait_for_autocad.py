"""Poll (read-only, never launches anything) until the owner has started AutoCAD and it answers COM.

Prints one line whenever the state changes; exits 0 when AutoCAD answers COM, 4 on timeout.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import com_probe as cp  # noqa: E402

LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 900.0
started = time.time()
last = None
while time.time() - started < LIMIT:
    pids = cp.acad_pids()
    state = {"pids": pids, "com": False, "docs": None}
    if pids:
        try:
            a = cp.app()
            state["com"] = True
            state["version"] = cp.retry(lambda: a.Version, attempts=3, delay=1.0)
            state["docs"] = cp.retry(lambda: a.Documents.Count, attempts=3, delay=1.0)
        except Exception as exc:  # still starting / busy / dialog open
            state["com_error"] = repr(exc)[:120]
    key = (tuple(pids), state["com"], state["docs"], state.get("com_error"))
    if key != last:
        print(time.strftime("%H:%M:%S"), state, flush=True)
        last = key
    if state["com"] and state["docs"] is not None:
        # stay stable for a few seconds before declaring it ready (a start-up crash would show here)
        time.sleep(6)
        if cp.acad_pids() == pids:
            print(time.strftime("%H:%M:%S"), "READY", state, flush=True)
            sys.exit(0)
        print(time.strftime("%H:%M:%S"), "process list changed during the 6 s stability check; waiting again", flush=True)
    time.sleep(4)
print(time.strftime("%H:%M:%S"), "TIMEOUT: AutoCAD did not become ready", flush=True)
sys.exit(4)
