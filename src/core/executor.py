"""One dedicated COM thread for every AutoCAD call, with a per-call timeout.

Why: MCP SDK 2.x runs synchronous tool handlers on AnyIO worker threads, so
before V0.3.0 each tool initialised COM on whatever worker it landed on, two
concurrent tool calls drove AutoCAD from two threads at once, and nothing
bounded a call -- a modal dialog in AutoCAD blocked the tool forever.

Here every COM job is queued to a single long-lived thread (COM initialised
once, serialised access). The caller waits up to `timeout` seconds:

* the job never started (still queued behind another call) -> it is cancelled
  and E_COM_BUSY is raised; nothing reached AutoCAD, retrying is safe;
* the job started but did not finish -> the worker is abandoned (a blocked COM
  call cannot be interrupted), a fresh worker serves later calls, and
  E_COM_TIMEOUT says the abandoned call may still complete inside AutoCAD, so
  the drawing must be inspected before retrying a mutation.

The abandoned thread is a daemon: when its COM call eventually returns it
uninitialises COM and exits, and it never blocks interpreter shutdown.
"""

import logging
import queue
import threading
import time
from concurrent.futures import CancelledError, Future
from concurrent.futures import TimeoutError as FutureTimeoutError

from core.errors import CadError, ComTimeoutError

log = logging.getLogger("autocad_mcp.com")

_IDLE_PUMP_SECONDS = 0.2


def _com_init():
    try:
        import pythoncom
    except ImportError:  # non-Windows: plain callables still run, nothing to initialise
        return None
    pythoncom.CoInitialize()
    return pythoncom


class _Worker:
    def __init__(self, generation: int, initialize_com: bool):
        self.generation = generation
        self.jobs: queue.Queue = queue.Queue()
        self.abandoned = False
        self.current_label: str | None = None
        self.started_at: float | None = None
        self._initialize_com = initialize_com
        self.thread = threading.Thread(
            target=self._loop, name=f"autocad-com-{generation}", daemon=True
        )
        self.thread.start()

    def _loop(self):
        pythoncom = _com_init() if self._initialize_com else None
        try:
            while True:
                try:
                    item = self.jobs.get(timeout=_IDLE_PUMP_SECONDS)
                except queue.Empty:
                    if pythoncom is not None:
                        pythoncom.PumpWaitingMessages()
                    if self.abandoned:
                        return
                    continue
                if item is None:
                    return
                func, future, label = item
                if not future.set_running_or_notify_cancel():
                    continue  # caller gave up while it was queued
                self.current_label, self.started_at = label, time.monotonic()
                try:
                    result = func()
                except BaseException as exc:  # delivered to the waiting caller
                    if not future.done():
                        future.set_exception(exc)
                else:
                    if not future.done():
                        future.set_result(result)
                finally:
                    self.current_label, self.started_at = None, None
                if self.abandoned:
                    return
        finally:
            if pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass


class ComExecutor:
    def __init__(self, *, initialize_com: bool = True):
        self._initialize_com = initialize_com
        self._lock = threading.Lock()
        self._worker: _Worker | None = None
        self._generation = 0
        self.abandoned_workers = 0
        self.calls = 0

    def _get_worker(self) -> _Worker:
        with self._lock:
            if self._worker is None or self._worker.abandoned:
                self._generation += 1
                self._worker = _Worker(self._generation, self._initialize_com)
            return self._worker

    def run(self, func, *, timeout: float, label: str = "call"):
        """Run func() on the COM thread and return its result, re-raising its
        exception. timeout <= 0 waits without limit."""
        worker = self._get_worker()
        future: Future = Future()
        worker.jobs.put((func, future, label))
        self.calls += 1
        try:
            return future.result(timeout=None if timeout <= 0 else timeout)
        except FutureTimeoutError:
            if future.cancel():
                raise CadError(
                    f"{label} was not started: AutoCAD was still busy with an earlier call "
                    f"({worker.current_label}) after {timeout:g}s. Nothing was sent to AutoCAD.",
                    code="E_COM_BUSY",
                    details={"timeout_seconds": timeout, "busy_with": worker.current_label},
                ) from None
            self._abandon(worker)
            raise ComTimeoutError(
                f"{label} did not finish within {timeout:g}s. AutoCAD may be showing a modal "
                "dialog or waiting at a command prompt. The call could still complete inside "
                "AutoCAD after this error, so inspect the drawing before retrying a change. "
                "Increase AUTOCAD_MCP_COM_TIMEOUT if long operations are expected.",
                details={"timeout_seconds": timeout, "operation": label, "worker_replaced": True},
            ) from None
        except CancelledError:
            raise CadError(f"{label} was cancelled before it started.", code="E_COM_BUSY") from None

    def _abandon(self, worker: _Worker) -> None:
        with self._lock:
            if worker.abandoned:
                return
            worker.abandoned = True
            self.abandoned_workers += 1
            if self._worker is worker:
                self._worker = None
        log.error("COM worker %s abandoned after a timeout in %s", worker.generation, worker.current_label)
        # Fail everything queued behind the stuck call now instead of letting
        # each caller wait out its own timeout. None of it was started.
        while True:
            try:
                item = worker.jobs.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            _func, future, label = item
            if future.cancel():
                continue
            if not future.done():
                future.set_exception(CadError(
                    f"{label} was not started: the COM worker it was queued on timed out.",
                    code="E_COM_BUSY",
                ))
        worker.jobs.put(None)

    def stats(self) -> dict:
        worker = self._worker
        return {
            "worker_generation": self._generation,
            "worker_alive": bool(worker and worker.thread.is_alive()),
            "busy_with": worker.current_label if worker else None,
            "abandoned_workers": self.abandoned_workers,
            "calls": self.calls,
        }


_executor: ComExecutor | None = None
_executor_lock = threading.Lock()


def get_executor() -> ComExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ComExecutor()
        return _executor
