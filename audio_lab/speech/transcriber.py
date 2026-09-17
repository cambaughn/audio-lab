"""Transcriber — local speech-to-text via faster-whisper.

distil-small.en, CPU int8 (macOS 13 has no CTranslate2 Metal path — a
permanent architectural fact, fine for push-to-talk utterance lengths).
Greedy decoding (beam_size=1): distil models are tuned for it, and beam
search buys accuracy we don't need at latency we'd notice. No VAD filter
— push-to-talk already bounds the utterance.

English-only by user decision (docs/plan). All processing local.
"""

from audio_lab.audio.clip import AudioClip

MODEL_NAME = "distil-small.en"


def _default_loader():
    from faster_whisper import WhisperModel

    from audio_lab.speech.hub import load_offline_first

    return load_offline_first(
        lambda: WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    )


class Transcriber:
    """Loads the STT model once and turns clips into text."""

    def __init__(self, loader=None) -> None:
        self._loader = loader or _default_loader
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load (downloading ~330 MB on first ever run). Raises on failure."""
        if self._model is None:
            self._model = self._loader()

    def transcribe(self, audio_clip: AudioClip) -> str:
        """Transcribe one clip. Returns '' when no speech was decoded."""
        if self._model is None:
            raise RuntimeError("Transcriber.load() must be called first")
        segments, _info = self._model.transcribe(
            audio_clip.samples,
            language="en",
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
