"""Matcher port sanity: threshold, margin, top-k, gallery building."""

import numpy as np

from audio_lab.identity.matcher import (
    REASON_AMBIGUOUS,
    REASON_BELOW_THRESHOLD,
    REASON_MATCH,
    REASON_NO_EMBEDDING,
    REASON_NO_IDENTITIES,
    GalleryIdentity,
    Matcher,
    build_gallery,
    top_k_mean,
)
from audio_lab.identity.store import IdentityStore

MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def unit(seed: int, dim: int = 192) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def gallery_for(base: np.ndarray, name: str, n: int = 6, jitter: float = 0.02):
    # jitter scales per-component: noise norm ~= jitter * sqrt(192) ~= 0.28,
    # giving same-voice cosines ~0.96 — realistic for a genuine speaker
    rng = np.random.default_rng(hash(name) % 2**32)
    rows = []
    for _ in range(n):
        v = base + jitter * rng.standard_normal(base.size).astype(np.float32)
        rows.append(v / np.linalg.norm(v))
    return GalleryIdentity(
        identity_id=name.lower(), display_name=name, embeddings=np.vstack(rows)
    )


CAM = unit(1)
RILEY = unit(2)


class TestMatcher:
    def test_empty_gallery_unknown(self):
        result = Matcher([]).match(CAM, threshold=0.4, margin=0.1, top_k=3)
        assert not result.is_known and result.reason == REASON_NO_IDENTITIES

    def test_zero_embedding_unknown(self):
        matcher = Matcher([gallery_for(CAM, "Cameron")])
        result = matcher.match(np.zeros(192, dtype=np.float32), threshold=0.4, margin=0.1, top_k=3)
        assert not result.is_known and result.reason == REASON_NO_EMBEDDING

    def test_matches_own_voice(self):
        matcher = Matcher([gallery_for(CAM, "Cameron"), gallery_for(RILEY, "Riley")])
        result = matcher.match(CAM, threshold=0.4, margin=0.1, top_k=3)
        assert result.is_known and result.display_name == "Cameron"
        assert result.reason == REASON_MATCH
        assert result.similarity > 0.8
        assert result.second_best is not None and result.second_best.score < 0.3

    def test_stranger_below_threshold(self):
        matcher = Matcher([gallery_for(CAM, "Cameron"), gallery_for(RILEY, "Riley")])
        result = matcher.match(unit(99), threshold=0.4, margin=0.1, top_k=3)
        assert not result.is_known and result.reason == REASON_BELOW_THRESHOLD
        assert result.similarity is not None  # reported even on unknown

    def test_ambiguous_margin_is_unknown(self):
        # two identities built from the SAME base voice — scores nearly tie
        matcher = Matcher([gallery_for(CAM, "Cameron"), gallery_for(CAM, "Impostor")])
        result = matcher.match(CAM, threshold=0.4, margin=0.1, top_k=3)
        assert not result.is_known and result.reason == REASON_AMBIGUOUS

    def test_top_k_mean(self):
        sims = np.array([0.9, 0.1, 0.8, 0.2])
        assert abs(top_k_mean(sims, 2) - 0.85) < 1e-6
        assert abs(top_k_mean(sims, 10) - float(sims.mean())) < 1e-6
        assert top_k_mean(np.array([]), 3) == 0.0


class TestBuildGallery:
    def test_skips_other_models_and_empties(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as store:
            good = store.create_identity("Cameron")
            for i in range(3):
                store.add_embedding_sample(good.identity_id, unit(i), MODEL, 3.0)
            other = store.create_identity("OldModel")
            store.add_embedding_sample(other.identity_id, unit(9), "legacy-model", 3.0)
            store.create_identity("Empty")
            gallery, warnings = build_gallery(store, MODEL)
        assert [g.display_name for g in gallery] == ["Cameron"]
        assert len(warnings) == 2
