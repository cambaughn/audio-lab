"""AudioClip metrics and ordered quality gates."""

import numpy as np

from audio_lab.audio.clip import (
    MIN_RMS_DBFS,
    MIN_UTTERANCE_S,
    SAMPLE_RATE,
    ClipVerdict,
    gate_clip,
    make_clip,
)


def tone(seconds: float, amplitude: float = 0.5, hz: float = 440.0) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


class TestMakeClip:
    def test_metrics_of_known_tone(self):
        clip = make_clip(tone(2.0, amplitude=0.5))
        assert clip.duration_s == 2.0
        assert 0.49 < clip.peak <= 0.5
        # sine RMS = A/sqrt(2) -> 20*log10(0.3536) ~ -9.03 dBFS
        assert -9.5 < clip.rms_dbfs < -8.5
        assert clip.clipped_fraction == 0.0
        assert clip.sample_rate == SAMPLE_RATE

    def test_empty_clip_is_silent(self):
        clip = make_clip(np.zeros(0))
        assert clip.duration_s == 0.0
        assert clip.peak == 0.0
        assert clip.rms_dbfs == float("-inf")

    def test_flattens_2d_input_and_casts(self):
        clip = make_clip(np.ones((100, 1), dtype=np.float64) * 0.25)
        assert clip.samples.ndim == 1
        assert clip.samples.dtype == np.float32
        assert clip.samples.size == 100


class TestGates:
    def test_silent_input_first(self):
        # all-zero AND too short: silence must win — it means mic permission
        verdict, reason = gate_clip(make_clip(np.zeros(100)))
        assert verdict is ClipVerdict.SILENT_INPUT
        assert "PERMISSION" in reason

    def test_too_short(self):
        verdict, reason = gate_clip(make_clip(tone(MIN_UTTERANCE_S / 2)))
        assert verdict is ClipVerdict.TOO_SHORT
        assert "TOO SHORT" in reason

    def test_too_quiet(self):
        quiet = tone(1.0, amplitude=10 ** (MIN_RMS_DBFS / 20) / 2)
        verdict, reason = gate_clip(make_clip(quiet))
        assert verdict is ClipVerdict.TOO_QUIET

    def test_clipped(self):
        loud = tone(1.0, amplitude=0.5)
        loud[: loud.size // 10] = 1.0  # 10% clipped
        verdict, reason = gate_clip(make_clip(loud))
        assert verdict is ClipVerdict.CLIPPED

    def test_accepted(self):
        verdict, reason = gate_clip(make_clip(tone(1.0, amplitude=0.5)))
        assert verdict is ClipVerdict.ACCEPTED
        assert reason == "ACCEPTED"

    def test_gate_order_short_before_quiet(self):
        # short AND quiet -> TOO_SHORT (ordering is part of the contract)
        quiet_short = tone(0.2, amplitude=1e-4)
        verdict, _ = gate_clip(make_clip(quiet_short))
        assert verdict is ClipVerdict.TOO_SHORT


class TestPlayback:
    def test_play_clip_passes_samples_unmodified(self):
        from audio_lab.audio.playback import play_clip

        clip = make_clip(tone(1.0, amplitude=0.03))
        played = []
        play_clip(clip, player=lambda s, sr: played.append((s, sr)))
        assert played[0][1] == SAMPLE_RATE
        assert np.array_equal(played[0][0], clip.samples)  # no gain, no processing


class TestSystemInputVolume:
    def test_reads_osascript_output(self):
        from audio_lab.audio.system_input import read_input_volume

        class R:
            stdout = "14\n"

        assert read_input_volume(runner=lambda *a, **k: R()) == 14

    def test_unavailable_gives_none(self):
        from audio_lab.audio.system_input import read_input_volume

        def boom(*a, **k):
            raise OSError("no osascript")

        assert read_input_volume(runner=boom) is None
