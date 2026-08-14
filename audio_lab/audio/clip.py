"""AudioClip and utterance quality gates — pure, no Qt, no sounddevice.

An AudioClip is an immutable in-memory utterance: float32 mono samples at
16 kHz plus the quality metrics computed once at creation. Raw audio never
touches disk anywhere in Audio Lab; clips live only for the duration of a
turn (or an enrollment review).

Gates are ordered and return exactly one reason code — the Identity Lab
enrollment-feedback philosophy: understandable over sophisticated. No VAD,
no SNR estimation (declined rabbit-holes, see docs/learnings.md).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import numpy as np

SAMPLE_RATE = 16_000

MIN_UTTERANCE_S = 0.6
MAX_UTTERANCE_S = 30.0
MIN_RMS_DBFS = -45.0
MAX_CLIPPED_FRACTION = 0.01
_CLIP_THRESHOLD = 0.99  # |sample| at or above this counts as clipped


@dataclass(frozen=True, eq=False)
class AudioClip:
    samples: np.ndarray  # float32, mono, SAMPLE_RATE
    sample_rate: int
    duration_s: float
    peak: float
    rms_dbfs: float
    clipped_fraction: float
    captured_at: datetime


class ClipVerdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    SILENT_INPUT = "SILENT_INPUT"
    TOO_SHORT = "TOO_SHORT"
    TOO_QUIET = "TOO_QUIET"
    CLIPPED = "CLIPPED"


def make_clip(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    captured_at: datetime | None = None,
) -> AudioClip:
    """Build a clip, computing its metrics once. Accepts any float array."""
    samples = np.asarray(samples, dtype=np.float32).ravel()
    duration_s = samples.size / sample_rate if sample_rate else 0.0
    if samples.size:
        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        clipped = float(np.count_nonzero(np.abs(samples) >= _CLIP_THRESHOLD) / samples.size)
    else:
        peak, rms, clipped = 0.0, 0.0, 0.0
    rms_dbfs = 20.0 * float(np.log10(rms)) if rms > 0.0 else float("-inf")
    return AudioClip(
        samples=samples,
        sample_rate=sample_rate,
        duration_s=duration_s,
        peak=peak,
        rms_dbfs=rms_dbfs,
        clipped_fraction=clipped,
        captured_at=captured_at or datetime.now(timezone.utc),
    )


def gate_clip(
    clip: AudioClip,
    *,
    min_duration_s: float = MIN_UTTERANCE_S,
    min_rms_dbfs: float = MIN_RMS_DBFS,
    max_clipped_fraction: float = MAX_CLIPPED_FRACTION,
) -> tuple[ClipVerdict, str]:
    """Ordered quality gates; exactly one reason code per rejection.

    SILENT_INPUT is checked first because an all-zero clip is a symptom of
    denied microphone permission, not of a quiet speaker — the two need
    different user guidance.
    """
    if clip.samples.size == 0 or clip.peak == 0.0:
        return ClipVerdict.SILENT_INPUT, "SILENT INPUT — CHECK MIC PERMISSION"
    if clip.duration_s < min_duration_s:
        return (
            ClipVerdict.TOO_SHORT,
            f"TOO SHORT ({clip.duration_s:.1f}s < {min_duration_s:.1f}s)",
        )
    if clip.rms_dbfs < min_rms_dbfs:
        return (
            ClipVerdict.TOO_QUIET,
            f"TOO QUIET ({clip.rms_dbfs:.0f} dBFS < {min_rms_dbfs:.0f} dBFS)",
        )
    if clip.clipped_fraction > max_clipped_fraction:
        return (
            ClipVerdict.CLIPPED,
            f"CLIPPED ({clip.clipped_fraction:.1%} of samples)",
        )
    return ClipVerdict.ACCEPTED, "ACCEPTED"
