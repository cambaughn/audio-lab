"""Main window — Batch 1: armed microphone, push-to-talk, waveform, log.

Owns the AudioRecorder (main-thread object; see audio/capture.py for the
threading model), the StatusLog, and settings persistence. Push-to-talk is
the big HOLD TO TALK button or holding Space while the window has focus —
deliberately in-app only (a global hotkey would need the Accessibility
permission; declined for v0.1).
"""

import subprocess
import time

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio_lab import __version__
from audio_lab.audio import playback
from audio_lab.audio.capture import AudioRecorder, RecorderState
from audio_lab.audio.clip import AudioClip
from audio_lab.audio.devices import list_input_devices
from audio_lab.config import settings as config
from audio_lab.diagnostics.metrics import StatusLog
from audio_lab.ui import theme
from audio_lab.ui.control_panel import ControlPanel
from audio_lab.ui.waveform_widget import WaveformWidget

CONSENT_TEXT = (
    "EXPERIMENTAL LOCAL VOICE-IDENTITY RESEARCH TOOL — USE ONLY WITH THE "
    "INFORMED CONSENT OF EVERYONE RECORDED — VOICE DATA REMAINS ON THIS "
    "MACHINE — NOT AN AUTHENTICATION SYSTEM"
)


class MainWindow(QMainWindow):
    def __init__(self, recorder: AudioRecorder | None = None) -> None:
        super().__init__()
        self.setWindowTitle("AUDIO LAB")
        self._settings = config.load_settings()
        self._status_log = StatusLog()
        self._last_clip: AudioClip | None = None

        self.recorder = recorder or AudioRecorder()
        self.recorder.setParent(self)

        self._recording_started: float | None = None
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(100)
        self._duration_timer.timeout.connect(self._tick_recording_duration)

        self._build_layout()
        self._wire_recorder()
        self._restore_geometry()

        self.log_event(self._build_info())
        self._refresh_devices()

    # -- layout --

    def _build_layout(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(theme.SPACING, theme.SPACING, theme.SPACING, theme.SPACING)
        outer.setSpacing(theme.SPACING)

        columns = QHBoxLayout()
        columns.setSpacing(theme.SPACING)

        left = QVBoxLayout()
        left.setSpacing(theme.SPACING)
        self.waveform = WaveformWidget()
        left.addWidget(self.waveform, stretch=1)

        self.ptt_button = QPushButton("HOLD TO TALK (SPACE)")
        self.ptt_button.setFixedHeight(56)
        self.ptt_button.setEnabled(False)
        self.ptt_button.pressed.connect(self._ptt_pressed)
        self.ptt_button.released.connect(self._ptt_released)
        left.addWidget(self.ptt_button)

        columns.addLayout(left, stretch=1)

        self.panel = ControlPanel()
        self.panel.arm_requested.connect(self._arm)
        self.panel.stop_requested.connect(self._disarm)
        self.panel.device_selected.connect(self._on_device_selected)
        self.panel.play_last_requested.connect(self._play_last)
        columns.addWidget(self.panel)

        outer.addLayout(columns, stretch=1)

        consent = QLabel(CONSENT_TEXT)
        consent.setObjectName("consent")
        consent.setWordWrap(True)
        outer.addWidget(consent)

        self.setCentralWidget(central)

    def _wire_recorder(self) -> None:
        self.recorder.state_changed.connect(self._on_recorder_state)
        self.recorder.level_changed.connect(self.panel.show_level)
        self.recorder.level_changed.connect(self.waveform.set_level)
        self.recorder.waveform_block.connect(self.waveform.add_points)
        self.recorder.clip_ready.connect(self._on_clip_ready)
        self.recorder.clip_rejected.connect(self._on_clip_rejected)
        self.recorder.error.connect(self._on_recorder_error)

    # -- build info --

    def _build_info(self) -> str:
        info = f"V{__version__}"
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=1.0,
            ).stdout.strip()
            if sha:
                info += f" · GIT {sha.upper()}"
        except Exception:
            pass  # not a git checkout — fine
        return f"SYSTEM START · {info}"

    # -- devices / arming --

    def _refresh_devices(self) -> None:
        devices = list_input_devices()
        self.panel.set_devices(devices, self._settings.input_device_name)
        names = ", ".join(d.name for d in devices) or "NONE"
        self.log_event(f"INPUT DEVICES: {names}")

    def _on_device_selected(self, device) -> None:
        self._settings.input_device_name = device.name
        self._save_settings()
        self.log_event(f"INPUT SELECTED: {device.name.upper()}")

    def _arm(self) -> None:
        device = self.panel.selected_device()
        name = device.name if device else None
        self.log_event(f"MIC ARM: {(name or 'DEFAULT').upper()}")
        self.recorder.arm(name)

    def _disarm(self) -> None:
        self.recorder.disarm()
        self.log_event("MIC STOPPED")

    # -- recorder events --

    def _on_recorder_state(self, state: str) -> None:
        is_error = state == RecorderState.ERROR.value
        recording = state == RecorderState.RECORDING.value
        self._set_ptt_recording_look(recording)
        if recording:
            self._recording_started = time.monotonic()
            self._duration_timer.start()
            self.panel.show_state("● RECORDING  0.0s")
        else:
            self._duration_timer.stop()
            self._recording_started = None
            self.panel.show_state(state, is_error=is_error)
        self.waveform.set_state_text(state)
        armed = state in (
            RecorderState.ARMED.value,
            RecorderState.RECORDING.value,
            RecorderState.DISABLED.value,
        )
        self.panel.set_armed(armed)
        self.ptt_button.setEnabled(state in (RecorderState.ARMED.value, RecorderState.RECORDING.value))

    def _on_clip_ready(self, clip: AudioClip) -> None:
        self._last_clip = clip
        summary = f"{clip.duration_s:.1f}s  {clip.rms_dbfs:.0f} dBFS"
        self.panel.show_last_clip(summary, playable=True)
        self.log_event(f"CLIP CAPTURED: {summary}")

    def _on_clip_rejected(self, reason: str) -> None:
        self.panel.show_last_clip(reason, playable=self._last_clip is not None)
        self.log_event(f"CLIP REJECTED: {reason}")

    def _on_recorder_error(self, message: str) -> None:
        self.log_event(message)

    def _play_last(self) -> None:
        if self._last_clip is not None:
            self.log_event("PLAYBACK: LAST CLIP")
            playback.play_clip(self._last_clip)

    def _set_ptt_recording_look(self, recording: bool) -> None:
        self.ptt_button.setText("● RECORDING — RELEASE TO SEND" if recording else "HOLD TO TALK (SPACE)")
        self.ptt_button.setObjectName("recording" if recording else "")
        self.ptt_button.style().unpolish(self.ptt_button)
        self.ptt_button.style().polish(self.ptt_button)

    def _tick_recording_duration(self) -> None:
        if self._recording_started is not None:
            elapsed = time.monotonic() - self._recording_started
            self.panel.show_state(f"● RECORDING  {elapsed:.1f}s")

    # -- push-to-talk (button + spacebar) --

    def _ptt_pressed(self) -> None:
        self.recorder.begin_utterance()

    def _ptt_released(self) -> None:
        self.recorder.end_utterance()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._ptt_pressed()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._ptt_released()
            return
        super().keyReleaseEvent(event)

    # -- log / settings / shutdown --

    def log_event(self, message: str) -> None:
        event = self._status_log.add(message)
        self.panel.append_log(StatusLog.format_event(event))

    def _restore_geometry(self) -> None:
        blob = self._settings.window_geometry
        if blob:
            self.restoreGeometry(QByteArray.fromBase64(blob.encode()))
        else:
            self.resize(860, 520)

    def _save_settings(self, include_geometry: bool = False) -> None:
        if include_geometry:
            self._settings.window_geometry = bytes(
                self.saveGeometry().toBase64()
            ).decode()
        config.save_settings(self._settings)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.recorder.disarm()
        self._save_settings(include_geometry=True)
        super().closeEvent(event)
