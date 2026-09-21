"""Spoken output via macOS `say` — QProcess, no extra threads.

A deliberate simplification of the planned SayWorker-on-a-QThread:
QProcess already runs the child asynchronously and delivers finished /
error signals on the Qt event loop, so a worker thread would only be
forwarding them (same reasoning as the capture thread, learnings
Observation 003).

Only one utterance runs at a time, so all state lives on the worker (no
attributes on the C++ QProcess — that segfaults across deleteLater). A
replaced or stopped utterance has its signals disconnected before it is
killed, so late C++ callbacks never reach freed Python state.

Signal contract: speaking_finished fires exactly once per speak() that
actually starts a process (or immediately for empty text); a kill via
stop() is not an error; a spawn failure is.

The command is injectable so tests exercise the lifecycle with harmless
real processes instead of audio.
"""

from PySide6.QtCore import QObject, QProcess, Signal


class SayWorker(QObject):
    speaking_started = Signal()
    speaking_finished = Signal()
    error = Signal(str)

    def __init__(self, parent=None, command: str = "say") -> None:
        super().__init__(parent)
        self._command = command
        self._process: QProcess | None = None

    @property
    def is_speaking(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def speak(self, text: str) -> None:
        """Speak `text` (non-blocking); replaces any utterance in progress.
        Whitespace-only text finishes immediately without a process."""
        self.stop()
        text = text.strip()
        if not text:
            self.speaking_finished.emit()
            return
        process = QProcess(self)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        process.start(self._command, [text])
        self.speaking_started.emit()

    def stop(self) -> None:
        """STOP SPEAKING: abandon the current utterance. Its signals are
        disconnected first, so no finished/error reaches the worker — we
        emit speaking_finished ourselves, exactly once."""
        process, self._process = self._process, None
        if process is None:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.finished.disconnect(self._on_finished)
            process.errorOccurred.disconnect(self._on_error)
            process.kill()
            process.waitForFinished(500)
            process.deleteLater()
            self.speaking_finished.emit()
        else:
            process.deleteLater()

    # -- process events (Qt event loop) --

    def _on_finished(self, exit_code: int, exit_status) -> None:
        self._clear_process()
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code != 0:
            self.error.emit(f"TTS ERROR: say exited with {exit_code}")
        self.speaking_finished.emit()

    def _on_error(self, process_error) -> None:
        if process_error == QProcess.ProcessError.FailedToStart:
            self._clear_process()
            self.error.emit(f"TTS ERROR: {self._command} failed to start")
            self.speaking_finished.emit()
        # other runtime errors are followed by finished(), handled there

    def _clear_process(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
