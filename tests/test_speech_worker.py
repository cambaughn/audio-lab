"""SpeechWorker driven synchronously with a fake embedder (no models)."""

import numpy as np

from audio_lab.audio.clip import make_clip
from audio_lab.identity.types import IdentityEvidence
from audio_lab.speech.worker import ModelState, SpeechWorker


class FakeEmbedder:
    def __init__(self, fail_load=False, fail_embed=False):
        self.fail_load = fail_load
        self.fail_embed = fail_embed
        self.embedded = []

    def load(self):
        if self.fail_load:
            raise RuntimeError("no network")

    def embed(self, clip):
        if self.fail_embed:
            raise RuntimeError("bad tensor")
        self.embedded.append(clip)
        return IdentityEvidence(
            embedding=np.ones(192, dtype=np.float32),
            model_id="fake-model",
            duration_s=clip.duration_s,
        )


def clip(seconds=1.0):
    return make_clip(0.3 * np.sin(np.arange(int(seconds * 16000)) / 10).astype(np.float32))


def run_worker(worker):
    """Run synchronously on the test thread (Identity Lab style)."""
    worker.run()


class TestSpeechWorker:
    def test_load_then_analyze_in_order(self, qt_core_app):
        fake = FakeEmbedder()
        worker = SpeechWorker(embedder=fake)
        states, analyses = [], []
        worker.model_state_changed.connect(states.append)
        worker.analysis_ready.connect(analyses.append)
        worker.analysis_ready.connect(
            lambda a: worker.request_stop() if len(analyses) >= 2 else None
        )
        worker.submit(clip(1.0))
        worker.submit(clip(2.0))
        run_worker(worker)
        assert states == [ModelState.LOADING.value, ModelState.READY.value]
        assert [round(a.evidence.duration_s) for a in analyses] == [1, 2]
        assert analyses[0].embed_ms >= 0.0

    def test_load_failure_is_terminal_and_signaled(self, qt_core_app):
        worker = SpeechWorker(embedder=FakeEmbedder(fail_load=True))
        states, errors, finished = [], [], []
        worker.model_state_changed.connect(states.append)
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))
        run_worker(worker)
        assert states == [ModelState.LOADING.value, ModelState.FAILED.value]
        assert errors and "MODEL FAILED" in errors[0]
        assert finished == [True]

    def test_embed_failure_reports_and_continues(self, qt_core_app):
        fake = FakeEmbedder(fail_embed=True)
        worker = SpeechWorker(embedder=fake)
        errors = []
        worker.error.connect(errors.append)
        worker.error.connect(lambda _: worker.request_stop())
        worker.submit(clip())
        run_worker(worker)
        assert errors and "ANALYSIS ERROR" in errors[0]
