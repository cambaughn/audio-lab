"""ConversationStore: contexts, messages, facts, deletion, hostile files."""

import pytest

from audio_lab.conversation.store import (
    ConversationCorruptedError,
    ConversationSchemaError,
    ConversationStore,
    ConversationUnavailableError,
    FactNotFoundError,
)


@pytest.fixture()
def store(tmp_path):
    s = ConversationStore(tmp_path / "conversations.db")
    yield s
    s.close()


class TestContexts:
    def test_private_context_stable_per_speaker(self, store):
        a = store.private_context_id("cam")
        assert store.private_context_id("cam") == a
        assert store.private_context_id("riley") != a

    def test_shared_context_is_singleton(self, store):
        assert store.shared_context_id() == store.shared_context_id()

    def test_empty_speaker_rejected(self, store):
        with pytest.raises(ValueError):
            store.private_context_id("")


class TestMessages:
    def test_recent_messages_order_and_limit(self, store):
        ctx = store.private_context_id("cam")
        for i in range(30):
            store.add_message(ctx, "user", f"msg-{i}")
        recent = store.recent_messages(ctx, limit=20)
        assert len(recent) == 20
        assert recent[0].content == "msg-10"  # oldest kept
        assert recent[-1].content == "msg-29"  # newest last (chronological)

    def test_message_metadata_round_trip(self, store):
        ctx = store.private_context_id("cam")
        stored = store.add_message(
            ctx, "user", "hi", speaker_id="cam", decision="PRIVATE_VERIFIED",
            similarity=0.71,
        )
        got = store.recent_messages(ctx)[0]
        assert got == stored
        assert got.similarity == 0.71


class TestFacts:
    def test_add_list_delete(self, store):
        ctx = store.private_context_id("cam")
        fact = store.add_fact(ctx, "locker is 4417", "cam")
        assert [f.content for f in store.facts(ctx)] == ["locker is 4417"]
        store.delete_fact(fact.fact_id)
        assert store.facts(ctx) == []
        with pytest.raises(FactNotFoundError):
            store.delete_fact(fact.fact_id)

    def test_share_missing_fact_errors(self, store):
        with pytest.raises(FactNotFoundError):
            store.share_fact("nope")


class TestDeletion:
    def test_delete_speaker_data_cascades_private_only(self, store):
        cam = store.private_context_id("cam")
        store.add_fact(cam, "private thing", "cam")
        store.add_message(cam, "user", "private msg", speaker_id="cam")
        shared_fact = store.add_fact(store.shared_context_id(), "wifi pw", "cam")
        store.delete_speaker_data("cam")
        # private context is gone; a fresh one comes back empty
        fresh = store.private_context_id("cam")
        assert store.facts(fresh) == [] and store.recent_messages(fresh) == []
        # explicitly shared facts survive (sharing was deliberate)
        assert [f.fact_id for f in store.facts(store.shared_context_id())] == [
            shared_fact.fact_id
        ]

    def test_delete_all(self, store):
        cam = store.private_context_id("cam")
        store.add_fact(cam, "x", "cam")
        store.add_fact(store.shared_context_id(), "y", "cam")
        store.delete_all()
        assert store.facts(store.shared_context_id()) == []
        assert store.facts(store.private_context_id("cam")) == []


class TestHostileFiles:
    def test_garbage_file(self, tmp_path):
        path = tmp_path / "garbage.db"
        path.write_bytes(b"not sqlite" * 500)
        with pytest.raises(ConversationCorruptedError):
            ConversationStore(path)

    def test_future_schema_refused(self, tmp_path):
        import sqlite3

        path = tmp_path / "future.db"
        ConversationStore(path).close()
        raw = sqlite3.connect(path)
        raw.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (99, 'x')"
        )
        raw.commit()
        raw.close()
        with pytest.raises(ConversationSchemaError):
            ConversationStore(path)

    def test_closed_store_refuses(self, store):
        store.close()
        with pytest.raises(ConversationUnavailableError):
            store.shared_context_id()

    def test_persistence_across_reopen(self, tmp_path):
        with ConversationStore(tmp_path / "c.db") as s:
            ctx = s.private_context_id("cam")
            s.add_fact(ctx, "persists", "cam")
        with ConversationStore(tmp_path / "c.db") as s:
            assert [f.content for f in s.facts(s.private_context_id("cam"))] == [
                "persists"
            ]
