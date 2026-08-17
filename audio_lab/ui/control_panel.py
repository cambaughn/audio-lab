"""Right-hand control panel — Batch 1 scope: microphone group + event log.

Signals-only contract with the main window (Identity Lab pattern): the
panel never imports the recorder or stores; the window calls the show_*
setters and listens to the signals. Later batches add SPEAKER,
AUTHORIZATION, TRANSCRIPT, LLM, TTS, and THRESHOLDS groups here.
"""

from PySide6.QtCore import QPoint, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QLabel,
    QListView,
    QPlainTextEdit,
    QPushButton,
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

    def __init__(self, parent=None) -> None:
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

    # -- window-called setters --

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
