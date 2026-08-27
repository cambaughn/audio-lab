"""Guided voice-enrollment dialog — six prompts, review-before-accept.

Flow per prompt: HOLD TO RECORD (button or Space) → the clip passes the
recorder's quality gates → embedded by the SpeechWorker → enrollment
gates (evaluate) → REVIEW / ACCEPT / RETRY. Nothing is stored until SAVE;
CANCEL stores nothing. The dialog borrows the main window's recorder,
speech worker, and player — it owns no hardware.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from audio_lab.identity.enrollment import (
    TARGET_SAMPLES,
    EnrollFeedback,
    VoiceEnrollmentSession,
    save_enrollment,
)
from audio_lab.identity.errors import IdentityStoreError
from audio_lab.ui import theme

CONSENT_TEXT = (
    "ENROLL ONLY WITH THIS PERSON'S INFORMED CONSENT. "
    "VOICE EMBEDDINGS (NOT AUDIO) ARE STORED LOCALLY."
)


class EnrollDialog(QDialog):
    """Modal enrollment flow. Emits enrolled(record) after a successful save."""

    enrolled = Signal(object)  # IdentityRecord

    def __init__(self, recorder, speech_worker, player, store, model_id, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ENROLL VOICE")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._recorder = recorder
        self._worker = speech_worker
        self._player = player
        self._store = store
        self._model_id = model_id
        self._session = VoiceEnrollmentSession()
        self._pending_clip = None
        self._pending_evidence = None
        self._awaiting_analysis = False

        root = QVBoxLayout(self)
        root.setSpacing(theme.SPACING)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("NAME"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Cameron")
        name_row.addWidget(self.name_edit, stretch=1)
        root.addLayout(name_row)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("secondary")
        root.addWidget(self.progress_label)

        self.prompt_label = QLabel()
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setMinimumHeight(48)
        root.addWidget(self.prompt_label)

        self.record_button = QPushButton("HOLD TO RECORD")
        self.record_button.setFixedHeight(48)
        self.record_button.pressed.connect(self._recorder.begin_utterance)
        self.record_button.released.connect(self._recorder.end_utterance)
        root.addWidget(self.record_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        review_row = QHBoxLayout()
        self.review_button = QPushButton("REVIEW")
        self.review_button.clicked.connect(self._review)
        self.accept_button = QPushButton("ACCEPT SAMPLE")
        self.accept_button.clicked.connect(self._accept_sample)
        self.retry_button = QPushButton("RETRY")
        self.retry_button.clicked.connect(self._retry)
        for b in (self.review_button, self.accept_button, self.retry_button):
            b.setEnabled(False)
            review_row.addWidget(b)
        root.addLayout(review_row)

        finish_row = QHBoxLayout()
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("SAVE ENROLLMENT")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        finish_row.addWidget(self.cancel_button)
        finish_row.addStretch(1)
        finish_row.addWidget(self.save_button)
        root.addLayout(finish_row)

        consent = QLabel(CONSENT_TEXT)
        consent.setObjectName("consent")
        consent.setWordWrap(True)
        root.addWidget(consent)

        self._recorder.clip_ready.connect(self._on_clip)
        self._recorder.clip_rejected.connect(self._on_clip_rejected)
        self._recorder.state_changed.connect(self._on_recorder_state)
        self._worker.analysis_ready.connect(self._on_analysis)
        self.name_edit.textChanged.connect(self._refresh)
        self._refresh()

    # -- recorder / worker events --

    def _on_clip(self, clip) -> None:
        self._pending_clip = clip
        self._pending_evidence = None
        self._awaiting_analysis = True
        self._set_status("PROCESSING…")
        self._worker.submit(clip)

    def _on_clip_rejected(self, reason: str) -> None:
        self._set_status(reason, error=True)

    def _on_recorder_state(self, state: str) -> None:
        self.record_button.setEnabled(state in ("MIC ARMED", "RECORDING"))

    def _on_analysis(self, analysis) -> None:
        if not self._awaiting_analysis or analysis.clip is not self._pending_clip:
            return
        self._awaiting_analysis = False
        self._pending_evidence = analysis.evidence
        feedback = self._session.evaluate(self._pending_clip, self._pending_evidence)
        if feedback is EnrollFeedback.ACCEPTED:
            self._set_status(
                f"SAMPLE OK ({self._pending_clip.duration_s:.1f}s) — REVIEW OR ACCEPT"
            )
            self._set_review_enabled(True)
        else:
            self._set_status(feedback.value, error=True)
            self._clear_pending()

    # -- review / accept / retry --

    def _review(self) -> None:
        if self._pending_clip is not None:
            self._player.play(self._pending_clip)

    def _accept_sample(self) -> None:
        feedback = self._session.accept(self._pending_clip, self._pending_evidence)
        if feedback is EnrollFeedback.ACCEPTED:
            self._set_status("SAMPLE ACCEPTED")
        else:
            self._set_status(feedback.value, error=True)
        self._clear_pending()
        self._refresh()

    def _retry(self) -> None:
        self._clear_pending()
        self._set_status("DISCARDED — RECORD AGAIN")

    def _save(self) -> None:
        try:
            record = save_enrollment(
                self._store, self.name_edit.text(), self._session, self._model_id
            )
        except (IdentityStoreError, ValueError) as exc:
            self._set_status(f"SAVE FAILED: {exc}", error=True)
            return
        self.enrolled.emit(record)
        self.accept()

    # -- housekeeping --

    def _clear_pending(self) -> None:
        self._pending_clip = None
        self._pending_evidence = None
        self._awaiting_analysis = False
        self._set_review_enabled(False)

    def _set_review_enabled(self, enabled: bool) -> None:
        for b in (self.review_button, self.accept_button, self.retry_button):
            b.setEnabled(enabled)

    def _refresh(self) -> None:
        prompt = self._session.current_prompt
        done = self._session.accepted_total
        self.progress_label.setText(f"SAMPLE {min(done + 1, TARGET_SAMPLES)} / {TARGET_SAMPLES}")
        if prompt is None:
            self.prompt_label.setText("ALL SAMPLES CAPTURED — SAVE TO FINISH")
            self.record_button.setEnabled(False)
        else:
            self.prompt_label.setText(f"[{prompt.kind}]  {prompt.text}")
        self.save_button.setEnabled(
            self._session.complete and bool(self.name_edit.text().strip())
        )

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setObjectName("error" if error else "")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            if self.record_button.isEnabled():
                self._recorder.begin_utterance()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            return  # Enter must never accidentally save/accept
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._recorder.end_utterance()
            return
        super().keyReleaseEvent(event)

    def done(self, result: int) -> None:  # noqa: N802 (Qt override)
        # disconnect borrowed signals so a closed dialog never reacts again
        for sig, slot in (
            (self._recorder.clip_ready, self._on_clip),
            (self._recorder.clip_rejected, self._on_clip_rejected),
            (self._recorder.state_changed, self._on_recorder_state),
            (self._worker.analysis_ready, self._on_analysis),
        ):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(result)
