"""IdentityStore — the canonical persistence layer for enrolled identities
and their voice-embedding samples.

Ported from Identity Lab v0.1.0 (thumbnails dropped; samples carry the
utterance duration). Repository-pattern API over a local SQLite file; no
SQLite types or SQL leak past this module. No Qt, no audio, no model
dependencies.

Guarantees:
- explicit, versioned migrations (schema_migrations table)
- typed exceptions for every distinguishable failure (see errors.py)
- embeddings stored via the documented codec (see codec.py / docs/storage.md)
- per-identity consistency: all samples of one identity share model_id + dim
- thread-safe: a single internal lock serializes all operations
- privacy: secure_delete is enabled so deleted embeddings are overwritten,
  and reset_database() VACUUMs the file afterwards
"""

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from audio_lab.identity import codec
from audio_lab.identity.errors import (
    CorruptedDatabaseError,
    DatabaseUnavailableError,
    DuplicateIdentityError,
    IdentityNotFoundError,
    ModelMismatchError,
    SchemaMismatchError,
)
from audio_lab.identity.types import (
    ENROLLMENT_VERSION,
    EmbeddingSample,
    IdentityRecord,
)

SCHEMA_VERSION = 1

DEFAULT_DB_FILENAME = "speakers.db"

# Migration statements by version, applied in order inside one transaction
# each. Never edit an existing migration — add a new version.
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE identities (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            enrollment_version INTEGER NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX idx_identities_name
            ON identities (lower(display_name))
        """,
        """
        CREATE TABLE voice_samples (
            id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL
                REFERENCES identities(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            dim INTEGER NOT NULL,
            dtype TEXT NOT NULL,
            model_id TEXT NOT NULL,
            duration_s REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX idx_samples_identity
            ON voice_samples (identity_id)
        """,
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IdentityStore:
    """Persistent store for identities and their voice-embedding samples."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        except (OSError, sqlite3.OperationalError) as exc:
            raise DatabaseUnavailableError(
                f"cannot open database at {self._path}: {exc}"
            ) from exc
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA secure_delete = ON")
            check = self._conn.execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise CorruptedDatabaseError(
                    f"integrity check failed for {self._path}: {check}"
                )
        except sqlite3.OperationalError as exc:
            raise DatabaseUnavailableError(
                f"cannot access database at {self._path}: {exc}"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise CorruptedDatabaseError(
                f"{self._path} is not a valid SQLite database: {exc}"
            ) from exc
        self._migrate()

    # -- lifecycle --

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> "IdentityStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise DatabaseUnavailableError("store is closed")

    # -- migrations --

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = self._conn.execute(
                "SELECT MAX(version) AS v FROM schema_migrations"
            ).fetchone()
            current = row["v"] or 0
            if current > SCHEMA_VERSION:
                raise SchemaMismatchError(
                    f"database schema version {current} is newer than the "
                    f"latest supported version {SCHEMA_VERSION} — refusing "
                    "to touch it (was this file written by a newer build?)"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in _MIGRATIONS[version]:
                    self._conn.execute(statement)
                self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, ?)",
                    (version, _now_iso()),
                )

    # -- identity CRUD --

    def create_identity(
        self, display_name: str, enrollment_version: int = ENROLLMENT_VERSION
    ) -> IdentityRecord:
        name = display_name.strip()
        if not name:
            raise ValueError("display_name must not be empty")
        identity_id = uuid.uuid4().hex
        created_at = _now_iso()
        with self._lock:
            self._require_open()
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO identities "
                        "(id, display_name, created_at, enrollment_version) "
                        "VALUES (?, ?, ?, ?)",
                        (identity_id, name, created_at, enrollment_version),
                    )
            except sqlite3.IntegrityError as exc:
                raise DuplicateIdentityError(
                    f"an identity named {name!r} already exists"
                ) from exc
        return self.get_identity(identity_id)

    def get_identity(self, identity_id: str) -> IdentityRecord:
        with self._lock:
            self._require_open()
            row = self._conn.execute(
                self._IDENTITY_QUERY + " WHERE i.id = ? GROUP BY i.id",
                (identity_id,),
            ).fetchone()
        if row is None:
            raise IdentityNotFoundError(f"no identity with id {identity_id!r}")
        return self._row_to_identity(row)

    def list_identities(self) -> list[IdentityRecord]:
        with self._lock:
            self._require_open()
            rows = self._conn.execute(
                self._IDENTITY_QUERY + " GROUP BY i.id ORDER BY i.created_at, i.rowid"
            ).fetchall()
        return [self._row_to_identity(r) for r in rows]

    def rename_identity(self, identity_id: str, new_name: str) -> IdentityRecord:
        name = new_name.strip()
        if not name:
            raise ValueError("display_name must not be empty")
        with self._lock:
            self._require_open()
            try:
                with self._conn:
                    cur = self._conn.execute(
                        "UPDATE identities SET display_name = ? WHERE id = ?",
                        (name, identity_id),
                    )
            except sqlite3.IntegrityError as exc:
                raise DuplicateIdentityError(
                    f"an identity named {name!r} already exists"
                ) from exc
            if cur.rowcount == 0:
                raise IdentityNotFoundError(f"no identity with id {identity_id!r}")
        return self.get_identity(identity_id)

    def delete_identity(self, identity_id: str) -> None:
        with self._lock:
            self._require_open()
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM identities WHERE id = ?", (identity_id,)
                )
            if cur.rowcount == 0:
                raise IdentityNotFoundError(f"no identity with id {identity_id!r}")

    # -- voice samples --

    def add_embedding_sample(
        self,
        identity_id: str,
        embedding: np.ndarray,
        model_id: str,
        duration_s: float,
    ) -> EmbeddingSample:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        if not isinstance(duration_s, (int, float)) or duration_s <= 0:
            raise ValueError("duration_s must be a positive number")
        model_id = model_id.strip()
        blob, dim = codec.encode_embedding(embedding)
        sample_id = uuid.uuid4().hex
        created_at = _now_iso()
        with self._lock:
            self._require_open()
            self._assert_identity_exists(identity_id)
            existing = self._conn.execute(
                "SELECT dim, model_id FROM voice_samples "
                "WHERE identity_id = ? LIMIT 1",
                (identity_id,),
            ).fetchone()
            if existing is not None and (
                existing["dim"] != dim or existing["model_id"] != model_id
            ):
                raise ModelMismatchError(
                    f"identity {identity_id!r} already has samples from model "
                    f"{existing['model_id']!r} (dim {existing['dim']}); refusing "
                    f"incompatible sample from model {model_id!r} (dim {dim})"
                )
            with self._conn:
                self._conn.execute(
                    "INSERT INTO voice_samples "
                    "(id, identity_id, embedding, dim, dtype, model_id, "
                    "duration_s, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sample_id,
                        identity_id,
                        blob,
                        dim,
                        codec.DTYPE_NAME,
                        model_id,
                        float(duration_s),
                        created_at,
                    ),
                )
        return EmbeddingSample(
            sample_id=sample_id,
            identity_id=identity_id,
            embedding=codec.decode_embedding(blob, dim, codec.DTYPE_NAME),
            dim=dim,
            dtype=codec.DTYPE_NAME,
            model_id=model_id,
            duration_s=float(duration_s),
            created_at=datetime.fromisoformat(created_at),
        )

    def get_embedding_samples(self, identity_id: str) -> list[EmbeddingSample]:
        """All samples for an identity, in insertion order.

        Raises MalformedEmbeddingError if any stored blob fails validation —
        corrupted data is reported, never silently skipped.
        """
        with self._lock:
            self._require_open()
            self._assert_identity_exists(identity_id)
            rows = self._conn.execute(
                "SELECT * FROM voice_samples WHERE identity_id = ? "
                "ORDER BY rowid",
                (identity_id,),
            ).fetchall()
        return [
            EmbeddingSample(
                sample_id=r["id"],
                identity_id=r["identity_id"],
                embedding=codec.decode_embedding(r["embedding"], r["dim"], r["dtype"]),
                dim=r["dim"],
                dtype=r["dtype"],
                model_id=r["model_id"],
                duration_s=r["duration_s"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # -- maintenance --

    def reset_database(self) -> None:
        """Delete every identity and sample. Keeps schema and file. VACUUMs
        so deleted biometric data does not linger in free pages."""
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute("DELETE FROM voice_samples")
                self._conn.execute("DELETE FROM identities")
            self._conn.execute("VACUUM")

    # -- internals --

    _IDENTITY_QUERY = """
        SELECT i.id, i.display_name, i.created_at, i.enrollment_version,
               COUNT(s.id) AS sample_count,
               MIN(s.model_id) AS model_id,
               MIN(s.dim) AS dim
        FROM identities i
        LEFT JOIN voice_samples s ON s.identity_id = i.id
    """

    def _assert_identity_exists(self, identity_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM identities WHERE id = ?", (identity_id,)
        ).fetchone()
        if row is None:
            raise IdentityNotFoundError(f"no identity with id {identity_id!r}")

    @staticmethod
    def _row_to_identity(row: sqlite3.Row) -> IdentityRecord:
        return IdentityRecord(
            identity_id=row["id"],
            display_name=row["display_name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            enrollment_version=row["enrollment_version"],
            sample_count=row["sample_count"],
            model_id=row["model_id"],
            dim=row["dim"],
        )
