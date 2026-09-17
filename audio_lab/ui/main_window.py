"""Main window — push-to-talk capture + speaker attribution.

Owns the AudioRecorder (main-thread object; see audio/capture.py for the
threading model), the SpeechWorker thread (models), the IdentityStore,
the matcher gallery, the StatusLog, and settings persistence.
Push-to-talk is the big HOLD TO TALK button or holding Space while the
window has focus — deliberately in-app only (a global hotkey would need
the Accessibility permission; declined for v0.1).

Per accepted clip: SpeechWorker embeds it → matcher scores it against the
gallery → decide() maps it to an access tier → SPEAKER / AUTHORIZATION
readouts update. While the enrollment dialog is open it owns all clips
and analyses; the window ignores them.
"""

import subprocess
import time

import numpy as np
from PySide6.QtCore import QByteArray, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio_lab import __version__
from audio_lab.audio.capture import AudioRecorder, RecorderState
from audio_lab.audio.playback import ClipPlayer
from audio_lab.audio.clip import AudioClip
from audio_lab.audio.devices import list_input_devices
from audio_lab.audio.system_input import LOW_INPUT_VOLUME, read_input_volume
from audio_lab.config import settings as config
from audio_lab.diagnostics.metrics import StatusLog
from audio_lab.identity import calibration
from audio_lab.identity.decision import AccessTier, decide
from audio_lab.identity.errors import IdentityStoreError
from audio_lab.identity.matcher import Matcher, build_gallery
from audio_lab.identity.store import DEFAULT_DB_FILENAME, SCHEMA_VERSION, IdentityStore
from audio_lab.speech.embedder import MODEL_ID
from audio_lab.speech.worker import ModelState, SpeechWorker
from audio_lab.ui import theme
from audio_lab.ui.control_panel import ControlPanel
from audio_lab.ui.enroll_dialog import EnrollDialog
from audio_lab.ui.manage_dialog import ManageDialog
from audio_lab.ui.waveform_widget import WaveformWidget

