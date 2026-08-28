"""Right-hand control panel — Batch 1 scope: microphone group + event log.

Signals-only contract with the main window (Identity Lab pattern): the
panel never imports the recorder or stores; the window calls the show_*
setters and listens to the signals. Later batches add SPEAKER,
AUTHORIZATION, TRANSCRIPT, LLM, TTS, and THRESHOLDS groups here.
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from audio_lab.audio.devices import InputDevice
from audio_lab.ui import theme

NO_MIC_TEXT = "NO INPUT DEVICES"
PANEL_WIDTH = 300


class ConsoleComboBox(QComboBox):
    """QComboBox whose dropdown is pinned flush below the control.

    On macOS, Qt positions the popup in native overlap mode with its own
    margins regardless of the `combobox-popup: 0` style hint (measured in
    Identity Lab: 7px left shift, wrong width). Setting the popup
    container's geometry explicitly after showPopup() is the only reliable
    fix.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setView(QListView())

    def showPopup(self) -> None:  # noqa: N802 (Qt override)
        super().showPopup()
        container = self.view().window()
        rows = min(self.count(), self.maxVisibleItems())
        row_h = sum(self.view().sizeHintForRow(i) for i in range(rows))
        chrome = container.height() - self.view().height()
        if chrome < 0 or chrome > 20:
            chrome = 2
        below = self.mapToGlobal(QPoint(0, self.height()))
        container.setGeometry(below.x(), below.y(), self.width(), row_h + chrome + 2)


