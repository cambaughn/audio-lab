"""The LLM request/response boundary — frozen, inspectable, serializable.

LlmRequest.serialized() is the canonical text of EVERYTHING outbound: the
system prompt, every message, the metadata, the model id. It exists so
privacy tests can scan the exact bytes that would leave the machine —
if a canary string is absent from serialized(), it is absent from the
request. Adapters must build their provider payload from these fields
and nothing else.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LlmRequest:
    system_prompt: str
    messages: tuple[LlmMessage, ...]
    model: str
    max_tokens: int
    metadata: tuple[tuple[str, str], ...] = ()

    def serialized(self) -> str:
        """Canonical text of everything outbound — the canary-scan surface."""
        parts = [f"[system]\n{self.system_prompt}"]
        for message in self.messages:
            parts.append(f"[{message.role}]\n{message.content}")
        if self.metadata:
            parts.append(
                "[metadata]\n" + "\n".join(f"{k}={v}" for k, v in self.metadata)
            )
        parts.append(f"[model]\n{self.model} max_tokens={self.max_tokens}")
        return "\n\n".join(parts)


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
