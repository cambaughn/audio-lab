"""Write-path matrix: 'remember X' under every decision tier."""

import pytest

from audio_lab.conversation.ephemeral import GUEST_KEY
from audio_lab.conversation.router import detect_remember
from audio_lab.conversation.types import RememberOutcome
from tests.world import ALL_DECISIONS, CAM_ID, make_world

FACT = "WRITE-CANARY-mm93kd is my locker code"


@pytest.fixture()
def world(tmp_path):
    store, ephemerals, router = make_world(tmp_path)
    yield store, ephemerals, router
    store.close()


def all_persisted_text(store) -> str:
    parts = []
    for ctx in (
        store.private_context_id(CAM_ID),
        store.private_context_id("riley-id-002"),
        store.shared_context_id(),
    ):
        parts += [f.content for f in store.facts(ctx)]
        parts += [m.content for m in store.recent_messages(ctx, 1000)]
    return " ".join(parts)


class TestRememberDetection:
    @pytest.mark.parametrize(
        "transcript,expected",
        [
            ("Remember my locker code is 4417", "my locker code is 4417"),
            ("remember, the door sticks", "the door sticks"),
            ("REMEMBER: buy milk.", "buy milk"),
            ("  remember   spaced out fact  ", "spaced out fact"),
            ("Do you remember me?", None),  # not a leading trigger
            ("remembering things is hard", None),  # word-boundary guard
            ("remember", None),  # no fact body
            ("what's my code?", None),
        ],
    )
    def test_detection(self, transcript, expected):
        assert detect_remember(transcript) == expected


class TestWriteMatrix:
    def test_private_verified_persists(self, world):
        store, _, router = world
        outcome = router.handle_remember(ALL_DECISIONS["PV(cam)"], FACT)
        assert outcome is RememberOutcome.SAVED_PRIVATE
        cam_facts = [f.content for f in store.facts(store.private_context_id(CAM_ID))]
        assert FACT in cam_facts

    @pytest.mark.parametrize("decision_key", ["REC(cam)", "REC(riley)", "UNKNOWN"])
    def test_unverified_never_touches_sqlite(self, world, decision_key):
        store, ephemerals, router = world
        before = all_persisted_text(store)
        outcome = router.handle_remember(ALL_DECISIONS[decision_key], FACT)
        assert outcome is RememberOutcome.SESSION_ONLY
        assert FACT not in all_persisted_text(store)
        assert all_persisted_text(store) == before  # byte-identical store
        # ...but it lives in that session's fact list
        key = (
            ALL_DECISIONS[decision_key].identity_id
            if decision_key != "UNKNOWN"
            else GUEST_KEY
        )
        assert FACT in ephemerals.session_for(key).facts

    def test_session_fact_dies_with_session(self, world):
        store, ephemerals, router = world
        router.handle_remember(ALL_DECISIONS["REC(cam)"], FACT)
        ephemerals.clear_all()
        bundle = router.route(ALL_DECISIONS["REC(cam)"], "what do you know?")
        assert FACT not in " ".join(bundle.facts)

    def test_unverified_exchange_never_touches_sqlite(self, world):
        store, _, router = world
        before = all_persisted_text(store)
        for key in ("REC(cam)", "UNKNOWN"):
            router.record_exchange(ALL_DECISIONS[key], "hello EXCH-CANARY", "hi")
        assert "EXCH-CANARY" not in all_persisted_text(store)
        assert all_persisted_text(store) == before
