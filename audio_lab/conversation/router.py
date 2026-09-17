"""ContextRouter — the deterministic privacy core.

Privacy in Audio Lab is a property of WHICH BYTES this module selects,
never of prompt wording. route() maps a recognition decision onto exactly
the context that tier is authorized for; unauthorized content is absent
from the result, so there is nothing for a model to be talked out of.
The system prompt never names other speakers and never contains
withholding instructions — both pinned by regression tests.

| tier             | scope       | facts                       | history               |
|------------------|-------------|-----------------------------|-----------------------|
| PRIVATE_VERIFIED | PRIVATE     | shared + own private        | own private context   |
| RECOGNIZED       | SHARED_ONLY | shared + own session facts  | own session thread    |
| UNKNOWN          | EPHEMERAL   | own session facts only      | guest session thread  |

Writes go to the container the turn was routed from; "remember <fact>"
persists only for PRIVATE_VERIFIED. Sharing is a deliberate UI action
(ConversationStore.share_fact), never a routing side effect.

Plain object: no Qt, no LLM, no audio. Fully deterministic.
"""

import re

from audio_lab.conversation.ephemeral import GUEST_KEY, EphemeralRegistry
from audio_lab.conversation.store import ConversationStore
from audio_lab.conversation.types import (
    ContextBundle,
    ContextScope,
    RememberOutcome,
)
from audio_lab.identity.decision import AccessTier, RecognitionDecision
from audio_lab.llm.types import LlmMessage, LlmRequest

PERSONA = (
    "You are Audio Lab, a local household voice-assistant experiment. "
    "Reply in one or two short sentences suitable for being spoken aloud. "
    "The application manages durable memory for you, outside this "
    "conversation: facts you have been given are already listed in these "
    "instructions. If the speaker asks you to remember something, ask them "
    "to repeat it as a sentence starting with the word 'remember' — that "
    "phrasing is what saves it."
)

HISTORY_LIMIT = 20

_REMEMBER_PATTERN = re.compile(r"^\s*remember\b[,:]?\s*(?P<fact>.+)$", re.IGNORECASE)


def detect_remember(transcript: str) -> str | None:
    """Deterministic leading-word trigger; returns the fact text or None."""
    match = _REMEMBER_PATTERN.match(transcript.strip())
    if match is None:
        return None
    fact = match.group("fact").strip().rstrip(".!")
    return fact or None


def build_request(
    bundle: ContextBundle, transcript: str, model: str, max_tokens: int = 300
) -> LlmRequest:
    """Compose the outbound request from a routed bundle and the new turn.
    This is the ONLY place a request is assembled — nothing outside the
    bundle may enter it."""
    return LlmRequest(
        system_prompt=bundle.system_prompt,
        messages=bundle.messages + (LlmMessage(role="user", content=transcript),),
        model=model,
        max_tokens=max_tokens,
        metadata=(
            ("scope", bundle.scope.value),
            ("speaker", bundle.speaker_label),
        ),
    )


class ContextRouter:
    def __init__(
        self,
        store: ConversationStore,
        ephemerals: EphemeralRegistry,
        history_limit: int = HISTORY_LIMIT,
    ) -> None:
        self._store = store
        self._ephemerals = ephemerals
        self._history_limit = history_limit

    # -- reads --

    def route(self, decision: RecognitionDecision, transcript: str) -> ContextBundle:
        if decision.tier is AccessTier.PRIVATE_VERIFIED:
            return self._route_private(decision)
        if decision.tier is AccessTier.RECOGNIZED:
            return self._route_shared_only(decision)
        return self._route_ephemeral()

    def _route_private(self, decision: RecognitionDecision) -> ContextBundle:
        context_id = self._store.private_context_id(decision.identity_id)
        shared = self._shared_fact_texts()
        private = [f.content for f in self._store.facts(context_id)]
        facts = tuple(shared + private)
        history = tuple(
            LlmMessage(role=m.role, content=m.content)
            for m in self._store.recent_messages(context_id, self._history_limit)
        )
        identity_line = f"You are speaking with {decision.display_name}."
        return self._bundle(
            ContextScope.PRIVATE, decision.display_name, identity_line, facts, history
        )

    def _route_shared_only(self, decision: RecognitionDecision) -> ContextBundle:
        session = self._ephemerals.session_for(decision.identity_id)
        facts = tuple(self._shared_fact_texts() + list(session.facts))
        identity_line = (
            f"You are probably speaking with {decision.display_name} "
            "(identity not verified for private information)."
        )
        return self._bundle(
            ContextScope.SHARED_ONLY,
            f"probably {decision.display_name}",
            identity_line,
            facts,
            tuple(session.messages),
        )

    def _route_ephemeral(self) -> ContextBundle:
        session = self._ephemerals.session_for(GUEST_KEY)
        identity_line = "You are speaking with an unidentified guest."
        return self._bundle(
            ContextScope.EPHEMERAL,
            "Guest",
            identity_line,
            tuple(session.facts),
            tuple(session.messages),
        )

    def _bundle(
        self,
        scope: ContextScope,
        label: str,
        identity_line: str,
        facts: tuple[str, ...],
        history: tuple[LlmMessage, ...],
    ) -> ContextBundle:
        prompt = f"{PERSONA}\n\n{identity_line}"
        if facts:
            prompt += "\n\nKNOWN FACTS:\n" + "\n".join(f"- {f}" for f in facts)
        summary = (
            f"SCOPE {scope.value} · SPEAKER {label.upper()} · "
            f"{len(history)} MSGS · {len(facts)} FACTS"
        )
        return ContextBundle(
            scope=scope,
            speaker_label=label,
            system_prompt=prompt,
            messages=history,
            facts=facts,
            debug_summary=summary,
        )

    # -- writes --

    def record_exchange(
        self,
        decision: RecognitionDecision,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Store the turn in the same container it was routed from."""
        if decision.tier is AccessTier.PRIVATE_VERIFIED:
            context_id = self._store.private_context_id(decision.identity_id)
            self._store.add_message(
                context_id,
                "user",
                user_text,
                speaker_id=decision.identity_id,
                decision=decision.tier.value,
                similarity=decision.similarity,
            )
            self._store.add_message(context_id, "assistant", assistant_text)
            return
        key = (
            decision.identity_id
            if decision.tier is AccessTier.RECOGNIZED
            else GUEST_KEY
        )
        session = self._ephemerals.session_for(key)
        session.messages.append(LlmMessage(role="user", content=user_text))
        session.messages.append(LlmMessage(role="assistant", content=assistant_text))

    def handle_remember(
        self, decision: RecognitionDecision, fact_text: str
    ) -> RememberOutcome:
        """Persist a fact only for a privately-verified speaker; everyone
        else gets a session-only note that dies with the session."""
        if decision.tier is AccessTier.PRIVATE_VERIFIED:
            context_id = self._store.private_context_id(decision.identity_id)
            self._store.add_fact(context_id, fact_text, decision.identity_id)
            return RememberOutcome.SAVED_PRIVATE
        key = (
            decision.identity_id
            if decision.tier is AccessTier.RECOGNIZED
            else GUEST_KEY
        )
        self._ephemerals.session_for(key).facts.append(fact_text)
        return RememberOutcome.SESSION_ONLY

    # -- helpers --

    def _shared_fact_texts(self) -> list[str]:
        return [f.content for f in self._store.facts(self._store.shared_context_id())]
