"""Level meter + rolling waveform, hand-painted in the console idiom.

Shows the last few seconds of decimated |peak| points as a mirrored
amber trace, a live level bar along the bottom, and big centered state
text when the microphone is not delivering audio (VideoWidget pattern
from Identity Lab).
"""

from collections import deque

import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from audio_lab.ui import theme

HISTORY_SECONDS = 6
POINTS_PER_SECOND = 200  # matches AudioRecorder.WAVEFORM_POINTS_PER_SECOND


class WaveformWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 160)
        self._points: deque[float] = deque(maxlen=HISTORY_SECONDS * POINTS_PER_SECOND)
        self._peak = 0.0
        self._state_text = "MIC IDLE"
        self._live = False
        self._recording = False

    # -- slots wired to AudioRecorder --

    @Slot(object)
    def add_points(self, points: np.ndarray) -> None:
        self._points.extend(float(p) for p in points)
        self.update()

    @Slot(float, float)
    def set_level(self, peak: float, rms_dbfs: float) -> None:
        self._peak = peak
        self.update()

    @Slot(str)
    def set_state_text(self, text: str) -> None:
        self._state_text = text
        self._live = text in ("MIC ARMED", "RECORDING")
        self._recording = text == "RECORDING"
        if not self._live:
            self._points.clear()
            self._peak = 0.0
        self.update()

    # -- painting --

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))
        painter.setPen(QPen(QColor(theme.AMBER_DIM), theme.BORDER_W))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if not self._live:
            painter.setPen(QColor(theme.AMBER_DIM))
            font = painter.font()
            font.setPixelSize(theme.FONT_SIZE_STATE)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, f"** {self._state_text} **")
            return

        width = self.rect().width()
        mid_y = self.rect().height() / 2.0
        usable_h = self.rect().height() * 0.72
        color = QColor(theme.AMBER if self._recording else theme.AMBER_DIM)
        painter.setPen(QPen(color, 1))
        points = list(self._points)
        if points:
            n = len(points)
            span = self._points.maxlen
            x0 = width - (n / span) * (width - 2) - 1
            step = (width - 2) / span
            for i, p in enumerate(points):
                x = x0 + i * step
                half = max(0.5, min(1.0, p) * usable_h / 2.0)
                painter.drawLine(int(x), int(mid_y - half), int(x), int(mid_y + half))

        # level bar along the bottom edge
        bar_w = int(min(1.0, self._peak) * (width - 8))
        painter.fillRect(4, self.rect().height() - 7, bar_w, 3, QColor(theme.AMBER))
