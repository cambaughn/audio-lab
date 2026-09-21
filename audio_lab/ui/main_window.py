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
from enum import Enum

import numpy as np
from PySide6.QtCore import QByteArray, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
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
from audio_lab.conversation.ephemeral import EphemeralRegistry
from audio_lab.conversation.router import ContextRouter, build_request, detect_remember
from audio_lab.conversation.store import ConversationStore, ConversationStoreError
from audio_lab.conversation.store import DEFAULT_DB_FILENAME as CONVERSATIONS_DB
from audio_lab.conversation.types import ContextScope, RememberOutcome
from audio_lab.diagnostics.metrics import StatusLog
from audio_lab.identity import calibration
from audio_lab.llm.adapter import FakeLlmAdapter, RecordingAdapter
from audio_lab.llm.worker import LlmWorker
from audio_lab.identity.decision import AccessTier, decide
from audio_lab.identity.errors import IdentityStoreError
from audio_lab.identity.matcher import Matcher, build_gallery
from audio_lab.identity.store import DEFAULT_DB_FILENAME, SCHEMA_VERSION, IdentityStore
from audio_lab.speech.embedder import MODEL_ID
from audio_lab.speech.worker import ModelState, SpeechWorker
from audio_lab.tts.speaker import SayWorker
from audio_lab.ui import theme
from audio_lab.ui.control_panel import ControlPanel
from audio_lab.ui.conversation_view import ConversationView
from audio_lab.ui.enroll_dialog import EnrollDialog
from audio_lab.ui.manage_dialog import ManageDialog
from audio_lab.ui.waveform_widget import WaveformWidget

CONSENT_TEXT = (
    "EXPERIMENTAL LOCAL VOICE-IDENTITY RESEARCH TOOL — USE ONLY WITH THE "
    "INFORMED CONSENT OF EVERYONE RECORDED — VOICE DATA REMAINS ON THIS "
    "MACHINE — NOT AN AUTHENTICATION SYSTEM"
)

TTS_COOLDOWN_MS = 300  # absorbs room echo tail after speech ends


