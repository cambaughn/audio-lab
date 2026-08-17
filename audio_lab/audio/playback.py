"""Clip playback for review — straight from memory, no files.

Playback is gain-boosted for review: push-to-talk clips from a laptop mic
commonly peak at only a few percent of full scale (learnings.md
Observation 005), which is inaudible through laptop speakers. The boost is
capped at +12 dB because full peak-normalization (+27 dB on a typical clip)
also lifts the microphone's own noise floor — discrete 120/217 Hz hum —
into clear audibility (Observation 006). The stored/analyzed samples are
never modified — only the copy sent to the output device.
"""

import numpy as np

from audio_lab.audio.clip import AudioClip

REVIEW_PEAK = 0.7  # target peak on playback; leaves headroom, no clipping
MAX_REVIEW_GAIN_DB = 12.0  # cap: uncapped +27 dB lifted the mic's own noise
_MIN_PEAK_TO_NORMALIZE = 1e-4  # floor (120/217 Hz hum) into audibility —
_MAX_GAIN = 10 ** (MAX_REVIEW_GAIN_DB / 20)  # Observation 006


def normalize_for_review(samples: np.ndarray, target_peak: float = REVIEW_PEAK) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < _MIN_PEAK_TO_NORMALIZE:
        return samples
    gain = min(target_peak / peak, _MAX_GAIN)
    return (samples * gain).astype(np.float32)


def play_clip(audio_clip: AudioClip, player=None) -> None:
    """Play a clip (non-blocking) at review level. Injectable player for tests."""
    if player is None:
        import sounddevice as sd

        player = sd.play
    player(normalize_for_review(audio_clip.samples), audio_clip.sample_rate)


def stop_playback(stopper=None) -> None:
    if stopper is None:
        import sounddevice as sd

        stopper = sd.stop
    stopper()
