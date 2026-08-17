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


class TestPlaybackNormalization:
    def test_quiet_clip_is_boosted_for_review(self):
        from audio_lab.audio.playback import REVIEW_PEAK, normalize_for_review, play_clip

        moderate = make_clip(tone(1.0, amplitude=0.3))
        out = normalize_for_review(moderate.samples)
        assert abs(float(np.max(np.abs(out))) - REVIEW_PEAK) < 1e-3
        assert moderate.samples.max() < 0.31  # original untouched
        played = []
        play_clip(moderate, player=lambda s, sr: played.append((s, sr)))
        assert played[0][1] == SAMPLE_RATE
        assert float(np.max(np.abs(played[0][0]))) > 0.6

    def test_gain_is_capped_for_very_quiet_clips(self):
        from audio_lab.audio.playback import MAX_REVIEW_GAIN_DB, normalize_for_review

        quiet = make_clip(tone(1.0, amplitude=0.03))  # typical laptop-mic peak
        out = normalize_for_review(quiet.samples)
        applied_db = 20 * np.log10(float(np.max(np.abs(out))) / quiet.peak)
        assert abs(applied_db - MAX_REVIEW_GAIN_DB) < 0.1  # capped, not 0.7 peak

    def test_silence_is_not_amplified(self):
        from audio_lab.audio.playback import normalize_for_review

        out = normalize_for_review(np.zeros(1000, dtype=np.float32))
        assert float(np.max(np.abs(out))) == 0.0
