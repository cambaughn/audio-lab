"""Push-to-talk microphone capture.

Threading model — a deliberate simplification of the original plan
(docs/learnings.md Observation 003): the PortAudio callback already runs on
its own native thread regardless of Qt, so there is no dedicated capture
QThread. AudioRecorder lives on the main thread; the callback touches only
lock-protected state; a ~15 Hz QTimer publishes levels/waveform and
finalizes clips via Qt signals.

Privacy contract: while ARMED the callback computes level scalars and
waveform peaks and DISCARDS the samples — metering only, never recording.
Samples are retained solely between begin_utterance() and end_utterance()
(or the 30 s auto-stop). Raw audio never touches disk.

The stream backend is injectable (stream_factory) so every state
transition is testable without a microphone.
"""

import threading
from enum import Enum

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from audio_lab.audio import clip as clipmod

PERMISSION_MESSAGE = (
    "MIC PERMISSION SUSPECTED — GRANT MICROPHONE ACCESS TO YOUR TERMINAL IN "
    "SYSTEM SETTINGS → PRIVACY & SECURITY → MICROPHONE, THEN RELAUNCH"
)


class RecorderState(str, Enum):
    IDLE = "MIC IDLE"
    ARMED = "MIC ARMED"
    RECORDING = "RECORDING"
    DISABLED = "MIC DISABLED"
    ERROR = "MIC ERROR"


def _default_stream_factory(device, sample_rate: int, blocksize: int, callback):
    import sounddevice as sd

    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        device=device,
        callback=callback,
    )
    stream.start()
    return stream


