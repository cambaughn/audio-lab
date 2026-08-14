"""AudioRecorder state machine, driven entirely through a fake stream.

No microphone: the fake factory captures the recorder's callback so tests
push blocks in directly, and _tick() is called manually in place of the
QTimer (Identity Lab style — synchronous, ordered assertions on signals
collected into lists).
"""

import numpy as np
import pytest

from audio_lab.audio.capture import (
    PERMISSION_MESSAGE,
    AudioRecorder,
    RecorderState,
)
from audio_lab.audio.clip import SAMPLE_RATE


class FakeStream:
    def __init__(self) -> None:
        self.stopped = False
        self.closed = False

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakeStreamFactory:
    """Records open attempts; can fail the first N of them."""

    def __init__(self, fail_first: int = 0) -> None:
        self.fail_first = fail_first
        self.attempts = 0
        self.callback = None
        self.streams: list[FakeStream] = []

    def __call__(self, device, sample_rate, blocksize, callback):
        self.attempts += 1
        if self.attempts <= self.fail_first:
            raise RuntimeError("Internal PortAudio error [PaErrorCode -9986]")
        self.callback = callback
        stream = FakeStream()
        self.streams.append(stream)
        return stream


@pytest.fixture()
def rig():
    factory = FakeStreamFactory()
    recorder = AudioRecorder(stream_factory=factory)
    states: list[str] = []
    clips: list = []
    rejections: list[str] = []
    errors: list[str] = []
    recorder.state_changed.connect(states.append)
    recorder.clip_ready.connect(clips.append)
    recorder.clip_rejected.connect(rejections.append)
    recorder.error.connect(errors.append)
    return recorder, factory, states, clips, rejections, errors


def speech_block(n: int = 1024, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(n) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 300 * t)).astype(np.float32)


def push_seconds(factory: FakeStreamFactory, seconds: float, block=None) -> None:
    n_blocks = int(seconds * SAMPLE_RATE / 1024) + 1
    for _ in range(n_blocks):
        factory.callback(
            (speech_block() if block is None else block).reshape(-1, 1), 1024, None, None
        )


class TestArming:
    def test_arm_reaches_armed(self, rig):
        recorder, factory, states, *_ = rig
        recorder.arm("Fake Mic")
        assert recorder.state is RecorderState.ARMED
        assert states == [RecorderState.ARMED.value]
        assert factory.attempts == 1

    def test_first_start_failure_is_retried(self):
        factory = FakeStreamFactory(fail_first=1)
        recorder = AudioRecorder(stream_factory=factory)
        recorder.arm(None)
        assert recorder.state is RecorderState.ARMED
        assert factory.attempts == 2  # failed once, retried, succeeded

    def test_persistent_failure_is_error(self):
        factory = FakeStreamFactory(fail_first=99)
        recorder = AudioRecorder(stream_factory=factory)
        errors: list[str] = []
        recorder.error.connect(errors.append)
        recorder.arm(None)
        assert recorder.state is RecorderState.ERROR
        assert factory.attempts == 2  # one retry, then give up
        assert "MIC ERROR" in errors[0]

    def test_disarm_closes_stream(self, rig):
        recorder, factory, states, *_ = rig
        recorder.arm(None)
        recorder.disarm()
        assert recorder.state is RecorderState.IDLE
        assert factory.streams[0].stopped and factory.streams[0].closed


class TestPushToTalk:
    def test_full_utterance_emits_clip(self, rig):
        recorder, factory, states, clips, rejections, _ = rig
        recorder.arm(None)
        recorder.begin_utterance()
        assert recorder.state is RecorderState.RECORDING
        push_seconds(factory, 1.0)
        recorder.end_utterance()
        assert recorder.state is RecorderState.ARMED
        assert len(clips) == 1 and not rejections
        assert clips[0].duration_s >= 1.0
        assert clips[0].sample_rate == SAMPLE_RATE

    def test_too_short_press_is_rejected_with_reason(self, rig):
        recorder, factory, _, clips, rejections, _ = rig
        recorder.arm(None)
        recorder.begin_utterance()
        push_seconds(factory, 0.2)
        recorder.end_utterance()
        assert not clips
        assert len(rejections) == 1 and "TOO SHORT" in rejections[0]

    def test_armed_metering_discards_samples(self, rig):
        recorder, factory, _, clips, rejections, _ = rig
        recorder.arm(None)
        push_seconds(factory, 2.0)  # metering only — not recording
        recorder.begin_utterance()
        push_seconds(factory, 1.0)
        recorder.end_utterance()
        # the clip contains only what was pushed while RECORDING
        assert clips[0].duration_s < 1.5

    def test_begin_ignored_when_not_armed(self, rig):
        recorder, *_ = rig
        recorder.begin_utterance()  # never armed
        assert recorder.state is RecorderState.IDLE

    def test_auto_stop_at_max_duration(self, rig):
        recorder, factory, _, clips, _, _ = rig
        recorder._max_samples = SAMPLE_RATE  # shrink cap to 1 s for the test
        recorder.arm(None)
        recorder.begin_utterance()
        push_seconds(factory, 3.0)  # exceeds the shrunk cap
        recorder._tick()
        assert recorder.state is RecorderState.ARMED  # auto-stopped
        assert len(clips) == 1
        assert clips[0].duration_s <= 1.1


class TestLockout:
    def test_disable_mid_recording_drops_buffer(self, rig):
        recorder, factory, _, clips, rejections, _ = rig
        recorder.arm(None)
        recorder.begin_utterance()
        push_seconds(factory, 1.0)
        recorder.set_enabled(False)  # TTS started speaking
        assert recorder.state is RecorderState.DISABLED
        recorder.end_utterance()  # release arrives late — must be a no-op
        assert not clips and not rejections
        recorder.set_enabled(True)
        assert recorder.state is RecorderState.ARMED

    def test_begin_ignored_while_disabled(self, rig):
        recorder, factory, *_ = rig
        recorder.arm(None)
        recorder.set_enabled(False)
        recorder.begin_utterance()
        assert recorder.state is RecorderState.DISABLED


class TestSilenceDetection:
    def test_all_zero_input_reports_permission(self, rig):
        recorder, factory, _, _, _, errors = rig
        recorder.arm(None)
        push_seconds(factory, 1.5, block=np.zeros(1024, dtype=np.float32))
        recorder._tick()
        assert recorder.state is RecorderState.ERROR
        assert errors == [PERMISSION_MESSAGE]
        assert factory.streams[0].closed

    def test_live_signal_passes_silence_check(self, rig):
        recorder, factory, _, _, _, errors = rig
        recorder.arm(None)
        push_seconds(factory, 1.5)
        recorder._tick()
        assert recorder.state is RecorderState.ARMED
        assert not errors


class TestMeterAndWaveform:
    def test_tick_emits_level_and_waveform(self, rig):
        recorder, factory, *_ = rig
        levels: list[tuple] = []
        waves: list[np.ndarray] = []
        recorder.level_changed.connect(lambda p, r: levels.append((p, r)))
        recorder.waveform_block.connect(waves.append)
        recorder.arm(None)
        push_seconds(factory, 0.5)
        recorder._tick()
        assert levels and levels[0][0] > 0.2  # peak of 0.3 sine
        assert waves and waves[0].size > 0
        # ~200 points per second of audio
        total_points = sum(w.size for w in waves)
        assert 80 <= total_points <= 130  # 0.5 s ≈ 100 points
