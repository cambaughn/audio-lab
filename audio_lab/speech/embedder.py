"""SpeakerEmbedder — local ECAPA-TDNN voice embeddings via SpeechBrain.

Pure wrapper, no Qt. The model loads once (~12 s cold including download,
~5 s warm) and then embeds a clip in ~45 ms on the M2 CPU (measured,
docs/environment.md). CPU is deliberate: at this model size MPS overhead
exceeds the gain.

All processing is local; embeddings never leave the machine.
"""

import numpy as np

from audio_lab.audio.clip import AudioClip
from audio_lab.identity.types import IdentityEvidence

MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
EMBEDDING_DIM = 192


def _default_loader():
    from pathlib import Path

    from speechbrain.inference.speaker import EncoderClassifier

    savedir = (
        Path.home()
        / "Library"
        / "Application Support"
        / "AudioLab"
        / "models"
        / "spkrec-ecapa-voxceleb"
    )
    return EncoderClassifier.from_hparams(
        source=MODEL_ID, savedir=str(savedir), run_opts={"device": "cpu"}
    )


class SpeakerEmbedder:
    """Loads the speaker model and turns clips into IdentityEvidence."""

    def __init__(self, loader=None) -> None:
        self._loader = loader or _default_loader
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load (downloading on first ever run). Raises on failure."""
        if self._model is None:
            self._model = self._loader()

    def embed(self, audio_clip: AudioClip) -> IdentityEvidence:
        """Embed one clip. Never raises on bad output — returns evidence
        with embedding=None instead (routes to UNKNOWN downstream)."""
        if self._model is None:
            raise RuntimeError("SpeakerEmbedder.load() must be called first")
        import torch

        wav = torch.from_numpy(np.ascontiguousarray(audio_clip.samples)).unsqueeze(0)
        with torch.no_grad():
            out = self._model.encode_batch(wav)
        vec = out.squeeze().cpu().numpy().astype(np.float32).ravel()
        if vec.size != EMBEDDING_DIM or not np.all(np.isfinite(vec)):
            vec = None
        return IdentityEvidence(
            embedding=vec, model_id=MODEL_ID, duration_s=audio_clip.duration_s
        )
