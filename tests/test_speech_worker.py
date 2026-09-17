"""SpeechWorker driven synchronously with a fake embedder (no models)."""

import numpy as np

from audio_lab.audio.clip import make_clip
from audio_lab.identity.types import IdentityEvidence
from audio_lab.speech.worker import ModelState, SpeechWorker


class FakeTranscriber:
    def __init__(self, fail_load=False, fail_transcribe=False, text="hello world"):
        self.fail_load = fail_load
        self.fail_transcribe = fail_transcribe
        self.text = text

    def load(self):
        if self.fail_load:
            raise RuntimeError("no whisper download")

    def transcribe(self, clip):
        if self.fail_transcribe:
            raise RuntimeError("decode blew up")
        return self.text


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


def make_worker(embedder=None, transcriber=None):
    return SpeechWorker(
        embedder=embedder or FakeEmbedder(),
        transcriber=transcriber or FakeTranscriber(),
    )


class TestSpeechWorker:
    def test_load_then_analyze_in_order(self, qt_core_app):
        fake = FakeEmbedder()
        worker = make_worker(embedder=fake)
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
        assert analyses[0].transcript == "hello world"
        assert analyses[0].transcribe_ms >= 0.0

    def test_load_failure_is_terminal_and_signaled(self, qt_core_app):
        worker = make_worker(embedder=FakeEmbedder(fail_load=True))
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
        worker = make_worker(embedder=fake)
        errors = []
        worker.error.connect(errors.append)
        worker.error.connect(lambda _: worker.request_stop())
        worker.submit(clip())
        run_worker(worker)
        assert errors and "ANALYSIS ERROR" in errors[0]

    def test_transcriber_load_failure_is_model_failed(self, qt_core_app):
        worker = make_worker(transcriber=FakeTranscriber(fail_load=True))
        states, errors = [], []
        worker.model_state_changed.connect(states.append)
        worker.error.connect(errors.append)
        run_worker(worker)
        assert states == [ModelState.LOADING.value, ModelState.FAILED.value]
        assert "MODEL FAILED" in errors[0]

    def test_transcription_failure_keeps_attribution(self, qt_core_app):
        worker = make_worker(transcriber=FakeTranscriber(fail_transcribe=True))
        analyses, errors = [], []
        worker.analysis_ready.connect(analyses.append)
        worker.analysis_ready.connect(lambda a: worker.request_stop())
        worker.error.connect(errors.append)
        worker.submit(clip())
        run_worker(worker)
        assert len(analyses) == 1
        assert analyses[0].transcript is None          # STT failed...
        assert analyses[0].evidence.embedding is not None  # ...attribution stands
        assert any("TRANSCRIPTION ERROR" in e for e in errors)


class TestTurnFormatting:
    def test_format_turn(self):
        from audio_lab.ui.conversation_view import format_turn

        assert format_turn("CAMERON", 0.63, "hi there") == "[CAMERON 0.63] hi there"
        assert format_turn("UNKNOWN", None, "who dis") == "[UNKNOWN] who dis"


class TestOfflineFirstLoading:
    def test_offline_success_restores_env(self, monkeypatch):
        import os

        from audio_lab.speech.hub import load_offline_first

        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        seen = []

        def loader():
            seen.append(os.environ.get("HF_HUB_OFFLINE"))
            return "model"

        assert load_offline_first(loader) == "model"
        assert seen == ["1"]  # offline forced during the load
        assert "HF_HUB_OFFLINE" not in os.environ  # and restored after

    def test_falls_back_online_when_cache_missing(self, monkeypatch):
        import os

        from audio_lab.speech.hub import load_offline_first

        monkeypatch.setenv("HF_HUB_OFFLINE", "0")
        seen = []

        def loader():
            seen.append(os.environ.get("HF_HUB_OFFLINE"))
            if len(seen) == 1:
                raise FileNotFoundError("not cached")
            return "downloaded"

        assert load_offline_first(loader) == "downloaded"
        assert seen == ["1", "0"]  # offline attempt, then online with prior env
        assert os.environ["HF_HUB_OFFLINE"] == "0"
