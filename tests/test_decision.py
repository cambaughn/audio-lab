"""Decision monotonicity — uncertainty can never raise privilege."""

import numpy as np
import pytest

from audio_lab.identity.decision import (
    REASON_PRIVATE_GRANTED,
    AccessTier,
    RecognitionDecision,
    decide,
)
from audio_lab.identity.matcher import GalleryIdentity, Matcher

RECOGNITION = 0.40
PRIVATE = 0.55
MARGIN = 0.10


def unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(192).astype(np.float32)
    return v / np.linalg.norm(v)


def decision_for(probe: np.ndarray, gallery: list[GalleryIdentity]) -> RecognitionDecision:
    match = Matcher(gallery).match(
        probe, threshold=RECOGNITION, margin=MARGIN, top_k=3
    )
    return decide(match, private_access_threshold=PRIVATE)


def gallery_entry(name: str, rows: list[np.ndarray]) -> GalleryIdentity:
    return GalleryIdentity(
        identity_id=name.lower(), display_name=name, embeddings=np.vstack(rows)
    )


def scaled_gallery(name: str, probe: np.ndarray, similarity: float) -> GalleryIdentity:
    """A gallery whose top-k mean against `probe` is exactly `similarity`."""
    other = unit(777)
    other -= np.dot(other, probe) * probe  # orthogonalize
    other /= np.linalg.norm(other)
    row = similarity * probe + np.sqrt(1 - similarity**2) * other
    return gallery_entry(name, [row, row, row])


CAM = unit(1)


class TestTiers:
    def test_high_similarity_is_private_verified(self):
        d = decision_for(CAM, [scaled_gallery("Cameron", CAM, 0.80)])
        assert d.tier is AccessTier.PRIVATE_VERIFIED
        assert d.display_name == "Cameron"
        assert d.reason == REASON_PRIVATE_GRANTED

    def test_between_thresholds_is_recognized_only(self):
        d = decision_for(CAM, [scaled_gallery("Cameron", CAM, 0.47)])
        assert d.tier is AccessTier.RECOGNIZED
        assert d.display_name == "Cameron"
        assert "BELOW PRIVATE THRESHOLD" in d.reason

    def test_below_recognition_is_unknown(self):
        d = decision_for(CAM, [scaled_gallery("Cameron", CAM, 0.30)])
        assert d.tier is AccessTier.UNKNOWN
        assert d.identity_id is None and d.display_name is None
        assert d.similarity is not None  # score still reported

    def test_no_evidence_is_unknown(self):
        d = decision_for(np.zeros(192, dtype=np.float32), [scaled_gallery("Cameron", CAM, 0.9)])
        assert d.tier is AccessTier.UNKNOWN

    def test_ambiguity_is_unknown_even_at_high_score(self):
        # two enrolled identities equally similar to the probe: similarity is
        # far above the private threshold, but the margin collapses -> UNKNOWN
        g = [scaled_gallery("Cameron", CAM, 0.9), scaled_gallery("Impostor", CAM, 0.9)]
        d = decision_for(CAM, g)
        assert d.tier is AccessTier.UNKNOWN
        assert d.similarity > PRIVATE  # high score...
        assert d.identity_id is None   # ...still no privilege


class TestMonotonicity:
    @pytest.mark.parametrize("similarity", np.linspace(0.05, 0.95, 19).tolist())
    def test_private_iff_at_or_above_threshold(self, similarity):
        d = decision_for(CAM, [scaled_gallery("Cameron", CAM, similarity)])
        if d.tier is AccessTier.PRIVATE_VERIFIED:
            assert d.similarity >= PRIVATE
        if similarity < PRIVATE - 0.02:  # tolerance for float construction
            assert d.tier is not AccessTier.PRIVATE_VERIFIED
        if similarity < RECOGNITION - 0.02:
            assert d.tier is AccessTier.UNKNOWN

    def test_unknown_never_carries_identity(self):
        for seed in range(20):
            d = decision_for(unit(seed + 50), [scaled_gallery("Cameron", CAM, 0.7)])
            if d.tier is AccessTier.UNKNOWN:
                assert d.identity_id is None and d.display_name is None
