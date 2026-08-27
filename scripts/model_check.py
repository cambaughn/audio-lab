"""Speaker-model smoke test — dependency, download, load, and timing.

Run once per environment:
    .venv/bin/python scripts/model_check.py

Downloads the ECAPA model on first run (~85 MB into the Hugging Face
cache), then reports load and per-clip embed timings. No microphone
needed — embeds a synthetic clip.
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    t0 = time.monotonic()
    from audio_lab.audio.clip import SAMPLE_RATE, make_clip
    from audio_lab.speech.embedder import EMBEDDING_DIM, MODEL_ID, SpeakerEmbedder

    embedder = SpeakerEmbedder()
    print(f"model: {MODEL_ID}")
    print("loading (downloads ~85 MB on first ever run)...")
    t1 = time.monotonic()
    try:
        embedder.load()
    except Exception as exc:
        print(f"MODEL FAILED: {exc}")
        return 1
    t2 = time.monotonic()
    print(f"import+load: {t2 - t0:.1f}s (load alone {t2 - t1:.1f}s)")

    rng = np.random.default_rng(0)
    fake_speech = (0.1 * rng.standard_normal(3 * SAMPLE_RATE)).astype(np.float32)
    clip = make_clip(fake_speech)
    evidence = embedder.embed(clip)  # first call includes lazy init
    t3 = time.monotonic()
    times = []
    for _ in range(5):
        t = time.monotonic()
        evidence = embedder.embed(clip)
        times.append(time.monotonic() - t)
    assert evidence.embedding is not None and evidence.embedding.size == EMBEDDING_DIM
    print(f"first embed: {t3 - t2:.2f}s; warm embed (3 s clip): {np.mean(times) * 1000:.0f} ms")
    print(f"embedding: dim={evidence.embedding.size} dtype={evidence.embedding.dtype}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
