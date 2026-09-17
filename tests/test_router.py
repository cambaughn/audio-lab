"""Router semantics beyond the canary matrix: prompts, bundles, ephemerals."""

import pytest

from audio_lab.conversation.ephemeral import EphemeralRegistry
from audio_lab.conversation.router import PERSONA, build_request
from audio_lab.conversation.types import ContextScope
from tests.world import ALL_DECISIONS, CANARY_SHARED, make_world


@pytest.fixture()
def world(tmp_path):
    store, ephemerals, router = make_world(tmp_path)
    yield store, ephemerals, router
    store.close()


class TestBundles:
    def test_private_bundle_shape(self, world):
        _, _, router = world
        bundle = router.route(ALL_DECISIONS["PV(cam)"], "hello")
        assert bundle.scope is ContextScope.PRIVATE
        assert bundle.speaker_label == "Cameron"
        assert bundle.system_prompt.startswith(PERSONA)
        assert (
            "You are speaking with Cameron, identified by voice for this turn."
            in bundle.system_prompt
        )
        assert any(CANARY_SHARED in f for f in bundle.facts)
        assert len(bundle.messages) == 2  # seeded history
        assert "SCOPE PRIVATE" in bundle.debug_summary
        assert "2 MSGS" in bundle.debug_summary

    def test_recognized_bundle_says_probably(self, world):
        _, _, router = world
        bundle = router.route(ALL_DECISIONS["REC(cam)"], "hello")
        assert bundle.scope is ContextScope.SHARED_ONLY
        assert bundle.speaker_label == "probably Cameron"
        assert "probably speaking with Cameron" in bundle.system_prompt
        assert "not verified" in bundle.system_prompt
        assert bundle.messages == ()  # fresh session thread

    def test_guest_bundle_is_empty(self, world):
        _, _, router = world
        bundle = router.route(ALL_DECISIONS["UNKNOWN"], "hello")
        assert bundle.scope is ContextScope.EPHEMERAL
        assert bundle.speaker_label == "Guest"
        assert "unidentified guest" in bundle.system_prompt
        assert bundle.facts == ()
        assert len(bundle.messages) == 1  # the seeded guest line, own session

    def test_facts_block_only_when_facts_exist(self, tmp_path):
        from audio_lab.conversation.router import ContextRouter
        from audio_lab.conversation.store import ConversationStore

        store = ConversationStore(tmp_path / "empty.db")
        router = ContextRouter(store, EphemeralRegistry())
        bundle = router.route(ALL_DECISIONS["UNKNOWN"], "hi")
        assert "KNOWN FACTS" not in bundle.system_prompt
        store.close()


class TestBuildRequest:
    def test_appends_transcript_as_final_user_turn(self, world):
        _, _, router = world
        bundle = router.route(ALL_DECISIONS["PV(cam)"], "what's my code?")
        request = build_request(bundle, "what's my code?", model="m1", max_tokens=99)
        assert request.messages[-1].role == "user"
        assert request.messages[-1].content == "what's my code?"
        assert request.messages[:-1] == bundle.messages
        assert request.system_prompt == bundle.system_prompt
        assert ("scope", "PRIVATE") in request.metadata
        assert request.max_tokens == 99

    def test_request_built_only_from_bundle(self, world):
        # structural check: every non-transcript message in the request
        # exists in the bundle — nothing else can sneak in
        _, _, router = world
        for key, decision in ALL_DECISIONS.items():
            bundle = router.route(decision, "probe")
            request = build_request(bundle, "probe", model="m")
            assert set(request.messages[:-1]) <= set(bundle.messages)


class TestExchangeRecording:
    def test_private_exchange_persists_with_attribution(self, world):
        store, _, router = world
        d = ALL_DECISIONS["PV(cam)"]
        router.record_exchange(d, "my question", "my answer")
        messages = store.recent_messages(store.private_context_id(d.identity_id), 10)
        assert messages[-2].content == "my question"
        assert messages[-2].speaker_id == d.identity_id
        assert messages[-2].decision == "PRIVATE_VERIFIED"
        assert messages[-1].role == "assistant"

    def test_recognized_and_guest_use_separate_sessions(self, world):
        _, ephemerals, router = world
        router.record_exchange(ALL_DECISIONS["REC(cam)"], "cam session", "ok")
        router.record_exchange(ALL_DECISIONS["UNKNOWN"], "guest words", "ok")
        cam_session = ephemerals.session_for("cam-id-001")
        guest_session = ephemerals.session_for("guest")
        assert any("cam session" in m.content for m in cam_session.messages)
        assert not any("cam session" in m.content for m in guest_session.messages)


class TestEphemeralRegistry:
    def test_lazy_sessions_and_clear(self):
        registry = EphemeralRegistry()
        assert registry.peek("guest") is None
        session = registry.session_for("guest")
        session.facts.append("x")
        assert registry.session_for("guest") is session
        assert registry.clear_all() == 1
        assert registry.peek("guest") is None
