"""VoiceEnrollmentSession gates and all-or-nothing persistence."""

import numpy as np
import pytest

from audio_lab.audio.clip import make_clip
from audio_lab.identity.enrollment import (
    OUTLIER_CHECK_AFTER,
    PROMPTS,
    TARGET_SAMPLES,
    EnrollFeedback,
    VoiceEnrollmentSession,
    save_enrollment,
)
from audio_lab.identity.errors import ModelMismatchError
from audio_lab.identity.store import IdentityStore
from audio_lab.identity.types import IdentityEvidence

MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def clip(seconds: float = 3.0):
    t = np.arange(int(seconds * 16000)) / 16000
    return make_clip((0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32))


def evidence(base: np.ndarray, jitter: float = 0.05, seed: int = 0):
    rng = np.random.default_rng(seed)
    v = base + jitter * rng.standard_normal(base.size).astype(np.float32)
    return IdentityEvidence(embedding=v.astype(np.float32), model_id=MODEL, duration_s=3.0)


VOICE_A = np.random.default_rng(1).standard_normal(192).astype(np.float32)
VOICE_B = np.random.default_rng(2).standard_normal(192).astype(np.float32)


def fill_session(session: VoiceEnrollmentSession, n: int, base=VOICE_A):
    for i in range(n):
        assert session.accept(clip(), evidence(base, seed=i)) is EnrollFeedback.ACCEPTED


class TestGates:
    def test_progresses_through_all_prompts(self):
        session = VoiceEnrollmentSession()
        seen = []
        for i in range(TARGET_SAMPLES):
            seen.append(session.current_prompt)
            fill_session(session, 0)  # no-op, keeps helper honest
            assert session.accept(clip(), evidence(VOICE_A, seed=i)) is EnrollFeedback.ACCEPTED
        assert seen == PROMPTS
        assert session.complete and session.current_prompt is None

    def test_too_short_rejected(self):
        session = VoiceEnrollmentSession()
        assert session.evaluate(clip(1.0), evidence(VOICE_A)) is EnrollFeedback.TOO_SHORT
        assert session.accepted_total == 0

    def test_missing_embedding_rejected(self):
        session = VoiceEnrollmentSession()
        bad = IdentityEvidence(embedding=None, model_id=MODEL, duration_s=3.0)
        assert session.evaluate(clip(), bad) is EnrollFeedback.NO_EMBEDDING

    def test_person_swap_rejected(self):
        session = VoiceEnrollmentSession()
        fill_session(session, OUTLIER_CHECK_AFTER)
        # a different random voice is near-orthogonal in 192-d
        assert session.accept(clip(), evidence(VOICE_B)) is EnrollFeedback.INCONSISTENT
        assert session.accepted_total == OUTLIER_CHECK_AFTER

    def test_same_voice_passes_consistency(self):
        session = VoiceEnrollmentSession()
        fill_session(session, OUTLIER_CHECK_AFTER)
        assert session.accept(clip(), evidence(VOICE_A, seed=99)) is EnrollFeedback.ACCEPTED

    def test_complete_session_refuses_more(self):
        session = VoiceEnrollmentSession()
        fill_session(session, TARGET_SAMPLES)
        assert session.evaluate(clip(), evidence(VOICE_A)) is EnrollFeedback.COMPLETE

    def test_evaluate_does_not_mutate(self):
        session = VoiceEnrollmentSession()
        assert session.evaluate(clip(), evidence(VOICE_A)) is EnrollFeedback.ACCEPTED
        assert session.accepted_total == 0


class TestSave:
    def test_incomplete_session_refused(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            session = VoiceEnrollmentSession()
            fill_session(session, 3)
            with pytest.raises(ValueError):
                save_enrollment(store, "Cameron", session, MODEL)
            assert store.list_identities() == []

    def test_complete_session_saves_all(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            session = VoiceEnrollmentSession()
            fill_session(session, TARGET_SAMPLES)
            record = save_enrollment(store, "Cameron", session, MODEL)
            assert record.sample_count == TARGET_SAMPLES
            assert record.model_id == MODEL
            samples = store.get_embedding_samples(record.identity_id)
            assert all(s.duration_s == 3.0 for s in samples)

    def test_failed_save_leaves_nothing(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            session = VoiceEnrollmentSession()
            fill_session(session, TARGET_SAMPLES)
            # sabotage: pre-existing incompatible sample space for this name is
            # impossible (new identity), so sabotage via wrong-dim embedding
            session._samples[3] = (np.zeros(64, dtype=np.float32), 3.0)
            with pytest.raises(ModelMismatchError):
                save_enrollment(store, "Cameron", session, MODEL)
            assert store.list_identities() == []  # all-or-nothing held
