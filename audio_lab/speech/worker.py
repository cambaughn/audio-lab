"""SpeechWorker — owns the ML models on a background thread.

Identity Lab InferenceWorker pattern: a long-lived QObject moved to a
QThread at launch; the model loads once at startup; clips are submitted
via a thread-safe slot and results come back as signals. Errors never
raise across the thread boundary. Batch 3 adds transcription to the same
per-clip pass.
"""

import threading
import time
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, Signal, Slot

from audio_lab.audio.clip import AudioClip
from audio_lab.identity.types import IdentityEvidence
from audio_lab.speech.embedder import SpeakerEmbedder
from audio_lab.speech.transcriber import Transcriber


class ModelState(str, Enum):
    LOADING = "MODEL LOADING"
    READY = "MODEL READY"
    FAILED = "MODEL FAILED"


@dataclass(frozen=True, eq=False)
class SpeechAnalysis:
    """Everything the speech stage learned about one clip.

    transcript is None when transcription failed (attribution still
    stands — "who spoke" and "what was said" fail independently), and ''
    when the model decoded no speech.
    """

    clip: AudioClip
    evidence: IdentityEvidence
    embed_ms: float
    transcript: str | None
    transcribe_ms: float


class SpeechWorker(QObject):
    """Loads models and analyzes clips; lives on its own QThread.

    Signals are the only outward channel. submit() is safe from any
    thread; analyses come back in submission order.
    """

    model_state_changed = Signal(str)  # ModelState value
    analysis_ready = Signal(object)    # SpeechAnalysis
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        embedder: SpeakerEmbedder | None = None,
        transcriber: Transcriber | None = None,
        clock=time.monotonic,
    ) -> None:
        super().__init__()
        self._embedder = embedder or SpeakerEmbedder()
        self._transcriber = transcriber or Transcriber()
        self._clock = clock
        self._queue: list[AudioClip] = []
        self._queue_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()

    # -- any thread --

    def submit(self, audio_clip: AudioClip) -> None:
        with self._queue_lock:
            self._queue.append(audio_clip)
        self._wake.set()

    def request_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # -- worker thread --

    @Slot()
    def run(self) -> None:
        try:
            self.model_state_changed.emit(ModelState.LOADING.value)
            try:
                self._embedder.load()
                self._transcriber.load()
            except Exception as exc:
                self.model_state_changed.emit(ModelState.FAILED.value)
                self.error.emit(f"MODEL FAILED: {exc}")
                return
            self.model_state_changed.emit(ModelState.READY.value)

            while not self._stop.is_set():
                self._wake.wait(timeout=0.2)
                self._wake.clear()
                while True:
                    with self._queue_lock:
                        if not self._queue:
                            break
                        clip = self._queue.pop(0)
                    self._analyze(clip)
                    if self._stop.is_set():
                        break
        except Exception as exc:  # never let an exception cross the thread
            self.error.emit(f"SPEECH WORKER FAILURE: {exc}")
        finally:
            self.finished.emit()

    def _analyze(self, clip: AudioClip) -> None:
        try:
            t0 = self._clock()
            evidence = self._embedder.embed(clip)
            embed_ms = (self._clock() - t0) * 1000.0
        except Exception as exc:
            self.error.emit(f"ANALYSIS ERROR: {exc}")
            return
        # Transcription fails independently of attribution: a broken STT
        # pass still yields an attributed turn with transcript=None.
        transcript: str | None
        try:
            t1 = self._clock()
            transcript = self._transcriber.transcribe(clip)
            transcribe_ms = (self._clock() - t1) * 1000.0
        except Exception as exc:
            transcript = None
            transcribe_ms = 0.0
            self.error.emit(f"TRANSCRIPTION ERROR: {exc}")
        self.analysis_ready.emit(
            SpeechAnalysis(
                clip=clip,
                evidence=evidence,
                embed_ms=embed_ms,
                transcript=transcript,
                transcribe_ms=transcribe_ms,
            )
        )
