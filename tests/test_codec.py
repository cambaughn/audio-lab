"""Embedding codec: round-trip fidelity and hostile inputs."""

import numpy as np
import pytest

from audio_lab.identity.codec import DTYPE_NAME, decode_embedding, encode_embedding
from audio_lab.identity.errors import MalformedEmbeddingError


def vec(dim: int = 192, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(dim).astype(np.float32)


class TestRoundTrip:
    def test_exact_round_trip(self):
        v = vec()
        blob, dim = encode_embedding(v)
        assert dim == 192 and len(blob) == 192 * 4
        out = decode_embedding(blob, dim, DTYPE_NAME)
        assert np.array_equal(out, v)
        assert out.flags.writeable

    def test_little_endian_on_disk(self):
        v = np.array([1.0], dtype=np.float32)
        blob, _ = encode_embedding(v)
        assert blob == b"\x00\x00\x80\x3f"  # IEEE-754 LE 1.0


class TestEncodeRejects:
    @pytest.mark.parametrize(
        "bad",
        [
            [1.0, 2.0],  # not ndarray
            np.zeros((2, 2), dtype=np.float32),  # not 1-D
            np.zeros(0, dtype=np.float32),  # empty
            np.zeros(4, dtype=np.float64),  # wrong dtype
            np.array([1.0, np.nan], dtype=np.float32),  # non-finite
            np.array([1.0, np.inf], dtype=np.float32),
        ],
    )
    def test_rejects(self, bad):
        with pytest.raises(MalformedEmbeddingError):
            encode_embedding(bad)


class TestDecodeRejects:
    def test_wrong_dtype_name(self):
        blob, dim = encode_embedding(vec())
        with pytest.raises(MalformedEmbeddingError):
            decode_embedding(blob, dim, "float64")

    def test_truncated_blob(self):
        blob, dim = encode_embedding(vec())
        with pytest.raises(MalformedEmbeddingError):
            decode_embedding(blob[:-4], dim, DTYPE_NAME)

    def test_dim_mismatch(self):
        blob, _ = encode_embedding(vec())
        with pytest.raises(MalformedEmbeddingError):
            decode_embedding(blob, 100, DTYPE_NAME)

    def test_bad_dim_values(self):
        blob, dim = encode_embedding(vec())
        for bad_dim in (0, -1, "192"):
            with pytest.raises(MalformedEmbeddingError):
                decode_embedding(blob, bad_dim, DTYPE_NAME)

    def test_nonfinite_stored_bytes(self):
        bad = np.array([np.nan], dtype="<f4").tobytes()
        with pytest.raises(MalformedEmbeddingError):
            decode_embedding(bad, 1, DTYPE_NAME)
