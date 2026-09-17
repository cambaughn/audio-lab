"""AnthropicAdapter — the only network code in Audio Lab.

Added at CP11, after the privacy suite proved isolation against the fake
adapter (CP9 rule). Builds the provider payload from the frozen
LlmRequest's fields and NOTHING else — the same bytes serialized() scans
are the only bytes that leave. Non-streaming, 30 s timeout, one retry.
"""

from audio_lab.llm.adapter import (
    LlmNetworkError,
    LlmResponseError,
)
from audio_lab.llm.config import LlmConfig, resolve_api_key
from audio_lab.llm.types import LlmRequest, LlmResponse


def _default_client_factory(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=1)


class AnthropicAdapter:
    """Calls the Anthropic Messages API. Raises LlmConfigError at
    construction when the key is missing — never mid-conversation."""

    def __init__(self, llm_config: LlmConfig, client_factory=None) -> None:
        api_key = resolve_api_key(llm_config)  # raises LlmConfigError
        self.model = llm_config.model
        self._client = (client_factory or _default_client_factory)(api_key)

    def complete(self, request: LlmRequest) -> LlmResponse:
        import anthropic

        try:
            response = self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=request.system_prompt,
                messages=[
                    {"role": m.role, "content": m.content} for m in request.messages
                ],
            )
        except anthropic.APIConnectionError as exc:
            raise LlmNetworkError(f"cannot reach Anthropic: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LlmResponseError(
                f"Anthropic error {exc.status_code}: {exc.message}"
            ) from exc

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if not text:
            text = f"(NO TEXT RESPONSE — stop_reason={response.stop_reason})"
        return LlmResponse(
            text=text,
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=getattr(response.usage, "input_tokens", None),
            output_tokens=getattr(response.usage, "output_tokens", None),
        )
