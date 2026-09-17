"""LlmRequest serialization covers everything outbound; adapters record."""

import pytest

from audio_lab.llm.adapter import FakeLlmAdapter, RecordingAdapter
from audio_lab.llm.types import LlmMessage, LlmRequest, LlmResponse


def request() -> LlmRequest:
    return LlmRequest(
        system_prompt="SYSTEM-MARKER persona text",
        messages=(
            LlmMessage("user", "USER-MARKER-1 hello"),
            LlmMessage("assistant", "ASSISTANT-MARKER reply"),
            LlmMessage("user", "USER-MARKER-2 follow-up"),
        ),
        model="MODEL-MARKER",
        max_tokens=123,
        metadata=(("scope", "PRIVATE"), ("speaker", "Cameron")),
    )


class TestSerialization:
    def test_covers_every_outbound_field(self):
        s = request().serialized()
        for marker in (
            "SYSTEM-MARKER",
            "USER-MARKER-1",
            "ASSISTANT-MARKER",
            "USER-MARKER-2",
            "MODEL-MARKER",
            "scope=PRIVATE",
            "speaker=Cameron",
            "max_tokens=123",
        ):
            assert marker in s, f"serialized() must cover {marker}"

    def test_frozen(self):
        req = request()
        with pytest.raises(Exception):
            req.model = "other"  # type: ignore[misc]


class TestAdapters:
    def test_fake_records_and_echoes_last_user(self):
        adapter = FakeLlmAdapter()
        response = adapter.complete(request())
        assert adapter.requests == [request()]
        assert response.text == "FAKE REPLY TO: USER-MARKER-2 follow-up"
        assert isinstance(response, LlmResponse)

    def test_fake_scripted_replies_in_order(self):
        adapter = FakeLlmAdapter(script=["first", "second"])
        assert adapter.complete(request()).text == "first"
        assert adapter.complete(request()).text == "second"
        assert adapter.complete(request()).text.startswith("FAKE REPLY TO")

    def test_recording_wrapper_keeps_ground_truth(self):
        inner = FakeLlmAdapter(script=["yo"])
        recorder = RecordingAdapter(inner)
        assert recorder.last_request is None
        response = recorder.complete(request())
        assert response.text == "yo"
        assert recorder.last_request == request()
        assert recorder.exchanges[0][1].text == "yo"
