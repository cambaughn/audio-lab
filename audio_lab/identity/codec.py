"""Embedding blob codec — the single place embeddings become bytes.

Binary format (documented for future readers; also see docs/storage.md):

- dtype: IEEE-754 float32 (4 bytes per element)
- byte order: little-endian, always — written as numpy '<f4' regardless of
  platform endianness
- layout: one C-contiguous 1-D vector, no header, no padding; blob length
  is exactly dim * 4 bytes, with dim stored alongside the blob in its own
  database column
- dimensionality: whatever the producing model emits (192 for the
  speechbrain/spkrec-ecapa-voxceleb speaker model)
- normalization: ECAPA embeddings are stored as produced (NOT unit
  normalized) — consumers must normalize before computing
  cosine similarity if they cannot guarantee provenance.
- model identifier: stored alongside each blob
  (e.g. "speechbrain/spkrec-ecapa-voxceleb").
  Embeddings from different model ids are NOT comparable and must never
  be mixed in similarity computations.
"""

import numpy as np

from audio_lab.identity.errors import MalformedEmbeddingError

DTYPE_NAME = "float32"
_LE_FLOAT32 = np.dtype("<f4")


def encode_embedding(embedding: np.ndarray) -> tuple[bytes, int]:
    """Validate and serialize an embedding. Returns (blob, dim).

    Requirements: numpy array, 1-D, float32, at least one element, all
    values finite. Anything else raises MalformedEmbeddingError.
    """
    if not isinstance(embedding, np.ndarray):
        raise MalformedEmbeddingError(
            f"embedding must be a numpy array, got {type(embedding).__name__}"
        )
    if embedding.ndim != 1:
        raise MalformedEmbeddingError(
            f"embedding must be 1-D, got shape {embedding.shape}"
        )
    if embedding.size == 0:
        raise MalformedEmbeddingError("embedding is empty")
    if embedding.dtype != np.float32:
        raise MalformedEmbeddingError(
            f"embedding dtype must be float32, got {embedding.dtype}"
        )
    if not np.all(np.isfinite(embedding)):
        raise MalformedEmbeddingError("embedding contains NaN or infinite values")
    blob = np.ascontiguousarray(embedding, dtype=_LE_FLOAT32).tobytes()
    return blob, int(embedding.size)


def decode_embedding(blob: bytes, dim: int, dtype: str) -> np.ndarray:
    """Deserialize a stored blob back into a float32 vector.

    Validates the declared dtype, the blob length against dim, and value
    finiteness. Returns a writable copy owned by the caller.
    """
    if dtype != DTYPE_NAME:
        raise MalformedEmbeddingError(
            f"stored dtype {dtype!r} is not supported (expected {DTYPE_NAME!r})"
        )
    if not isinstance(dim, int) or dim <= 0:
        raise MalformedEmbeddingError(f"stored dim {dim!r} is not a positive integer")
    expected_len = dim * _LE_FLOAT32.itemsize
    if not isinstance(blob, (bytes, bytearray)) or len(blob) != expected_len:
        actual = len(blob) if isinstance(blob, (bytes, bytearray)) else type(blob).__name__
        raise MalformedEmbeddingError(
            f"blob length {actual} does not match dim {dim} ({expected_len} bytes)"
        )
    vec = np.frombuffer(blob, dtype=_LE_FLOAT32).astype(np.float32, copy=True)
    if not np.all(np.isfinite(vec)):
        raise MalformedEmbeddingError("stored embedding contains NaN or infinite values")
    return vec
