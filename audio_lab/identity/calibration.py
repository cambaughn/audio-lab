"""Threshold calibration from enrolled data — pure, no Qt, no models.

Genuine scores: leave-one-out — each enrolled sample scored against the
top-k of the same identity's remaining samples. Impostor scores: each
sample scored against every OTHER identity's full gallery. With two
enrolled speakers and 6 samples each this yields 12 genuine and 12
impostor scores — few, but measured on the actual voices, actual mic,
and actual room, which beats any published number.

Suggestions are advisory; the user sets the sliders (docs/experiment.md).
"""

from dataclasses import dataclass

import numpy as np

from audio_lab.identity.matcher import normalize, top_k_mean
from audio_lab.identity.store import IdentityStore


@dataclass(frozen=True)
class ScoreDistributions:
    genuine: tuple[float, ...]
    impostor: tuple[float, ...]


@dataclass(frozen=True)
class ThresholdSuggestion:
    recognition: float
    private_access: float


def score_distributions(
    store: IdentityStore, model_id: str, top_k: int = 3
) -> ScoreDistributions:
    galleries: dict[str, np.ndarray] = {}
    for record in store.list_identities():
        if record.sample_count == 0 or record.model_id != model_id:
            continue
        rows = [
            n
            for s in store.get_embedding_samples(record.identity_id)
            if (n := normalize(s.embedding)) is not None
        ]
        if rows:
            galleries[record.identity_id] = np.vstack(rows)

    genuine: list[float] = []
    impostor: list[float] = []
    for identity_id, matrix in galleries.items():
        for i in range(matrix.shape[0]):
            probe = matrix[i]
            others = np.delete(matrix, i, axis=0)
            if others.shape[0] > 0:
                genuine.append(top_k_mean(others @ probe, top_k))
            for other_id, other_matrix in galleries.items():
                if other_id != identity_id:
                    impostor.append(top_k_mean(other_matrix @ probe, top_k))
    return ScoreDistributions(genuine=tuple(genuine), impostor=tuple(impostor))


def suggest_thresholds(dist: ScoreDistributions) -> ThresholdSuggestion | None:
    """Advisory starting points; None when there is not enough data."""
    if not dist.genuine or not dist.impostor:
        return None
    min_genuine = min(dist.genuine)
    max_impostor = max(dist.impostor)
    recognition = round((min_genuine + max_impostor) / 2.0, 2)
    recognition = float(np.clip(recognition, 0.05, 0.95))
    private_access = round(max(recognition + 0.10, min_genuine - 0.03), 2)
    private_access = float(np.clip(private_access, recognition, 0.95))
    return ThresholdSuggestion(recognition=recognition, private_access=private_access)


def summarize(values: tuple[float, ...]) -> str:
    if not values:
        return "none"
    arr = np.asarray(values)
    return (
        f"n={arr.size}  min={arr.min():.3f}  median={np.median(arr):.3f}  "
        f"max={arr.max():.3f}"
    )
