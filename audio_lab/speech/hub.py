"""Offline-first model loading.

Both speech models are cached locally after their first download, but
their loaders revalidate against the Hugging Face hub by default — and a
rate-limited or unreachable hub turned a 3-second cached load into a
multi-minute stall (docs/environment.md, CP8). Audio Lab's contract is
that everything except the LLM call works without a network, so cached
loads must too: try fully offline first, fall back to online only when
the cache is incomplete (first-ever run).
"""

import os

_VAR = "HF_HUB_OFFLINE"


def _set_offline(value: str | None) -> None:
    if value is None:
        os.environ.pop(_VAR, None)
    else:
        os.environ[_VAR] = value


def load_offline_first(load_fn):
    """Run load_fn with HF offline mode forced; retry online on failure."""
    previous = os.environ.get(_VAR)
    _set_offline("1")
    try:
        return load_fn()
    except Exception:
        _set_offline(previous)
        return load_fn()  # cache incomplete — go online for the download
    finally:
        _set_offline(previous)
