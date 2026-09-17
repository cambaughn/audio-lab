"""Conversation-layer types: scopes, records, and the routed bundle."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from audio_lab.llm.types import LlmMessage


class ContextScope(str, Enum):
    PRIVATE = "PRIVATE"          # verified speaker: private + shared, private history
    SHARED_ONLY = "SHARED_ONLY"  # recognized-not-verified: shared facts, session thread
    EPHEMERAL = "EPHEMERAL"      # unknown: nothing but this session's own thread


class RememberOutcome(str, Enum):
    SAVED_PRIVATE = "SAVED_PRIVATE"
    SESSION_ONLY = "SESSION_ONLY"


@dataclass(frozen=True)
class StoredMessage:
    message_id: str
    context_id: str
    role: str  # "user" | "assistant"
    content: str
    speaker_id: str | None
    decision: str | None      # AccessTier value at capture time
    similarity: float | None
    created_at: datetime


@dataclass(frozen=True)
class Fact:
    fact_id: str
    context_id: str
    content: str
    created_by_speaker_id: str
    created_at: datetime


@dataclass(frozen=True)
class ContextBundle:
    """Exactly what the router selected for one turn — nothing else may
    reach the model request."""

    scope: ContextScope
    speaker_label: str            # "Cameron" / "probably Cameron" / "Guest"
    system_prompt: str
    messages: tuple[LlmMessage, ...]
    facts: tuple[str, ...]        # exactly what was folded into system_prompt
    debug_summary: str            # the safe summary shown in debug UI
