"""THE experiment: exhaustive canary matrix over the serialized request.

For every recognition decision, route a turn and serialize the exact
outbound request. Another speaker's private canaries must be byte-absent
in every cell; each canary may appear only where its tier authorizes it.
These tests run against FakeLlmAdapter and passed before any network
adapter existed in the tree (CP9 rule).
"""

import pytest

from audio_lab.conversation.router import build_request
from audio_lab.llm.adapter import FakeLlmAdapter
from tests.world import (
    ALL_DECISIONS,
    CANARY_RILEY_HIST,
    CANARY_RILEY_PRIV,
    CANARY_CAM_HIST,
    CANARY_CAM_PRIV,
    CANARY_GUEST,
    CANARY_SHARED,
    make_world,
)

PROBE = "What do you know about everyone?"


def serialized_request_for(router, decision) -> str:
    """Route -> build -> send through the fake adapter -> scan what it saw."""
    bundle = router.route(decision, PROBE)
    request = build_request(bundle, PROBE, model="fake-llm")
    adapter = FakeLlmAdapter()
    adapter.complete(request)
    assert len(adapter.requests) == 1
    return adapter.requests[0].serialized()


@pytest.fixture()
def world(tmp_path):
    store, ephemerals, router = make_world(tmp_path)
    yield store, ephemerals, router
    store.close()


# canary -> the set of decision keys allowed to see it
AUTHORIZED = {
    CANARY_CAM_PRIV: {"PV(cam)"},
    CANARY_CAM_HIST: {"PV(cam)"},
    CANARY_RILEY_PRIV: {"PV(riley)"},
    CANARY_RILEY_HIST: {"PV(riley)"},
    CANARY_SHARED: {"PV(cam)", "PV(riley)", "REC(cam)", "REC(riley)"},
    CANARY_GUEST: {"UNKNOWN"},
}


class TestReadMatrix:
    @pytest.mark.parametrize("decision_key", list(ALL_DECISIONS))
    @pytest.mark.parametrize("canary", list(AUTHORIZED))
    def test_canary_present_iff_authorized(self, world, decision_key, canary):
        _, _, router = world
        serialized = serialized_request_for(router, ALL_DECISIONS[decision_key])
        if decision_key in AUTHORIZED[canary]:
            assert canary in serialized, (
                f"{decision_key} is authorized for {canary} but it is missing"
            )
        else:
            assert canary not in serialized, (
                f"LEAK: {canary} appeared in the request for {decision_key}"
            )

    @pytest.mark.parametrize("decision_key", list(ALL_DECISIONS))
    def test_other_speakers_name_absent_from_system_prompt(self, world, decision_key):
        _, _, router = world
        decision = ALL_DECISIONS[decision_key]
        bundle = router.route(decision, PROBE)
        own = (decision.display_name or "").lower()
        for name in ("cameron", "riley"):
            if name != own:
                assert name not in bundle.system_prompt.lower(), (
                    f"{decision_key}: system prompt mentions other speaker {name!r}"
                )

    def test_guest_gets_absolutely_nothing_stored(self, world):
        _, _, router = world
        serialized = serialized_request_for(router, ALL_DECISIONS["UNKNOWN"])
        for canary in (
            CANARY_CAM_PRIV,
            CANARY_CAM_HIST,
            CANARY_RILEY_PRIV,
            CANARY_RILEY_HIST,
            CANARY_SHARED,
        ):
            assert canary not in serialized


class TestMechanismRegression:
    """Privacy must never be enforced by prompt instruction — pinned."""

    FORBIDDEN = (
        "do not reveal",
        "do not share",
        "don't tell",
        "must not",
        "keep secret",
        "other user",
        "confidential",
    )

    @pytest.mark.parametrize("decision_key", list(ALL_DECISIONS))
    def test_no_withholding_language(self, world, decision_key):
        _, _, router = world
        bundle = router.route(ALL_DECISIONS[decision_key], PROBE)
        prompt = bundle.system_prompt.lower()
        for phrase in self.FORBIDDEN:
            assert phrase not in prompt, (
                f"withholding instruction {phrase!r} crept into the system prompt"
            )


class TestIndirectLeaks:
    def test_share_fact_copies_exactly_one_fact(self, world):
        store, _, router = world
        cam_ctx = store.private_context_id("cam-id-001")
        cam_facts = store.facts(cam_ctx)
        shared_before = store.facts(store.shared_context_id())
        store.share_fact(cam_facts[0].fact_id)
        shared_after = store.facts(store.shared_context_id())
        assert len(shared_after) == len(shared_before) + 1
        assert shared_after[-1].content == cam_facts[0].content
        # original private fact untouched
        assert len(store.facts(cam_ctx)) == len(cam_facts)

    def test_shared_never_contains_private_unless_shared(self, world):
        store, _, router = world
        shared_texts = " ".join(f.content for f in store.facts(store.shared_context_id()))
        assert CANARY_CAM_PRIV not in shared_texts
        assert CANARY_RILEY_PRIV not in shared_texts

    def test_response_stored_only_in_origin_scope(self, world):
        store, ephemerals, router = world
        from tests.world import ALL_DECISIONS as D

        secret_reply = "REPLY-CANARY-x7k2p9 about your locker"
        router.record_exchange(D["PV(cam)"], "what's my code?", secret_reply)
        # Cameron sees it in his next private bundle...
        cam_serialized = serialized_request_for(router, D["PV(cam)"])
        assert "REPLY-CANARY-x7k2p9" in cam_serialized
        # ...nobody else ever does
        for key in ("PV(riley)", "REC(cam)", "REC(riley)", "UNKNOWN"):
            assert "REPLY-CANARY-x7k2p9" not in serialized_request_for(router, D[key])

    def test_recognized_thread_isolated_from_private_history(self, world):
        store, ephemerals, router = world
        from tests.world import ALL_DECISIONS as D

        router.record_exchange(D["REC(cam)"], "session-note SESSCANARY-q1w2", "ok")
        # session note visible to the same under-verified session...
        assert "SESSCANARY-q1w2" in serialized_request_for(router, D["REC(cam)"])
        # ...but never written into Cameron's private context
        cam_ctx = store.private_context_id("cam-id-001")
        stored = " ".join(m.content for m in store.recent_messages(cam_ctx, 100))
        assert "SESSCANARY-q1w2" not in stored
        # and not visible to his verified bundle either (no retroactive merge)
        assert "SESSCANARY-q1w2" not in serialized_request_for(router, D["PV(cam)"])