class AudioRecorder(QObject):
    """Owns the input stream and the push-to-talk buffer.

    Signals are the only outward channel; the PortAudio callback never
    raises and never emits — it only mutates lock-protected state that
    _tick() publishes from the Qt thread.
    """

    state_changed = Signal(str)  # RecorderState value
    level_changed = Signal(float, float)  # peak (0..1), rms dBFS
    waveform_block = Signal(object)  # np.ndarray of decimated |peak| points
    clip_ready = Signal(object)  # gate-accepted AudioClip
    clip_rejected = Signal(str)  # human-readable gate reason
    error = Signal(str)

    METER_INTERVAL_MS = 66
    WAVEFORM_POINTS_PER_SECOND = 200
    START_RETRIES = 1  # first stream start after a fresh permission grant can fail once
    SILENCE_CHECK_SECONDS = 1.0

    def __init__(
        self,
        stream_factory=None,
        sample_rate: int = clipmod.SAMPLE_RATE,
        blocksize: int = 1024,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._stream_factory = stream_factory or _default_stream_factory
        self._sample_rate = sample_rate
        self._blocksize = blocksize
        self._wave_bin = max(1, sample_rate // self.WAVEFORM_POINTS_PER_SECOND)
        self._max_samples = int(clipmod.MAX_UTTERANCE_S * sample_rate)

        self._stream = None
        self._state = RecorderState.IDLE
        self._enabled = True

        self._lock = threading.Lock()
        self._last_peak = 0.0
        self._last_rms = 0.0
        self._wave_carry = np.zeros(0, dtype=np.float32)
        self._wave_points: list[np.ndarray] = []
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._recorded_samples = 0
        self._auto_stop = False
        self._armed_samples_seen = 0
        self._armed_max_abs = 0.0
        self._silence_checked = False

        self._timer = QTimer(self)
        self._timer.setInterval(self.METER_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # -- state --

    @property
    def state(self) -> RecorderState:
        return self._state

    def _set_state(self, state: RecorderState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state.value)

    # -- lifecycle (UI thread) --

    def arm(self, device) -> None:
        """Open the input stream on `device` (name, index, or None=default).

        One automatic retry: the very first stream start after a fresh
        permission grant can fail spuriously (environment.md, CP2).
        """
        if self._stream is not None:
            return
        last_exc: Exception | None = None
        for _ in range(self.START_RETRIES + 1):
            try:
                self._stream = self._stream_factory(
                    device, self._sample_rate, self._blocksize, self._callback
                )
                break
            except Exception as exc:
                last_exc = exc
                self._stream = None
        if self._stream is None:
            self._set_state(RecorderState.ERROR)
            self.error.emit(f"MIC ERROR: {last_exc}")
            return
        with self._lock:
            self._armed_samples_seen = 0
            self._armed_max_abs = 0.0
            self._silence_checked = False
            self._wave_carry = np.zeros(0, dtype=np.float32)
            self._wave_points.clear()
        self._timer.start()
        self._set_state(RecorderState.ARMED if self._enabled else RecorderState.DISABLED)

    def disarm(self) -> None:
        """Close the stream and drop any in-flight buffer."""
        self._timer.stop()
        self._drop_recording()
        self._close_stream()
        self._set_state(RecorderState.IDLE)

    def set_enabled(self, enabled: bool) -> None:
        """TTS/processing lockout. Disabling mid-utterance drops the buffer."""
        self._enabled = enabled
        if not enabled:
            self._drop_recording()
            if self._stream is not None and self._state is not RecorderState.ERROR:
                self._set_state(RecorderState.DISABLED)
        elif self._stream is not None and self._state is RecorderState.DISABLED:
            self._set_state(RecorderState.ARMED)

    # -- push-to-talk (UI thread) --

    def begin_utterance(self) -> None:
        if self._state is not RecorderState.ARMED:
            return
        with self._lock:
            self._recording = True
            self._chunks = []
            self._recorded_samples = 0
            self._auto_stop = False
        self._set_state(RecorderState.RECORDING)

    def end_utterance(self) -> None:
        if self._state is not RecorderState.RECORDING:
            return
        self._finish_recording()

    # -- PortAudio callback thread: locked state only, never raises --

    def _callback(self, indata, frames, time_info, status) -> None:
        block = np.asarray(indata, dtype=np.float32).ravel()
        if block.size == 0:
            return
        peak = float(np.max(np.abs(block)))
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
        with self._lock:
            self._last_peak = peak
            self._last_rms = rms
            self._armed_samples_seen += block.size
            self._armed_max_abs = max(self._armed_max_abs, peak)
            merged = np.concatenate((self._wave_carry, np.abs(block)))
            usable = (merged.size // self._wave_bin) * self._wave_bin
            if usable:
                bins = merged[:usable].reshape(-1, self._wave_bin)
                self._wave_points.append(bins.max(axis=1))
            self._wave_carry = merged[usable:]
            if self._recording:
                if self._recorded_samples < self._max_samples:
                    self._chunks.append(block.copy())
                    self._recorded_samples += block.size
                else:
                    self._auto_stop = True
            # ARMED and not recording: block is discarded here — metering only.

    # -- Qt-thread publisher --

    def _tick(self) -> None:
        with self._lock:
            peak, rms = self._last_peak, self._last_rms
            points = (
                np.concatenate(self._wave_points) if self._wave_points else None
            )
            self._wave_points.clear()
            auto_stop = self._auto_stop
            seen, max_abs = self._armed_samples_seen, self._armed_max_abs
            silence_checked = self._silence_checked
        rms_dbfs = 20.0 * float(np.log10(rms)) if rms > 0.0 else float("-inf")
        self.level_changed.emit(peak, rms_dbfs)
        if points is not None and points.size:
            self.waveform_block.emit(points)
        if not silence_checked and seen >= self._sample_rate * self.SILENCE_CHECK_SECONDS:
            with self._lock:
                self._silence_checked = True
            if max_abs == 0.0:
                self._timer.stop()
                self._drop_recording()
                self._close_stream()
                self._set_state(RecorderState.ERROR)
                self.error.emit(PERMISSION_MESSAGE)
                return
        if auto_stop and self._state is RecorderState.RECORDING:
            self._finish_recording()

    # -- internals --

    def _finish_recording(self) -> None:
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
            self._auto_stop = False
        samples = (
            np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        )
        self._set_state(RecorderState.ARMED if self._enabled else RecorderState.DISABLED)
        audio_clip = clipmod.make_clip(samples, self._sample_rate)
        verdict, reason = clipmod.gate_clip(audio_clip)
        if verdict is clipmod.ClipVerdict.ACCEPTED:
            self.clip_ready.emit(audio_clip)
        else:
            self.clip_rejected.emit(reason)

    def _drop_recording(self) -> None:
        with self._lock:
            self._recording = False
            self._chunks = []
            self._recorded_samples = 0
            self._auto_stop = False

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass  # closing a dying stream must never take the app down
