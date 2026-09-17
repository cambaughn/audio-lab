"""LlmWorker — runs adapter calls off the UI thread.

Same long-lived QObject/QThread pattern as SpeechWorker. The adapter is
injected (fake until CP11; RecordingAdapter-wrapped either way so debug
always has ground truth). One request in flight at a time — push-to-talk
is turn-based by design.
"""

import threading

from PySide6.QtCore import QObject, Signal, Slot

from audio_lab.llm.adapter import LlmError
from audio_lab.llm.types import LlmRequest


class LlmWorker(QObject):
    request_started = Signal()
    response_ready = Signal(object, object)  # (LlmRequest, LlmResponse)
    error = Signal(str)
    finished = Signal()

    def __init__(self, adapter) -> None:
        super().__init__()
        self._adapter = adapter
        self._queue: list[LlmRequest] = []
        self._queue_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()

    def set_adapter(self, adapter) -> None:
        """Swap the adapter (FAKE/REAL toggle). Safe between requests."""
        with self._queue_lock:
            self._adapter = adapter

    def submit(self, request: LlmRequest) -> None:
        with self._queue_lock:
            self._queue.append(request)
        self._wake.set()

    def request_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    @Slot()
    def run(self) -> None:
        try:
            while not self._stop.is_set():
                self._wake.wait(timeout=0.2)
                self._wake.clear()
                while True:
                    with self._queue_lock:
                        if not self._queue:
                            break
                        request = self._queue.pop(0)
                        adapter = self._adapter
                    self.request_started.emit()
                    try:
                        response = adapter.complete(request)
                        self.response_ready.emit(request, response)
                    except LlmError as exc:
                        self.error.emit(f"LLM ERROR: {type(exc).__name__}: {exc}")
                    except Exception as exc:
                        self.error.emit(f"LLM ERROR: {exc}")
                    if self._stop.is_set():
                        break
        finally:
            self.finished.emit()