CONSENT_TEXT = (
    "EXPERIMENTAL LOCAL VOICE-IDENTITY RESEARCH TOOL — USE ONLY WITH THE "
    "INFORMED CONSENT OF EVERYONE RECORDED — VOICE DATA REMAINS ON THIS "
    "MACHINE — NOT AN AUTHENTICATION SYSTEM"
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        recorder: AudioRecorder | None = None,
        speech_worker: SpeechWorker | None = None,
        store: IdentityStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("AUDIO LAB")
        self._settings = config.load_settings()
        self._status_log = StatusLog()
        self._last_clip: AudioClip | None = None
        self._model_ready = False
        self._enroll_dialog: EnrollDialog | None = None
        self._matcher = Matcher([])

        self.recorder = recorder or AudioRecorder()
        self.recorder.setParent(self)
        self.player = ClipPlayer(self)

        self._store_error: str | None = None
        if store is not None:
            self.store = store
        else:
            try:
                self.store = IdentityStore(config.APP_DATA_DIR / DEFAULT_DB_FILENAME)
            except IdentityStoreError as exc:
                self.store = None
                self._store_error = str(exc)

        self._recording_started: float | None = None
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(100)
        self._duration_timer.timeout.connect(self._tick_recording_duration)

        self._build_layout()
        self._wire_recorder()
        self._restore_geometry()

        self.log_event(self._build_info())
        if self._store_error:
            self.log_event(f"STORE ERROR: {self._store_error} — RUNNING WITHOUT IDENTITIES")
        self._refresh_devices()
        self._rebuild_gallery()
        self._start_speech_worker(speech_worker)

    def _start_speech_worker(self, worker: SpeechWorker | None) -> None:
        self.speech_worker = worker or SpeechWorker()
        self._speech_thread = QThread(self)
        self.speech_worker.moveToThread(self._speech_thread)
        self._speech_thread.started.connect(self.speech_worker.run)
        self.speech_worker.model_state_changed.connect(self._on_model_state)
        self.speech_worker.analysis_ready.connect(self._on_analysis)
        self.speech_worker.error.connect(self.log_event)
        self.speech_worker.finished.connect(self._speech_thread.quit)
        self._speech_thread.start()

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

        self.panel = ControlPanel(
            recognition_threshold=self._settings.recognition_threshold,
            private_access_threshold=self._settings.private_access_threshold,
            match_margin=self._settings.match_margin,
        )
        self.panel.arm_requested.connect(self._arm)
        self.panel.stop_requested.connect(self._disarm)
        self.panel.device_selected.connect(self._on_device_selected)
        self.panel.play_last_requested.connect(self._play_last)
        self.panel.enroll_requested.connect(self._open_enroll)
        self.panel.manage_requested.connect(self._open_manage)
        self.panel.recognition_threshold_changed.connect(self._on_recognition_threshold)
        self.panel.private_threshold_changed.connect(self._on_private_threshold)
        self.panel.margin_changed.connect(self._on_margin)
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
        model_short = MODEL_ID.rsplit("/", maxsplit=1)[-1].upper()
        info = f"V{__version__} · MODEL {model_short} · SCHEMA V{SCHEMA_VERSION}"
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
        self._check_input_volume()
        self.recorder.arm(name)

    def _check_input_volume(self) -> None:
        volume = read_input_volume()
        low = volume is not None and volume < LOW_INPUT_VOLUME
        self.panel.show_input_volume(volume, low)
        if volume is not None:
            self.log_event(f"OS INPUT VOLUME: {volume}%" + (" — LOW, CAPTURE WILL BE QUIET" if low else ""))

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
        self._refresh_enroll_enabled()

    def _on_clip_ready(self, clip: AudioClip) -> None:
        if self._enrollment_active():
            return  # the enrollment dialog owns clips while it is open
        self._last_clip = clip
        summary = f"{clip.duration_s:.1f}s  {clip.rms_dbfs:.0f} dBFS"
        self.panel.show_last_clip(summary, playable=True)
        self.log_event(f"CLIP CAPTURED: {summary}")
        if self._model_ready:
            self.speech_worker.submit(clip)

    def _on_clip_rejected(self, reason: str) -> None:
        self.panel.show_last_clip(reason, playable=self._last_clip is not None)
        self.log_event(f"CLIP REJECTED: {reason}")

    def _on_recorder_error(self, message: str) -> None:
        self.log_event(message)

    def _play_last(self) -> None:
        if self._last_clip is not None:
            self.log_event("PLAYBACK: LAST CLIP")
            self.player.play(self._last_clip)

    # -- speaker identity --

    def _enrollment_active(self) -> bool:
        return self._enroll_dialog is not None and self._enroll_dialog.isVisible()

    def _refresh_enroll_enabled(self) -> None:
        self.panel.set_enroll_enabled(
            self._model_ready
            and self.store is not None
            and self.recorder.state
            in (RecorderState.ARMED, RecorderState.RECORDING)
        )

    def _on_model_state(self, state: str) -> None:
        self._model_ready = state == ModelState.READY.value
        self.panel.show_model_state(state, is_error=state == ModelState.FAILED.value)
        self.log_event(state)
        self._refresh_enroll_enabled()

    def _rebuild_gallery(self) -> None:
        if self.store is None:
            self._matcher = Matcher([])
            return
        try:
            gallery, warnings = build_gallery(self.store, MODEL_ID)
        except IdentityStoreError as exc:
            self.log_event(f"GALLERY ERROR: {exc}")
            self._matcher = Matcher([])
            return
        self._matcher = Matcher(gallery)
        for warning in warnings:
            self.log_event(f"GALLERY: {warning.upper()}")
        self.log_event(
            f"GALLERY LOADED: {self._matcher.identity_count} SPEAKERS, "
            f"{self._matcher.sample_count} SAMPLES"
        )
        self._auto_calibrate()

    def _auto_calibrate(self) -> None:
        """Recalibrate thresholds from enrolled data on every gallery change.

        The sliders remain manual overrides between enrollment changes; each
        enrollment change re-derives them from measured data (user feedback:
        calibration should never be a separate chore)."""
        try:
            dist = calibration.score_distributions(self.store, MODEL_ID)
        except IdentityStoreError as exc:
            self.log_event(f"CALIBRATION SKIPPED: {exc}")
            return
        suggestion = calibration.suggest_thresholds(dist)
        if suggestion is None:
            return
        self._settings.recognition_threshold = suggestion.recognition
        self._settings.private_access_threshold = suggestion.private_access
        self.panel.set_thresholds(suggestion.recognition, suggestion.private_access)
        self._save_settings()
        self.log_event(
            f"THRESHOLDS AUTO-CALIBRATED: RECOG {suggestion.recognition:.2f} "
            f"PRIVATE {suggestion.private_access:.2f} ({suggestion.basis})"
        )
        if dist.genuine and dist.impostor and min(dist.genuine) <= max(dist.impostor):
            self.log_event(
                "WARNING: GENUINE AND IMPOSTOR SCORES OVERLAP — VOICES MAY "
                "NOT SEPARATE RELIABLY"
            )

    def _on_analysis(self, analysis) -> None:
        if self._enrollment_active():
            return  # enrollment analyses belong to the dialog
        evidence = analysis.evidence
        probe = (
            evidence.embedding
            if evidence.embedding is not None
            else np.zeros(1, dtype=np.float32)  # matcher maps this to UNKNOWN
        )
        match = self._matcher.match(
            probe,
            threshold=self._settings.recognition_threshold,
            margin=self._settings.match_margin,
            top_k=self._settings.top_k,
        )
        decision = decide(
            match, private_access_threshold=self._settings.private_access_threshold
        )
        sim = f"{decision.similarity:.2f}" if decision.similarity is not None else "--"
        second = f"{decision.second_best:.2f}" if decision.second_best is not None else "--"
        if decision.tier is AccessTier.PRIVATE_VERIFIED:
            speaker_text = f"SPEAKER  {decision.display_name.upper()}"
            decision_text = "PRIVATE ACCESS GRANTED"
            dimmed = False
        elif decision.tier is AccessTier.RECOGNIZED:
            speaker_text = f"SPEAKER  PROBABLY {decision.display_name.upper()}"
            decision_text = "PRIVATE ACCESS DENIED"
            dimmed = True
        else:
            speaker_text = "SPEAKER  UNKNOWN"
            decision_text = "NO ACCESS — UNKNOWN SPEAKER"
            dimmed = True
        self.panel.show_speaker(speaker_text, f"SIM  {sim}    2ND  {second}")
        self.panel.show_decision(decision_text, decision.reason, dimmed)
        self.log_event(
            f"{speaker_text.replace('  ', ': ')} ({sim}) — {decision.reason} "
            f"[{analysis.clip.duration_s:.1f}S · {analysis.clip.rms_dbfs:.0f} dBFS "
            f"· EMBED {analysis.embed_ms:.0f} MS]"
        )

    def _open_enroll(self) -> None:
        if self.store is None or self._enrollment_active():
            return
        self._enroll_dialog = EnrollDialog(
            self.recorder,
            self.speech_worker,
            self.player,
            self.store,
            MODEL_ID,
            parent=self,
        )
        self._enroll_dialog.enrolled.connect(
            lambda record: self.log_event(
                f"IDENTITY ENROLLED: {record.display_name.upper()} "
                f"({record.sample_count} SAMPLES)"
            )
        )
        result = self._enroll_dialog.exec()
        self._enroll_dialog = None
        if result == QDialog.DialogCode.Accepted:
            self._rebuild_gallery()
        else:
            self.log_event("ENROLLMENT CANCELED — NOTHING STORED")

    def _open_manage(self) -> None:
        if self.store is None:
            return
        dialog = ManageDialog(self.store, parent=self)
        dialog.exec()
        if dialog.changed:
            self._rebuild_gallery()

    # -- thresholds --

    def _on_recognition_threshold(self, value: float) -> None:
        self._settings.recognition_threshold = value
        self._save_settings()

    def _on_private_threshold(self, value: float) -> None:
        self._settings.private_access_threshold = value
        self._save_settings()

    def _on_margin(self, value: float) -> None:
        self._settings.match_margin = value
        self._save_settings()

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
        self.player.stop()
        self.recorder.disarm()
        self.speech_worker.request_stop()
        self._speech_thread.quit()
        self._speech_thread.wait(5000)
        if self.store is not None:
            self.store.close()
        self._save_settings(include_geometry=True)
        super().closeEvent(event)
