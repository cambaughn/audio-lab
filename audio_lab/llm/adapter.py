"""LLM adapter boundary — protocol, fake, and recording wrapper.

FakeLlmAdapter is the only adapter that exists until the privacy suite is
green (CP9 rule: no network code before the tests prove isolation). The
RecordingAdapter wraps any adapter so the debug UI can always show the
true last outbound request — ground truth, never a reconstruction.
"""

from typing import Protocol

from audio_lab.llm.types import LlmRequest, LlmResponse


class LlmError(Exception):
    """Base class for adapter failures."""


class LlmConfigError(LlmError):
    """Missing or invalid provider configuration (no key, bad llm.json)."""


class LlmNetworkError(LlmError):
    """The provider could not be reached or the call timed out."""


class LlmResponseError(LlmError):
    """The provider answered with an error or an unusable response."""


class LlmAdapter(Protocol):
    def complete(self, request: LlmRequest) -> LlmResponse: ...


class FakeLlmAdapter:
    """Records every request; replies from a script or with a
    deterministic echo. The privacy suite's instrument."""

    MODEL = "fake-llm"

    def __init__(self, script: list[str] | None = None) -> None:
        self.requests: list[LlmRequest] = []
        self._script = list(script) if script else []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if self._script:
            text = self._script.pop(0)
        else:
            last_user = next(
                (m.content for m in reversed(request.messages) if m.role == "user"),
                "",
            )
            text = f"FAKE REPLY TO: {last_user}"
        return LlmResponse(text=text, model=self.MODEL, stop_reason="end_turn")


class RecordingAdapter:
    """Wraps any adapter and keeps (request, response) pairs in memory."""

    def __init__(self, inner: LlmAdapter) -> None:
        self._inner = inner
        self.exchanges: list[tuple[LlmRequest, LlmResponse]] = []

    @property
    def last_request(self) -> LlmRequest | None:
        return self.exchanges[-1][0] if self.exchanges else None

    def complete(self, request: LlmRequest) -> LlmResponse:
        response = self._inner.complete(request)
        self.exchanges.append((request, response))
        return response
