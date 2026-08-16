"""Clip playback for review — straight from memory, no files.

Playback is peak-normalized to a comfortable review level: push-to-talk
clips from a laptop mic commonly peak at only a few percent of full scale
(learnings.md Observation 005), which is inaudible through laptop speakers.
The stored/analyzed samples are never modified — only the copy sent to the
output device.
"""

import numpy as np

from audio_lab.audio.clip import AudioClip

REVIEW_PEAK = 0.7  # target peak on playback; leaves headroom, no clipping
_MIN_PEAK_TO_NORMALIZE = 1e-4  # don't blow up genuine silence


def normalize_for_review(samples: np.ndarray, target_peak: float = REVIEW_PEAK) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < _MIN_PEAK_TO_NORMALIZE:
        return samples
    return (samples * (target_peak / peak)).astype(np.float32)


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
