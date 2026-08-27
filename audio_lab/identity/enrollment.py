"""Voice enrollment session — guided multi-utterance capture with simple,
deterministic quality gates.

Identity Lab philosophy: a working, understandable flow over a
sophisticated one. Six utterances (four prompted for phonetic variety,
two free speech), one sample each. Prompts guide variety but are NOT
verified against the audio content.

The recorder's clip gates (silence / too-short / too-quiet / clipped)
run before anything reaches this session; enrollment adds only:

  1. long enough for a stable voiceprint  (TOO_SHORT, >= 2.0 s)
  2. the model produced an embedding      (NO_EMBEDDING)
  3. consistent with the session          (INCONSISTENT; cosine vs mean of
     accepted — guards against a person swap mid-enrollment)

evaluate() is a pure check (the dialog uses it to offer REVIEW/ACCEPT);
accept() re-checks and commits to the session. Nothing touches the
database until save_enrollment() — cancel is simply "never call save",
which guarantees no partial identities.
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np

from audio_lab.audio.clip import AudioClip
from audio_lab.identity.matcher import normalize
from audio_lab.identity.store import IdentityStore
from audio_lab.identity.types import (
    ENROLLMENT_VERSION,
    IdentityEvidence,
    IdentityRecord,
)

# -- tuning constants (first pass: conservative and simple) --
MIN_ENROLL_DURATION_S = 2.0
OUTLIER_MIN_COSINE = 0.35   # vs mean of accepted samples (ECAPA same-speaker
OUTLIER_CHECK_AFTER = 2     # utterances typically score 0.4+; impostors < 0.3)


@dataclass(frozen=True)
class EnrollmentPrompt:
    kind: str  # "READ" | "FREE"
    text: str


PROMPTS: list[EnrollmentPrompt] = [
    EnrollmentPrompt("READ", "The quick onyx goblin jumps over the lazy dwarf."),
    EnrollmentPrompt("READ", "Count slowly from one to eight at your normal pace."),
    EnrollmentPrompt("READ", "It was a bright cold day in April, and the clocks were striking thirteen."),
    EnrollmentPrompt("READ", "My voice is how this machine knows who is speaking."),
    EnrollmentPrompt("FREE", "In your own words: what did you do this morning?"),
    EnrollmentPrompt("FREE", "Say anything you like for a few seconds."),
]
TARGET_SAMPLES = len(PROMPTS)  # 6


class EnrollFeedback(str, Enum):
    ACCEPTED = "SAMPLE ACCEPTED"
    TOO_SHORT = "TOO SHORT — SPEAK FOR AT LEAST 2 SECONDS"
    NO_EMBEDDING = "PROCESSING FAILED — TRY AGAIN"
    INCONSISTENT = "DOESN'T MATCH EARLIER SAMPLES — SAME PERSON ONLY"
    COMPLETE = "ALL SAMPLES CAPTURED"


class VoiceEnrollmentSession:
    """Collects quality-gated voice embeddings across guided prompts.

    Pure logic: it never touches the microphone, the UI, or the database.
    """

    def __init__(self) -> None:
        self._samples: list[tuple[np.ndarray, float]] = []  # (embedding, duration)

    # -- progress introspection --

    @property
    def accepted_total(self) -> int:
        return len(self._samples)

    @property
    def complete(self) -> bool:
        return self.accepted_total >= TARGET_SAMPLES

    @property
    def current_prompt(self) -> EnrollmentPrompt | None:
        if self.complete:
            return None
        return PROMPTS[self.accepted_total]

    def accepted_samples(self) -> list[tuple[np.ndarray, float]]:
        return list(self._samples)

    # -- gates --

    def evaluate(self, clip: AudioClip, evidence: IdentityEvidence) -> EnrollFeedback:
        """Pure check — does this utterance pass the gates right now?"""
        if self.complete:
            return EnrollFeedback.COMPLETE
        if clip.duration_s < MIN_ENROLL_DURATION_S:
            return EnrollFeedback.TOO_SHORT
        if evidence.embedding is None:
            return EnrollFeedback.NO_EMBEDDING
        probe = normalize(evidence.embedding)
        if probe is None:
            return EnrollFeedback.NO_EMBEDDING
        if len(self._samples) >= OUTLIER_CHECK_AFTER:
            mean = normalize(np.mean([normalize(e) for e, _ in self._samples], axis=0))
            if mean is not None and float(np.dot(probe, mean)) < OUTLIER_MIN_COSINE:
                return EnrollFeedback.INCONSISTENT
        return EnrollFeedback.ACCEPTED

    def accept(self, clip: AudioClip, evidence: IdentityEvidence) -> EnrollFeedback:
        """Re-check and commit the utterance to the session."""
        feedback = self.evaluate(clip, evidence)
        if feedback is EnrollFeedback.ACCEPTED:
            self._samples.append(
                (np.asarray(evidence.embedding, dtype=np.float32), clip.duration_s)
            )
        return feedback


def save_enrollment(
    store: IdentityStore,
    display_name: str,
    session: VoiceEnrollmentSession,
    model_id: str,
) -> IdentityRecord:
    """Persist a completed session as a new identity (all-or-nothing).

    If any sample write fails, the partially created identity is removed
    before the error propagates — the store never retains a half-enrolled
    person.
    """
    if not session.complete:
        raise ValueError(
            f"enrollment incomplete: {session.accepted_total} accepted, "
            f"{TARGET_SAMPLES} required"
        )
    record = store.create_identity(display_name, enrollment_version=ENROLLMENT_VERSION)
    try:
        for embedding, duration_s in session.accepted_samples():
            store.add_embedding_sample(record.identity_id, embedding, model_id, duration_s)
    except Exception:
        store.delete_identity(record.identity_id)
        raise
    return store.get_identity(record.identity_id)
