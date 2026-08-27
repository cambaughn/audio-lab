"""Identity-layer record types.

Names are deliberately modality-neutral (IdentityEvidence, not
VoiceEvidence): today the evidence comes from voice, and nothing else is
built — but nothing here would have to be renamed for a future modality.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

ENROLLMENT_VERSION = 1  # bump when the enrollment procedure changes materially


@dataclass(frozen=True)
class IdentityRecord:
    identity_id: str
    display_name: str
    created_at: datetime
    enrollment_version: int
    sample_count: int
    model_id: str | None   # None until the first sample is stored
    dim: int | None        # None until the first sample is stored


@dataclass(frozen=True, eq=False)  # eq=False: ndarray members don't compare
class EmbeddingSample:
    sample_id: str
    identity_id: str
    embedding: np.ndarray  # float32, 1-D, dim elements
    dim: int
    dtype: str
    model_id: str
    duration_s: float      # length of the utterance that produced it
    created_at: datetime


@dataclass(frozen=True, eq=False)
class IdentityEvidence:
    """What matching consumes for one utterance: an embedding plus the
    metadata needed to judge and store it. embedding is None when the
    model could not produce one (evidence of nothing — routes to UNKNOWN,
    never to a guess)."""

    embedding: np.ndarray | None
    model_id: str
    duration_s: float
