"""ConversationStore — persistence for contexts, messages, and facts.

Same discipline as the identity store (Identity Lab pattern): versioned
migrations, typed errors, secure_delete, quick_check, reset + VACUUM, one
internal lock. Lives in its own file (conversations.db) beside
speakers.db; speaker_id values are soft cross-file references.

Only PRIVATE and SHARED contexts exist here — EPHEMERAL context is
in-memory by design (conversation/ephemeral.py) and never touches SQLite.
"""

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from audio_lab.conversation.types import ContextScope, Fact, StoredMessage

SCHEMA_VERSION = 1

DEFAULT_DB_FILENAME = "conversations.db"

_MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE contexts (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL CHECK (scope IN ('PRIVATE','SHARED')),
            speaker_id TEXT,
            created_at TEXT NOT NULL,
            CHECK ((scope = 'PRIVATE') = (speaker_id IS NOT NULL))
        )
        """,
        """
        CREATE UNIQUE INDEX idx_contexts_unique
            ON contexts (scope, ifnull(speaker_id, ''))
        """,
        """
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            context_id TEXT NOT NULL REFERENCES contexts(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user','assistant')),
            content TEXT NOT NULL,
            speaker_id TEXT,
            decision TEXT,
            similarity REAL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_messages_context ON messages (context_id)",
        """
        CREATE TABLE facts (
            id TEXT PRIMARY KEY,
            context_id TEXT NOT NULL REFERENCES contexts(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_by_speaker_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_facts_context ON facts (context_id)",
    ],
}


class ConversationStoreError(Exception):
    """Base class for conversation-storage failures."""


class ConversationUnavailableError(ConversationStoreError):
    """The database cannot be opened or the store is closed."""


class ConversationCorruptedError(ConversationStoreError):
    """The file is not a readable SQLite database or failed quick_check."""


class ConversationSchemaError(ConversationStoreError):
    """The schema version is newer than this code supports."""


class FactNotFoundError(ConversationStoreError):
    """No fact exists with the given id."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        except (OSError, sqlite3.OperationalError) as exc:
            raise ConversationUnavailableError(
                f"cannot open database at {self._path}: {exc}"
            ) from exc
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA secure_delete = ON")
            check = self._conn.execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise ConversationCorruptedError(
                    f"integrity check failed for {self._path}: {check}"
                )
        except sqlite3.OperationalError as exc:
            raise ConversationUnavailableError(
                f"cannot access database at {self._path}: {exc}"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise ConversationCorruptedError(
                f"{self._path} is not a valid SQLite database: {exc}"
            ) from exc
        self._migrate()

    # -- lifecycle --

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> "ConversationStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise ConversationUnavailableError("store is closed")

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            row = self._conn.execute(
                "SELECT MAX(version) AS v FROM schema_migrations"
            ).fetchone()
            current = row["v"] or 0
            if current > SCHEMA_VERSION:
                raise ConversationSchemaError(
                    f"database schema version {current} is newer than the "
                    f"latest supported version {SCHEMA_VERSION}"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in _MIGRATIONS[version]:
                    self._conn.execute(statement)
                self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, ?)",
                    (version, _now_iso()),
                )

    # -- contexts --

    def private_context_id(self, speaker_id: str) -> str:
        """The speaker's private context, created on first use."""
        if not speaker_id:
            raise ValueError("speaker_id must be non-empty")
        return self._ensure_context(ContextScope.PRIVATE.value, speaker_id)

    def shared_context_id(self) -> str:
        """The single household shared context, created on first use."""
        return self._ensure_context("SHARED", None)

    def _ensure_context(self, scope: str, speaker_id: str | None) -> str:
        with self._lock:
            self._require_open()
            row = self._conn.execute(
                "SELECT id FROM contexts WHERE scope = ? "
                "AND ifnull(speaker_id,'') = ifnull(?, '')",
                (scope, speaker_id),
            ).fetchone()
            if row is not None:
                return row["id"]
            context_id = uuid.uuid4().hex
            with self._conn:
                self._conn.execute(
                    "INSERT INTO contexts (id, scope, speaker_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (context_id, scope, speaker_id, _now_iso()),
                )
            return context_id

    # -- messages --

    def add_message(
        self,
        context_id: str,
        role: str,
        content: str,
        speaker_id: str | None = None,
        decision: str | None = None,
        similarity: float | None = None,
    ) -> StoredMessage:
        message_id = uuid.uuid4().hex
        created_at = _now_iso()
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute(
                    "INSERT INTO messages (id, context_id, role, content, "
                    "speaker_id, decision, similarity, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (message_id, context_id, role, content, speaker_id,
                     decision, similarity, created_at),
                )
        return StoredMessage(
            message_id=message_id,
            context_id=context_id,
            role=role,
            content=content,
            speaker_id=speaker_id,
            decision=decision,
            similarity=similarity,
            created_at=datetime.fromisoformat(created_at),
        )

    def recent_messages(self, context_id: str, limit: int = 20) -> list[StoredMessage]:
        """The last `limit` messages in chronological order."""
        with self._lock:
            self._require_open()
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE context_id = ? "
                "ORDER BY rowid DESC LIMIT ?",
                (context_id, limit),
            ).fetchall()
        return [self._row_to_message(r) for r in reversed(rows)]

    # -- facts --

    def add_fact(
        self, context_id: str, content: str, created_by_speaker_id: str
    ) -> Fact:
        fact_id = uuid.uuid4().hex
        created_at = _now_iso()
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute(
                    "INSERT INTO facts (id, context_id, content, "
                    "created_by_speaker_id, created_at) VALUES (?, ?, ?, ?, ?)",
                    (fact_id, context_id, content, created_by_speaker_id, created_at),
                )
        return Fact(
            fact_id=fact_id,
            context_id=context_id,
            content=content,
            created_by_speaker_id=created_by_speaker_id,
            created_at=datetime.fromisoformat(created_at),
        )

    def facts(self, context_id: str) -> list[Fact]:
        with self._lock:
            self._require_open()
            rows = self._conn.execute(
                "SELECT * FROM facts WHERE context_id = ? ORDER BY rowid",
                (context_id,),
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def share_fact(self, fact_id: str) -> Fact:
        """Copy exactly one fact into the shared context (deliberate UI
        action — the only way anything becomes SHARED). The original
        private fact is untouched."""
        with self._lock:
            self._require_open()
            row = self._conn.execute(
                "SELECT * FROM facts WHERE id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                raise FactNotFoundError(f"no fact with id {fact_id!r}")
        return self.add_fact(
            self.shared_context_id(), row["content"], row["created_by_speaker_id"]
        )

    def delete_fact(self, fact_id: str) -> None:
        with self._lock:
            self._require_open()
            with self._conn:
                cur = self._conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            if cur.rowcount == 0:
                raise FactNotFoundError(f"no fact with id {fact_id!r}")

    # -- deletion surface --

    def delete_speaker_data(self, speaker_id: str) -> None:
        """Delete the speaker's private context (messages and facts cascade).
        Facts they explicitly shared remain — sharing was deliberate."""
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute(
                    "DELETE FROM contexts WHERE scope = 'PRIVATE' AND speaker_id = ?",
                    (speaker_id,),
                )

    def delete_all(self) -> None:
        """Delete every context, message, and fact; VACUUM the file."""
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute("DELETE FROM contexts")
            self._conn.execute("VACUUM")

    # -- internals --

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> StoredMessage:
        return StoredMessage(
            message_id=row["id"],
            context_id=row["context_id"],
            role=row["role"],
            content=row["content"],
            speaker_id=row["speaker_id"],
            decision=row["decision"],
            similarity=row["similarity"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            fact_id=row["id"],
            context_id=row["context_id"],
            content=row["content"],
            created_by_speaker_id=row["created_by_speaker_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
