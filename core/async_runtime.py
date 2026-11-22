"""A dedicated asyncio event loop running alongside Qt.

Qt owns the GUI thread; long-running work and provider calls must never block
it. This runtime starts one background loop, accepts thread-safe submissions,
and cancels outstanding tasks on shutdown.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Coroutine

from utils.logger import get_logger

log = get_logger("runtime")


class AsyncRuntime:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="javed-async", daemon=True)
        self._ready = threading.Event()
        self._started = False
        self._stopped = False
        self._lock = threading.Lock()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def running(self) -> bool:
        return self._started and not self._stopped and self._loop.is_running()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_forever()
        finally:
            try:
                pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:  # pragma: no cover - best-effort teardown
                log.exception("Async runtime teardown failed.")
            finally:
                self._loop.close()
                log.info("Async runtime stopped.")

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._thread.start()
            self._started = True
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Async runtime did not start within 5 seconds.")
        log.info("Async runtime started.")

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future:
        if not self.running:
            coroutine.close()
            raise RuntimeError("Async runtime is not running.")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def call_soon(self, callback, *args: Any) -> None:
        if not self.running:
            raise RuntimeError("Async runtime is not running.")
        self._loop.call_soon_threadsafe(callback, *args)

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started or self._stopped:
                return
            self._stopped = True

        if self._loop.is_running():
            async def _cancel_pending() -> None:
                current = asyncio.current_task()
                pending = [task for task in asyncio.all_tasks() if task is not current]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            try:
                future = asyncio.run_coroutine_threadsafe(_cancel_pending(), self._loop)
                future.result(timeout=timeout)
            except Exception:
                log.warning("Timed out while cancelling background tasks.", exc_info=True)
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass

        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("Async runtime thread did not exit within %.1fs.", timeout)
        else:
            log.info("Async runtime joined.")
