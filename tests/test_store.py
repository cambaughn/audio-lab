"""IdentityStore: CRUD, consistency guards, hostile data, lifecycle.

This layer must be the most reliable part of the project — tests bias
toward edge cases and hostile data. No audio, no models, no Qt.
"""

import sqlite3

import numpy as np
import pytest

from audio_lab.identity.errors import (
    CorruptedDatabaseError,
    DatabaseUnavailableError,
    DuplicateIdentityError,
    IdentityNotFoundError,
    MalformedEmbeddingError,
    ModelMismatchError,
    SchemaMismatchError,
)
from audio_lab.identity.store import SCHEMA_VERSION, IdentityStore

MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def vec(seed: int = 0, dim: int = 192) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(dim).astype(np.float32)


@pytest.fixture()
def store(tmp_path):
    s = IdentityStore(tmp_path / "speakers.db")
    yield s
    s.close()


class TestIdentityCrud:
    def test_create_and_get(self, store):
        rec = store.create_identity("Cameron")
        assert rec.display_name == "Cameron"
        assert rec.sample_count == 0 and rec.model_id is None
        assert store.get_identity(rec.identity_id) == rec

    def test_duplicate_name_case_insensitive(self, store):
        store.create_identity("Cameron")
        with pytest.raises(DuplicateIdentityError):
            store.create_identity("cameron")

    def test_empty_name_rejected(self, store):
        with pytest.raises(ValueError):
            store.create_identity("   ")

    def test_rename(self, store):
        rec = store.create_identity("Cameron")
        renamed = store.rename_identity(rec.identity_id, "Cam")
        assert renamed.display_name == "Cam"

    def test_rename_to_existing_rejected(self, store):
        store.create_identity("Cameron")
        rec = store.create_identity("Riley")
        with pytest.raises(DuplicateIdentityError):
            store.rename_identity(rec.identity_id, "CAMERON")

    def test_delete_cascades_samples(self, store):
        rec = store.create_identity("Cameron")
        store.add_embedding_sample(rec.identity_id, vec(), MODEL, 3.0)
        store.delete_identity(rec.identity_id)
        with pytest.raises(IdentityNotFoundError):
            store.get_embedding_samples(rec.identity_id)

    def test_missing_identity_errors(self, store):
        for op in (
            lambda: store.get_identity("nope"),
            lambda: store.rename_identity("nope", "X"),
            lambda: store.delete_identity("nope"),
            lambda: store.get_embedding_samples("nope"),
            lambda: store.add_embedding_sample("nope", vec(), MODEL, 3.0),
        ):
            with pytest.raises(IdentityNotFoundError):
                op()


class TestSamples:
    def test_add_and_get_round_trip(self, store):
        rec = store.create_identity("Cameron")
        sample = store.add_embedding_sample(rec.identity_id, vec(1), MODEL, 2.5)
        assert sample.duration_s == 2.5 and sample.dim == 192
        got = store.get_embedding_samples(rec.identity_id)
        assert len(got) == 1
        assert np.array_equal(got[0].embedding, vec(1))
        assert store.get_identity(rec.identity_id).sample_count == 1
        assert store.get_identity(rec.identity_id).model_id == MODEL

    def test_model_mismatch_rejected(self, store):
        rec = store.create_identity("Cameron")
        store.add_embedding_sample(rec.identity_id, vec(), MODEL, 3.0)
        with pytest.raises(ModelMismatchError):
            store.add_embedding_sample(rec.identity_id, vec(), "other-model", 3.0)

    def test_dim_mismatch_rejected(self, store):
        rec = store.create_identity("Cameron")
        store.add_embedding_sample(rec.identity_id, vec(), MODEL, 3.0)
        with pytest.raises(ModelMismatchError):
            store.add_embedding_sample(rec.identity_id, vec(dim=100), MODEL, 3.0)

    def test_bad_duration_rejected(self, store):
        rec = store.create_identity("Cameron")
        for bad in (0, -1.0, "3"):
            with pytest.raises(ValueError):
                store.add_embedding_sample(rec.identity_id, vec(), MODEL, bad)

    def test_malformed_embedding_rejected(self, store):
        rec = store.create_identity("Cameron")
        with pytest.raises(MalformedEmbeddingError):
            store.add_embedding_sample(
                rec.identity_id, np.zeros(4, dtype=np.float64), MODEL, 3.0
            )

    def test_corrupted_blob_reported_on_read(self, store, tmp_path):
        rec = store.create_identity("Cameron")
        store.add_embedding_sample(rec.identity_id, vec(), MODEL, 3.0)
        # vandalize the blob behind the store's back
        raw = sqlite3.connect(tmp_path / "speakers.db")
        raw.execute("UPDATE voice_samples SET embedding = X'0102'")
        raw.commit()
        raw.close()
        with pytest.raises(MalformedEmbeddingError):
            store.get_embedding_samples(rec.identity_id)


class TestLifecycleAndHostileFiles:
    def test_closed_store_refuses(self, store):
        store.close()
        with pytest.raises(DatabaseUnavailableError):
            store.list_identities()

    def test_persistence_across_reopen(self, tmp_path):
        with IdentityStore(tmp_path / "s.db") as s:
            rec = s.create_identity("Cameron")
            s.add_embedding_sample(rec.identity_id, vec(), MODEL, 3.0)
        with IdentityStore(tmp_path / "s.db") as s:
            records = s.list_identities()
            assert len(records) == 1 and records[0].sample_count == 1

    def test_garbage_file_is_corrupted_error(self, tmp_path):
        path = tmp_path / "garbage.db"
        path.write_bytes(b"this is not sqlite at all" * 100)
        with pytest.raises(CorruptedDatabaseError):
            IdentityStore(path)

    def test_future_schema_refused(self, tmp_path):
        path = tmp_path / "future.db"
        with IdentityStore(path) as s:
            pass
        raw = sqlite3.connect(path)
        raw.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION + 1, "2999-01-01"),
        )
        raw.commit()
        raw.close()
        with pytest.raises(SchemaMismatchError):
            IdentityStore(path)

    def test_path_is_directory_unavailable(self, tmp_path):
        with pytest.raises(DatabaseUnavailableError):
            IdentityStore(tmp_path)  # a directory, not a file

    def test_reset_database(self, store):
        rec = store.create_identity("Cameron")
        store.add_embedding_sample(rec.identity_id, vec(), MODEL, 3.0)
        store.reset_database()
        assert store.list_identities() == []
        # store remains usable
        store.create_identity("Riley")
