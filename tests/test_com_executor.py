"""The dedicated COM thread (core/com_executor.py), exercised with plain
Python callables: no AutoCAD and no COM objects are involved."""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.com_executor import ComExecutor
from core.errors import CadError, ComTimeoutError


@pytest.fixture
def executor():
    return ComExecutor(initialize_com=False)


def test_runs_on_one_dedicated_thread(executor):
    names = {executor.run(lambda: threading.current_thread().name, timeout=5) for _ in range(5)}
    assert len(names) == 1
    assert names.pop().startswith("autocad-com-")


def test_returns_value_and_propagates_exceptions(executor):
    assert executor.run(lambda: 42, timeout=5) == 42
    with pytest.raises(ZeroDivisionError):
        executor.run(lambda: 1 / 0, timeout=5)
    assert executor.run(lambda: "still alive", timeout=5) == "still alive"


def test_calls_are_serialised(executor):
    active = []
    overlaps = []

    def job():
        active.append(1)
        if len(active) > 1:
            overlaps.append(True)
        time.sleep(0.05)
        active.pop()
        return True

    threads = [threading.Thread(target=lambda: executor.run(job, timeout=10)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlaps == []


def test_timeout_of_a_running_call_replaces_the_worker(executor):
    release = threading.Event()
    first_generation = executor.stats()["worker_generation"] or 1
    with pytest.raises(ComTimeoutError) as info:
        executor.run(lambda: release.wait(5), timeout=0.2, label="stuck_call")
    assert info.value.code == "E_COM_TIMEOUT"
    assert info.value.details["worker_replaced"] is True
    assert "could still complete" in info.value.message
    # The next call is served by a fresh worker immediately, not queued behind the stuck one.
    started = time.monotonic()
    assert executor.run(lambda: "fresh", timeout=2) == "fresh"
    assert time.monotonic() - started < 1.0
    assert executor.stats()["worker_generation"] > first_generation
    assert executor.stats()["abandoned_workers"] == 1
    release.set()


def test_call_queued_behind_a_long_call_is_not_started(executor):
    release = threading.Event()
    ran_second = []
    holder = threading.Thread(target=lambda: executor.run(lambda: release.wait(5), timeout=10, label="long"))
    holder.start()
    time.sleep(0.1)
    with pytest.raises(CadError) as info:
        executor.run(lambda: ran_second.append(True), timeout=0.2, label="queued")
    assert info.value.code == "E_COM_BUSY"
    assert "Nothing was sent" in info.value.message
    release.set()
    holder.join()
    time.sleep(0.3)
    assert ran_second == []  # the cancelled job never ran


def test_zero_timeout_waits_without_limit(executor):
    assert executor.run(lambda: (time.sleep(0.1), "done")[1], timeout=0) == "done"
