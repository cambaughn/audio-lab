"""Ephemeral sessions — in-memory by design, never SQLite.

Deletability at session end is a structural property, not a cleanup job:
these objects live in a plain dict, END GUEST SESSION clears them, and
app exit discards them by construction. Guests and under-verified
speakers can therefore never leave a persistent trace.
"""

from dataclasses import dataclass, field

from audio_lab.llm.types import LlmMessage

GUEST_KEY = "guest"


@dataclass
class EphemeralSession:
    messages: list[LlmMessage] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)


class EphemeralRegistry:
    """Per-key ephemeral sessions: one per RECOGNIZED speaker, one guest."""

    def __init__(self) -> None:
        self._sessions: dict[str, EphemeralSession] = {}

    def session_for(self, key: str) -> EphemeralSession:
        if key not in self._sessions:
            self._sessions[key] = EphemeralSession()
        return self._sessions[key]

    def peek(self, key: str) -> EphemeralSession | None:
        return self._sessions.get(key)

    def clear_all(self) -> int:
        """END GUEST SESSION: drop every ephemeral session. Returns count."""
        count = len(self._sessions)
        self._sessions.clear()
        return count
