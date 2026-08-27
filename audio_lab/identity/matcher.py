"""Identity matching — cosine similarity against the enrolled gallery.

Pure computation, no Qt, no audio. Ported from Identity Lab v0.1.0. The gallery is an in-memory snapshot of
the store (rebuild after enrollment changes). Scoring: per identity, the
mean of the top-k best-matching enrollment samples; a match requires the
best identity to clear the threshold AND (when other identities exist)
beat the runner-up by a margin. Otherwise the result is Unknown — the
matcher never forces a guess, and similarity is a cosine score, not a
probability.
"""

from dataclasses import dataclass

import numpy as np

from audio_lab.identity.errors import IdentityStoreError, MalformedEmbeddingError
from audio_lab.identity.store import IdentityStore

# Rejection/acceptance reasons (stable strings, shown in debug UI)
REASON_MATCH = "MATCH"
REASON_NO_IDENTITIES = "NO IDENTITIES ENROLLED"
REASON_NO_EMBEDDING = "NO USABLE EMBEDDING"
REASON_BELOW_THRESHOLD = "BELOW THRESHOLD"
REASON_AMBIGUOUS = "AMBIGUOUS — MARGIN TOO SMALL"


def normalize(embedding: np.ndarray) -> np.ndarray | None:
    """Unit-L2-normalize a vector; None for zero/non-finite input."""
    v = np.asarray(embedding, dtype=np.float32).ravel()
    if v.size == 0 or not np.all(np.isfinite(v)):
        return None
    norm = float(np.linalg.norm(v))
    if norm <= 0.0:
        return None
    return v / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors (normalized internally)."""
    an, bn = normalize(a), normalize(b)
    if an is None or bn is None:
        return 0.0
    return float(np.dot(an, bn))


def top_k_mean(similarities: np.ndarray, k: int) -> float:
    """Mean of the k highest values (all values if fewer than k)."""
    if similarities.size == 0:
        return 0.0
    k = max(1, min(int(k), similarities.size))
    top = np.sort(similarities)[-k:]
    return float(np.mean(top))


@dataclass(frozen=True)
class GalleryIdentity:
    identity_id: str
    display_name: str
    embeddings: np.ndarray  # (N, D), rows unit-normalized


@dataclass(frozen=True)
class MatchCandidate:
    identity_id: str
    display_name: str
    score: float


@dataclass(frozen=True)
class MatchResult:
    is_known: bool
    identity_id: str | None
    display_name: str | None
    similarity: float | None            # best score, reported even on Unknown
    best: MatchCandidate | None
    second_best: MatchCandidate | None
    reason: str


_UNKNOWN_EMPTY = MatchResult(
    is_known=False, identity_id=None, display_name=None, similarity=None,
    best=None, second_best=None, reason=REASON_NO_IDENTITIES,
)
_UNKNOWN_NO_EMBEDDING = MatchResult(
    is_known=False, identity_id=None, display_name=None, similarity=None,
    best=None, second_best=None, reason=REASON_NO_EMBEDDING,
)


def build_gallery(
    store: IdentityStore, model_id: str
) -> tuple[list[GalleryIdentity], list[str]]:
    """Snapshot the store into a matchable gallery.

    Resilient by design: identities that are empty, from a different model,
    or contain malformed samples are skipped with a human-readable warning
    instead of poisoning recognition for everyone else.
    """
    gallery: list[GalleryIdentity] = []
    warnings: list[str] = []
    for record in store.list_identities():
        if record.sample_count == 0:
            warnings.append(f"{record.display_name}: no samples — skipped")
            continue
        if record.model_id != model_id:
            warnings.append(
                f"{record.display_name}: enrolled with model "
                f"{record.model_id!r}, current is {model_id!r} — skipped"
            )
            continue
        try:
            samples = store.get_embedding_samples(record.identity_id)
        except MalformedEmbeddingError as exc:
            warnings.append(f"{record.display_name}: corrupted samples — {exc}")
            continue
        except IdentityStoreError as exc:
            warnings.append(f"{record.display_name}: unreadable — {exc}")
            continue
        rows = []
        for s in samples:
            n = normalize(s.embedding)
            if n is not None:
                rows.append(n)
        if not rows:
            warnings.append(f"{record.display_name}: no usable samples — skipped")
            continue
        gallery.append(
            GalleryIdentity(
                identity_id=record.identity_id,
                display_name=record.display_name,
                embeddings=np.vstack(rows),
            )
        )
    return gallery, warnings


class Matcher:
    """Matches one live embedding against a fixed gallery snapshot."""

    def __init__(self, gallery: list[GalleryIdentity]) -> None:
        self._gallery = list(gallery)

    @property
    def identity_count(self) -> int:
        return len(self._gallery)

    @property
    def sample_count(self) -> int:
        return sum(g.embeddings.shape[0] for g in self._gallery)

    def match(
        self,
        embedding: np.ndarray,
        *,
        threshold: float,
        margin: float,
        top_k: int,
    ) -> MatchResult:
        if not self._gallery:
            return _UNKNOWN_EMPTY
        probe = normalize(embedding)
        if probe is None:
            return _UNKNOWN_NO_EMBEDDING

        candidates = [
            MatchCandidate(
                identity_id=g.identity_id,
                display_name=g.display_name,
                score=top_k_mean(g.embeddings @ probe, top_k),
            )
            for g in self._gallery
        ]
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        if best.score < threshold:
            return MatchResult(
                is_known=False, identity_id=None, display_name=None,
                similarity=best.score, best=best, second_best=second,
                reason=REASON_BELOW_THRESHOLD,
            )
        if second is not None and (best.score - second.score) < margin:
            return MatchResult(
                is_known=False, identity_id=None, display_name=None,
                similarity=best.score, best=best, second_best=second,
                reason=REASON_AMBIGUOUS,
            )
        return MatchResult(
            is_known=True, identity_id=best.identity_id,
            display_name=best.display_name, similarity=best.score,
            best=best, second_best=second, reason=REASON_MATCH,
        )
