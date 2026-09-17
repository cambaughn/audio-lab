"""Speech-model smoke test — dependencies, downloads, load, and timing.

Run once per environment:
    .venv/bin/python scripts/model_check.py

Downloads the ECAPA (~85 MB) and distil-small.en Whisper (~330 MB) models
on first run, then reports load and per-clip timings. No microphone
needed — embeds a synthetic clip and transcribes `say`-generated speech
(synthetic TTS audio, not a person's voice, so writing it to a temp file
breaks no privacy boundary).
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

    # -- speech-to-text --
    import subprocess
    import tempfile
    import wave

    from audio_lab.speech.transcriber import MODEL_NAME, Transcriber

    transcriber = Transcriber()
    print(f"\nSTT model: {MODEL_NAME} (downloads ~330 MB on first ever run)...")
    t4 = time.monotonic()
    try:
        transcriber.load()
    except Exception as exc:
        print(f"STT MODEL FAILED: {exc}")
        return 1
    print(f"STT load: {time.monotonic() - t4:.1f}s")

    spoken = "The quick onyx goblin jumps over the lazy dwarf"
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = f"{tmp}/synthetic.wav"
        subprocess.run(
            ["say", "-o", wav_path, "--data-format=LEI16@16000", spoken],
            check=True,
        )
        with wave.open(wav_path) as wav:
            frames = wav.readframes(wav.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    speech_clip = make_clip(samples)
    for label in ("first", "warm"):
        t5 = time.monotonic()
        text = transcriber.transcribe(speech_clip)
        stt_ms = (time.monotonic() - t5) * 1000
        rtf = stt_ms / 1000.0 / speech_clip.duration_s
        print(
            f"{label} transcription of {speech_clip.duration_s:.1f}s speech: "
            f"{stt_ms:.0f} ms (RTF {rtf:.2f}) -> {text!r}"
        )
    missing = [w for w in ("quick", "goblin", "lazy") if w not in text.lower()]
    if missing:
        print(f"WARNING: expected words missing from transcript: {missing}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