class AppState(str, Enum):
    """One turn at a time: PTT is possible only in READY. The recorder is
    force-disabled in every other state, so the app can never transcribe
    its own speech (belt-and-braces guard in _on_clip_ready)."""

    READY = "READY"
    PROCESSING = "PROCESSING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


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

        # conversation layer: persistent store + in-memory ephemerals + router
        self._conversation_error: str | None = None
        try:
            self.conversations = ConversationStore(config.APP_DATA_DIR / CONVERSATIONS_DB)
        except ConversationStoreError as exc:
            self.conversations = None
            self._conversation_error = str(exc)
        self.ephemerals = EphemeralRegistry()
        self.router = (
            ContextRouter(self.conversations, self.ephemerals)
            if self.conversations is not None
            else None
        )
        self.llm_recorder = RecordingAdapter(FakeLlmAdapter())
        self._llm_model = FakeLlmAdapter.MODEL
        self._pending_turn = None  # (decision, transcript) awaiting LLM reply

        self.say = SayWorker(self)
        self.say.speaking_started.connect(self._on_speaking_started)
        self.say.speaking_finished.connect(self._on_speaking_finished)
        self.say.error.connect(self.log_event)
        self._app_state = AppState.READY

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
        if self._conversation_error:
            self.log_event(
                f"CONVERSATION STORE ERROR: {self._conversation_error} — "
                "RUNNING WITHOUT CONTEXTS"
            )
        self._refresh_devices()
        self._rebuild_gallery()
        self._start_speech_worker(speech_worker)
        self._start_llm_worker()
        # restore a persisted REAL adapter only now that llm_worker exists;
        # setChecked triggers _on_use_fake_toggled, which needs the worker
        if not self._settings.use_fake_llm:
            self.panel.fake_llm_check.setChecked(False)

    def _start_llm_worker(self) -> None:
        self.llm_worker = LlmWorker(self.llm_recorder)
        self._llm_thread = QThread(self)
        self.llm_worker.moveToThread(self._llm_thread)
        self._llm_thread.started.connect(self.llm_worker.run)
        self.llm_worker.response_ready.connect(self._on_llm_response)
        self.llm_worker.error.connect(self._on_llm_error)
        self.llm_worker.finished.connect(self._llm_thread.quit)
        self._llm_thread.start()

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
        self.conversation = ConversationView()
        left.addWidget(self.conversation, stretch=2)
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
        # the panel outgrew small screens — scroll it rather than the window
        panel_scroll = QScrollArea()
        panel_scroll.setWidget(self.panel)
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setFixedWidth(self.panel.width() + 14)
        self.panel.arm_requested.connect(self._arm)
        self.panel.stop_requested.connect(self._disarm)
        self.panel.device_selected.connect(self._on_device_selected)
        self.panel.play_last_requested.connect(self._play_last)
        self.panel.enroll_requested.connect(self._open_enroll)
        self.panel.manage_requested.connect(self._open_manage)
        self.panel.end_session_requested.connect(self._end_guest_session)
        self.panel.stop_speaking_requested.connect(self.say.stop)
        self.panel.debug_toggled.connect(self._on_debug_toggled)
        self.panel.debug_check.setChecked(self._settings.debug_mode)
        self.panel.set_debug_visible(self._settings.debug_mode)
        self.panel.use_fake_llm_toggled.connect(self._on_use_fake_toggled)
        # NOTE: the persisted-real-adapter restore happens after the LLM
        # worker exists — see __init__ — not here, mid-layout.
        self.panel.recognition_threshold_changed.connect(self._on_recognition_threshold)
        self.panel.private_threshold_changed.connect(self._on_private_threshold)
        self.panel.margin_changed.connect(self._on_margin)
        columns.addWidget(panel_scroll)

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
        if self._app_state in (AppState.THINKING, AppState.SPEAKING):
            self.log_event("CLIP DISCARDED — TTS/LLM ACTIVE")
            return
        self._last_clip = clip
        summary = f"{clip.duration_s:.1f}s  {clip.rms_dbfs:.0f} dBFS"
        self.panel.show_last_clip(summary, playable=True)
        self.log_event(f"CLIP CAPTURED: {summary}")
        if self._model_ready:
            self._set_app_state(AppState.PROCESSING)
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
        reason = decision.reason
        if (
            decision.tier is not AccessTier.PRIVATE_VERIFIED
            and analysis.clip.duration_s < 2.0
        ):
            # measured on this mic: ~1 s clips score ~0.1 lower than 3 s+
            reason += "  ·  SHORT CLIP — LONGER SPEECH GIVES STRONGER ID"
        self.panel.show_speaker(speaker_text, f"SIM  {sim}    2ND  {second}")
        self.panel.show_decision(decision_text, reason, dimmed)

        # attributed transcript -> conversation view + TRANSCRIPT panel
        label = (
            decision.display_name.upper()
            if decision.display_name is not None
            else "UNKNOWN"
        )
        ephemeral = decision.tier is not AccessTier.PRIVATE_VERIFIED
        turn_tag = "EPHEMERAL — NOT PERSISTED" if ephemeral else None
        latency_text = (
            f"STT  {analysis.transcribe_ms:4.0f} MS    EMBED  {analysis.embed_ms:3.0f} MS"
        )
        if analysis.transcript is None:
            self.conversation.add_turn(label, decision.similarity, "(TRANSCRIPTION FAILED)", turn_tag)
            self.panel.show_transcript("(TRANSCRIPTION FAILED)", latency_text, is_error=True)
        elif analysis.transcript == "":
            self.conversation.add_turn(label, decision.similarity, "(NO SPEECH DECODED)", turn_tag)
            self.panel.show_transcript("(NO SPEECH DECODED)", latency_text)
        else:
            self.conversation.add_turn(label, decision.similarity, analysis.transcript, turn_tag)
            self.panel.show_transcript(analysis.transcript, latency_text)

        self.log_event(
            f"{speaker_text.replace('  ', ': ')} ({sim}) — {decision.reason} "
            f"[{analysis.clip.duration_s:.1f}S · {analysis.clip.rms_dbfs:.0f} dBFS "
            f"· EMBED {analysis.embed_ms:.0f} MS · STT {analysis.transcribe_ms:.0f} MS]"
        )
        if analysis.transcript:
            self._process_turn(decision, analysis.transcript, ephemeral)
        elif self._app_state is AppState.PROCESSING:
            self._set_app_state(AppState.READY)

    # -- the conversational turn: router -> LLM -> response --

    def _process_turn(self, decision, transcript: str, ephemeral: bool) -> None:
        if self.router is None:
            self._set_app_state(AppState.READY)
            return
        assistant_tag = "EPHEMERAL — NOT PERSISTED" if ephemeral else None

        fact = detect_remember(transcript)
        if fact is not None:
            outcome = self.router.handle_remember(decision, fact)
            if outcome is RememberOutcome.SAVED_PRIVATE:
                ack = "Noted — saved to your private memory."
                self.log_event(f"FACT SAVED (PRIVATE/{decision.display_name.upper()})")
            else:
                ack = "Noted for this session only — private access not verified."
                self.log_event("FACT NOT SAVED — PRIVATE ACCESS NOT VERIFIED")
            self.router.record_exchange(decision, transcript, ack)
            self.conversation.add_turn("ASSISTANT", None, ack, assistant_tag)
            self._speak(ack)
            return

        bundle = self.router.route(decision, transcript)
        request = build_request(bundle, transcript, model=self._llm_model)
        self._pending_turn = (decision, transcript, bundle, assistant_tag)
        self._set_app_state(AppState.THINKING)
        self.llm_worker.submit(request)

    def _on_llm_response(self, request, response) -> None:
        pending, self._pending_turn = self._pending_turn, None
        self.panel.show_llm_state(f"LLM  {self._llm_model.upper()}")
        if pending is None:
            self._set_app_state(AppState.READY)
            return
        decision, transcript, bundle, assistant_tag = pending
        self.router.record_exchange(decision, transcript, response.text)
        self.conversation.add_turn("ASSISTANT", None, response.text, assistant_tag)
        self.log_event(f"LLM REPLY ({len(response.text)} CHARS)")
        self._refresh_debug_panel(bundle)
        self._speak(response.text)

    def _on_llm_error(self, message: str) -> None:
        self._pending_turn = None
        self.panel.show_llm_state("LLM  ERROR", is_error=True)
        self.log_event(message)
        self._set_app_state(AppState.READY)

    def _refresh_debug_panel(self, bundle=None) -> None:
        if not self._settings.debug_mode:
            return
        request = self.llm_recorder.last_request
        if request is None:
            self.panel.show_debug_request("(NO REQUEST SENT YET)")
            return
        header = bundle.debug_summary if bundle is not None else ""
        self.panel.show_debug_request(
            f"{header}\n\n=== EXACT OUTBOUND REQUEST ===\n{request.serialized()}"
        )

    def _on_debug_toggled(self, enabled: bool) -> None:
        self._settings.debug_mode = enabled
        self.panel.set_debug_visible(enabled)
        self._save_settings()
        self._refresh_debug_panel()

    def _set_app_state(self, state: AppState) -> None:
        if state is self._app_state:
            return
        self._app_state = state
        # the recorder may record only in READY — everything else locks PTT
        self.recorder.set_enabled(state is AppState.READY)
        speaking = state is AppState.SPEAKING
        self.panel.show_tts_state("TTS  SPEAKING" if speaking else "TTS  IDLE", speaking)
        if state is AppState.THINKING:
            self.panel.show_llm_state("LLM  THINKING…")

    def _speak(self, text: str) -> None:
        self._set_app_state(AppState.SPEAKING)
        self.say.speak(text)

    def _on_speaking_started(self) -> None:
        self.log_event("TTS: SPEAKING")

    def _on_speaking_finished(self) -> None:
        if self._app_state is AppState.SPEAKING:
            # cooldown absorbs the echo tail before the mic re-arms
            QTimer.singleShot(TTS_COOLDOWN_MS, self._end_cooldown)

    def _end_cooldown(self) -> None:
        if self._app_state is AppState.SPEAKING:
            self._set_app_state(AppState.READY)

    def _end_guest_session(self) -> None:
        count = self.ephemerals.clear_all()
        self.log_event(f"GUEST SESSION ENDED — {count} EPHEMERAL SESSION(S) CLEARED")

    # -- FAKE/REAL adapter toggle --

    def _on_use_fake_toggled(self, use_fake: bool) -> None:
        if use_fake:
            self._activate_fake_adapter()
        elif not self._activate_real_adapter():
            self.panel.fake_llm_check.blockSignals(True)
            self.panel.fake_llm_check.setChecked(True)
            self.panel.fake_llm_check.blockSignals(False)
            self._activate_fake_adapter()  # stay on fake; label reflects it
            use_fake = True
        self._settings.use_fake_llm = use_fake
        self._save_settings()

    def _activate_fake_adapter(self) -> None:
        self.llm_recorder = RecordingAdapter(FakeLlmAdapter())
        self._llm_model = FakeLlmAdapter.MODEL
        self.llm_worker.set_adapter(self.llm_recorder)
        self.panel.show_llm_state("LLM  FAKE (LOCAL)")
        self.log_event("LLM ADAPTER: FAKE (LOCAL)")

    def _activate_real_adapter(self) -> bool:
        from audio_lab.llm.adapter import LlmConfigError
        from audio_lab.llm.anthropic_adapter import AnthropicAdapter
        from audio_lab.llm.config import load_llm_config

        try:
            llm_config = load_llm_config()
            adapter = AnthropicAdapter(llm_config)
        except LlmConfigError as exc:
            self.panel.show_llm_state("LLM  NOT CONFIGURED", is_error=True)
            self.log_event(f"LLM NOT CONFIGURED: {exc}")
            return False
        self.llm_recorder = RecordingAdapter(adapter)
        self._llm_model = llm_config.model
        self.llm_worker.set_adapter(self.llm_recorder)
        self.panel.show_llm_state(f"LLM  {llm_config.model.upper()}")
        self.log_event(f"LLM ADAPTER: ANTHROPIC ({llm_config.model})")
        return True

    def _open_enroll(self) -> None:
        if self.store is None or self._enrollment_active():
            return
        self.say.stop()
        self._set_app_state(AppState.READY)
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
        available = self.screen().availableGeometry() if self.screen() else None
        if available is None:
            self.resize(880, 560)
            return
        if not blob:
            self.resize(min(920, available.width() - 40), min(640, available.height() - 60))
        # never open taller/wider than the screen (restored or default)
        if self.height() > available.height() or self.width() > available.width():
            self.resize(
                min(self.width(), available.width() - 20),
                min(self.height(), available.height() - 40),
            )
            self.move(available.x() + 10, available.y() + 10)

    def _save_settings(self, include_geometry: bool = False) -> None:
        if include_geometry:
            self._settings.window_geometry = bytes(
                self.saveGeometry().toBase64()
            ).decode()
        config.save_settings(self._settings)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.player.stop()
        self.say.stop()
        self.recorder.disarm()
        self.speech_worker.request_stop()
        self.llm_worker.request_stop()
        self._speech_thread.quit()
        self._speech_thread.wait(5000)
        self._llm_thread.quit()
        self._llm_thread.wait(5000)
        if self.store is not None:
            self.store.close()
        if self.conversations is not None:
            self.conversations.close()
        self._save_settings(include_geometry=True)
        super().closeEvent(event)
