"""Calibration: distributions from a synthetic two-speaker store."""

import numpy as np

from audio_lab.identity.calibration import (
    score_distributions,
    suggest_thresholds,
    summarize,
)
from audio_lab.identity.store import IdentityStore

MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def voice(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(192).astype(np.float32)
    return v / np.linalg.norm(v)


def enroll(store, name, base, n=6, jitter=0.15, seed=0):
    rng = np.random.default_rng(seed)
    rec = store.create_identity(name)
    for _ in range(n):
        v = base + jitter * rng.standard_normal(192).astype(np.float32)
        store.add_embedding_sample(rec.identity_id, v.astype(np.float32), MODEL, 3.0)
    return rec


class TestCalibration:
    def test_two_speaker_distributions_separate(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            enroll(store, "Cameron", voice(1), seed=10)
            enroll(store, "Riley", voice(2), seed=20)
            dist = score_distributions(store, MODEL)
        assert len(dist.genuine) == 12  # 2 speakers x 6 leave-one-out
        assert len(dist.impostor) == 12
        assert min(dist.genuine) > max(dist.impostor)  # synthetic voices separate

        suggestion = suggest_thresholds(dist)
        assert suggestion is not None
        assert max(dist.impostor) < suggestion.recognition < min(dist.genuine)
        assert suggestion.private_access >= suggestion.recognition + 0.10 - 1e-9

    def test_single_speaker_suggests_from_genuine_only(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            enroll(store, "Cameron", voice(1))
            dist = score_distributions(store, MODEL)
        assert len(dist.genuine) == 6 and dist.impostor == ()
        suggestion = suggest_thresholds(dist)
        assert suggestion is not None
        assert "1 SPEAKER" in suggestion.basis
        assert suggestion.recognition < min(dist.genuine)
        assert suggestion.recognition < suggestion.private_access <= 0.95
        # every genuine sample would still clear the private threshold
        assert suggestion.private_access <= min(dist.genuine)

    def test_empty_store_suggests_nothing(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            dist = score_distributions(store, MODEL)
        assert suggest_thresholds(dist) is None

    def test_summarize_handles_empty(self):
        assert summarize(()) == "none"
        assert "median" in summarize((0.5, 0.6))
