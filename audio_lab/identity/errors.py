"""Typed exceptions for the identity storage layer.

Each failure mode is distinguishable so callers can react appropriately
(show an error state, offer a reset, refuse a sample) instead of pattern-
matching on message strings.
"""


class IdentityStoreError(Exception):
    """Base class for all identity-storage failures."""


class DatabaseUnavailableError(IdentityStoreError):
    """The database file cannot be opened, created, or accessed
    (missing permissions, path is a directory, store already closed)."""


class CorruptedDatabaseError(IdentityStoreError):
    """The file exists but is not a readable SQLite database, or SQLite's
    integrity check failed."""


class SchemaMismatchError(IdentityStoreError):
    """The database schema version is newer than this code supports, or the
    migration bookkeeping is inconsistent."""


class IdentityNotFoundError(IdentityStoreError):
    """No identity exists with the given id."""


class DuplicateIdentityError(IdentityStoreError):
    """An identity with the same display name (case-insensitive) exists."""


class MalformedEmbeddingError(IdentityStoreError):
    """An embedding is invalid: wrong dtype, wrong shape, non-finite values,
    or a stored blob whose bytes do not match its declared dimension/dtype."""


class ModelMismatchError(IdentityStoreError):
    """A new sample's model id or dimensionality conflicts with the samples
    already stored for that identity — embeddings from different models
    live in different vector spaces and must never be mixed."""
