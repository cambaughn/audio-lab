"""SayWorker lifecycle with real (harmless, silent) processes.

The injectable command lets these tests exercise the full QProcess signal
path — start, finish, kill, spawn failure — without producing audio.
"""

import time

from PySide6.QtCore import QCoreApplication

from audio_lab.tts.speaker import SayWorker


def spin_until(app, predicate, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate(), "condition not reached before timeout"


class TestSayWorker:
    def test_speak_runs_and_finishes(self, qt_core_app):
        worker = SayWorker(command="true")  # exits 0 immediately, no audio
        started, finished, errors = [], [], []
        worker.speaking_started.connect(lambda: started.append(1))
        worker.speaking_finished.connect(lambda: finished.append(1))
        worker.error.connect(errors.append)
        worker.speak("hello")
        assert started == [1] and worker.is_speaking
        spin_until(qt_core_app, lambda: finished)
        assert not worker.is_speaking
        assert errors == []

    def test_empty_text_finishes_without_process(self, qt_core_app):
        worker = SayWorker(command="true")
        started, finished = [], []
        worker.speaking_started.connect(lambda: started.append(1))
        worker.speaking_finished.connect(lambda: finished.append(1))
        worker.speak("   ")
        assert finished == [1] and started == []

    def test_stop_kills_without_error(self, qt_core_app):
        worker = SayWorker(command="sleep")  # speak("5") -> sleep 5
        finished, errors = [], []
        worker.speaking_finished.connect(lambda: finished.append(1))
        worker.error.connect(errors.append)
        worker.speak("5")
        assert worker.is_speaking
        worker.stop()
        spin_until(qt_core_app, lambda: finished)
        assert errors == []  # a stopped utterance is not an error

    def test_new_speak_replaces_current(self, qt_core_app):
        worker = SayWorker(command="sleep")
        finished = []
        worker.speaking_finished.connect(lambda: finished.append(1))
        worker.speak("5")
        worker.speak("0.01")  # kills the first, starts the second
        spin_until(qt_core_app, lambda: len(finished) >= 2)

    def test_nonzero_exit_is_error(self, qt_core_app):
        worker = SayWorker(command="false")  # exits 1
        finished, errors = [], []
        worker.speaking_finished.connect(lambda: finished.append(1))
        worker.error.connect(errors.append)
        worker.speak("x")
        spin_until(qt_core_app, lambda: finished)
        assert errors and "TTS ERROR" in errors[0]

    def test_missing_command_reports_error(self, qt_core_app):
        worker = SayWorker(command="definitely-not-a-real-binary-xyz")
        finished, errors = [], []
        worker.speaking_finished.connect(lambda: finished.append(1))
        worker.error.connect(errors.append)
        worker.speak("x")
        spin_until(qt_core_app, lambda: finished)
        assert errors and "TTS ERROR" in errors[0]
