"""Clip playback for review — in-memory, through Qt's native audio path.

Playback deliberately does NOT go through PortAudio: the app's input
stream is armed while clips are reviewed, and sharing one PortAudio host
with a simultaneous output stream produced crackle that three rounds of
gain changes never touched (learnings.md Observation 008). QAudioSink
plays straight from a memory buffer via CoreAudio — the same output path
every other macOS app uses — and raw audio still never touches disk.

Samples are played exactly as captured: no gain, no processing.
"""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from audio_lab.audio.clip import AudioClip


def _build_format(sample_rate: int) -> QAudioFormat:
    fmt = QAudioFormat()
    fmt.setSampleRate(sample_rate)
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
    return fmt


class ClipPlayer(QObject):
    """Plays one clip at a time from memory. Injectable sink for tests."""

    def __init__(self, parent=None, sink_factory=None) -> None:
        super().__init__(parent)
        self._sink_factory = sink_factory or self._default_sink_factory
        self._sink = None
        self._buffer: QBuffer | None = None

    @staticmethod
    def _default_sink_factory(fmt: QAudioFormat):
        device = QMediaDevices.defaultAudioOutput()
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()  # let CoreAudio pick; float 16 kHz
        return QAudioSink(device, fmt)  # is universally supported in practice

    def play(self, audio_clip: AudioClip) -> None:
        self.stop()
        fmt = _build_format(audio_clip.sample_rate)
        self._sink = self._sink_factory(fmt)
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(audio_clip.samples.astype("float32").tobytes()))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink.start(self._buffer)

    def stop(self) -> None:
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
            self._sink = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None