class ControlPanel(QWidget):
    arm_requested = Signal()
    stop_requested = Signal()
    device_selected = Signal(object)  # InputDevice
    play_last_requested = Signal()
    enroll_requested = Signal()
    manage_requested = Signal()
    recognition_threshold_changed = Signal(float)
    private_threshold_changed = Signal(float)
    margin_changed = Signal(float)

    def __init__(
        self,
        recognition_threshold: float = 0.40,
        private_access_threshold: float = 0.55,
        match_margin: float = 0.10,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH)
        self._devices: list[InputDevice] = []
        self._armed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACING)

        # -- MICROPHONE --
        mic_box = QGroupBox("MICROPHONE")
        mic = QVBoxLayout(mic_box)
        mic.setSpacing(theme.SPACING - 2)

        self.device_combo = ConsoleComboBox()
        self.device_combo.activated.connect(self._on_device_activated)
        mic.addWidget(self.device_combo)

        self.arm_button = QPushButton("ARM MIC")
        self.arm_button.clicked.connect(self._on_arm_clicked)
        mic.addWidget(self.arm_button)

        self.state_label = QLabel("MIC IDLE")
        mic.addWidget(self.state_label)

        self.level_label = QLabel("LEVEL   ---.- dBFS")
        self.level_label.setObjectName("secondary")
        mic.addWidget(self.level_label)

        self.input_volume_label = QLabel("OS INPUT VOL  --")
        self.input_volume_label.setObjectName("secondary")
        mic.addWidget(self.input_volume_label)

        self.last_clip_label = QLabel("LAST CLIP  --")
        self.last_clip_label.setObjectName("secondary")
        mic.addWidget(self.last_clip_label)

        self.play_button = QPushButton("PLAY LAST CLIP")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.play_last_requested)
        mic.addWidget(self.play_button)

        root.addWidget(mic_box)

        # -- SPEAKER --
        speaker_box = QGroupBox("SPEAKER")
        speaker = QVBoxLayout(speaker_box)
        speaker.setSpacing(theme.SPACING - 4)
        self.model_label = QLabel("MODEL LOADING")
        speaker.addWidget(self.model_label)
        self.speaker_label = QLabel("SPEAKER  --")
        speaker.addWidget(self.speaker_label)
        self.similarity_label = QLabel("SIM  --    2ND  --")
        self.similarity_label.setObjectName("secondary")
        speaker.addWidget(self.similarity_label)
        root.addWidget(speaker_box)

        # -- AUTHORIZATION --
        auth_box = QGroupBox("AUTHORIZATION")
        auth = QVBoxLayout(auth_box)
        auth.setSpacing(theme.SPACING - 4)
        self.decision_label = QLabel("DECISION  --")
        auth.addWidget(self.decision_label)
        self.reason_label = QLabel("")
        self.reason_label.setObjectName("secondary")
        self.reason_label.setWordWrap(True)
        auth.addWidget(self.reason_label)
        root.addWidget(auth_box)

        # -- THRESHOLDS --
        thr_box = QGroupBox("THRESHOLDS")
        thr = QVBoxLayout(thr_box)
        thr.setSpacing(theme.SPACING - 4)
        self.recognition_slider, self.recognition_value = self._slider_row(
            thr, "RECOG", recognition_threshold, 5, 95
        )
        self.recognition_slider.valueChanged.connect(
            lambda v: self._on_slider(self.recognition_value, v, self.recognition_threshold_changed)
        )
        self.private_slider, self.private_value = self._slider_row(
            thr, "PRIVATE", private_access_threshold, 5, 95
        )
        self.private_slider.valueChanged.connect(
            lambda v: self._on_slider(self.private_value, v, self.private_threshold_changed)
        )
        self.margin_slider, self.margin_value = self._slider_row(
            thr, "MARGIN", match_margin, 0, 50
        )
        self.margin_slider.valueChanged.connect(
            lambda v: self._on_slider(self.margin_value, v, self.margin_changed)
        )
        root.addWidget(thr_box)

        # -- IDENTITY --
        id_box = QGroupBox("IDENTITY")
        id_layout = QVBoxLayout(id_box)
        self.enroll_button = QPushButton("ENROLL VOICE")
        self.enroll_button.setEnabled(False)
        self.enroll_button.clicked.connect(self.enroll_requested)
        id_layout.addWidget(self.enroll_button)
        self.manage_button = QPushButton("MANAGE SPEAKERS")
        self.manage_button.clicked.connect(self.manage_requested)
        id_layout.addWidget(self.manage_button)
        root.addWidget(id_box)

        # -- EVENT LOG --
        log_box = QGroupBox("EVENT LOG")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)
        self.log_view.setFixedHeight(180)
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box)

        root.addStretch(1)

    # -- slider plumbing (int sliders holding value*100) --

    def _slider_row(self, layout, label: str, value: float, lo: int, hi: int):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(round(value * 100))
        row.addWidget(slider, stretch=1)
        value_label = QLabel(f"{value:.2f}")
        value_label.setFixedWidth(34)
        row.addWidget(value_label)
        layout.addLayout(row)
        return slider, value_label

    @staticmethod
    def _on_slider(value_label: QLabel, raw: int, signal) -> None:
        value = raw / 100.0
        value_label.setText(f"{value:.2f}")
        signal.emit(value)

    # -- window-called setters --

    def show_model_state(self, text: str, is_error: bool = False) -> None:
        self.model_label.setText(text)
        self.model_label.setObjectName("error" if is_error else "")
        self.model_label.style().unpolish(self.model_label)
        self.model_label.style().polish(self.model_label)

    def show_speaker(self, speaker_text: str, similarity_text: str) -> None:
        self.speaker_label.setText(speaker_text)
        self.similarity_label.setText(similarity_text)

    def show_decision(self, decision_text: str, reason_text: str, dimmed: bool) -> None:
        self.decision_label.setText(decision_text)
        self.decision_label.setObjectName("secondary" if dimmed else "")
        self.decision_label.style().unpolish(self.decision_label)
        self.decision_label.style().polish(self.decision_label)
        self.reason_label.setText(reason_text)

    def set_enroll_enabled(self, enabled: bool) -> None:
        self.enroll_button.setEnabled(enabled)

    def set_thresholds(self, recognition: float, private_access: float) -> None:
        """Move the sliders programmatically (auto-calibration) without
        re-emitting the change signals."""
        for slider, label, value in (
            (self.recognition_slider, self.recognition_value, recognition),
            (self.private_slider, self.private_value, private_access),
        ):
            slider.blockSignals(True)
            slider.setValue(round(value * 100))
            slider.blockSignals(False)
            label.setText(f"{value:.2f}")

    def set_devices(self, devices: list[InputDevice], selected_name: str | None) -> None:
        self._devices = devices
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if not devices:
            self.device_combo.addItem(NO_MIC_TEXT)
            self.device_combo.setEnabled(False)
            self.arm_button.setEnabled(False)
        else:
            for dev in devices:
                suffix = " (default)" if dev.is_default else ""
                self.device_combo.addItem(f"{dev.name}{suffix}")
            self.device_combo.setEnabled(True)
            self.arm_button.setEnabled(True)
            index = next(
                (i for i, d in enumerate(devices) if d.name == selected_name), 0
            )
            self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)

    def selected_device(self) -> InputDevice | None:
        index = self.device_combo.currentIndex()
        if 0 <= index < len(self._devices):
            return self._devices[index]
        return None

    def show_state(self, text: str, is_error: bool = False) -> None:
        self.state_label.setText(text)
        self.state_label.setObjectName("error" if is_error else "")
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

    def show_level(self, peak: float, rms_dbfs: float) -> None:
        if rms_dbfs == float("-inf"):
            self.level_label.setText("LEVEL   ---.- dBFS")
        else:
            self.level_label.setText(f"LEVEL   {rms_dbfs:6.1f} dBFS")

    def show_input_volume(self, volume: int | None, low: bool) -> None:
        text = "OS INPUT VOL  --" if volume is None else f"OS INPUT VOL  {volume:3d}%"
        if low:
            text += "  ▲ LOW — RAISE IN SYSTEM SETTINGS → SOUND → INPUT"
        self.input_volume_label.setText(text)
        self.input_volume_label.setObjectName("error" if low else "secondary")
        self.input_volume_label.style().unpolish(self.input_volume_label)
        self.input_volume_label.style().polish(self.input_volume_label)

    def show_last_clip(self, summary: str, playable: bool) -> None:
        self.last_clip_label.setText(f"LAST CLIP  {summary}")
        self.play_button.setEnabled(playable)

    def set_armed(self, armed: bool) -> None:
        self._armed = armed
        self.arm_button.setText("STOP MIC" if armed else "ARM MIC")
        self.device_combo.setEnabled(not armed and bool(self._devices))

    def append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    # -- internal --

    def _on_arm_clicked(self) -> None:
        if self._armed:
            self.stop_requested.emit()
        else:
            self.arm_requested.emit()

    def _on_device_activated(self, index: int) -> None:
        if 0 <= index < len(self._devices):
            self.device_selected.emit(self._devices[index])
