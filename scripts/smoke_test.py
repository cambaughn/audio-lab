"""Microphone smoke test — settles the environment questions once.

Verifies, without any Qt or model code:
  1. input devices enumerate by real system name
  2. a 16 kHz mono float32 stream opens on the chosen device
     (CoreAudio resamples transparently below PortAudio)
  3. one second of audio actually contains signal — an all-zero buffer
     means macOS mic permission was denied to the hosting terminal
     (TCC denial is silent: no error, just digital silence)

Run from the macOS Terminal app so the permission prompt attributes to it:
    .venv/bin/python scripts/smoke_test.py [device-name-substring]

Exit codes: 0 = signal captured, 2 = silence (permission suspected),
1 = stream error.
"""

import sys
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
BLOCKSIZE = 1024  # explicit: macOS artifact bug with blocksize=0
CAPTURE_SECONDS = 1.0


def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else None

    print("Input devices:")
    default_input = sd.query_devices(kind="input")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            marker = " (default)" if dev["name"] == default_input["name"] else ""
            print(f"  [{idx}] {dev['name']}{marker}")

    device = None  # default
    if wanted is not None:
        device = wanted  # sounddevice accepts substring name matching
    name = sd.query_devices(device, kind="input")["name"]
    print(f"\nOpening {SAMPLE_RATE} Hz mono stream on: {name}")

    blocks: list[np.ndarray] = []
    start = time.monotonic()
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCKSIZE,
            device=device,
            callback=lambda indata, frames, t, status: blocks.append(indata.copy()),
        ):
            open_ms = (time.monotonic() - start) * 1000
            print(f"Stream opened in {open_ms:.0f} ms — capturing {CAPTURE_SECONDS:.0f} s...")
            time.sleep(CAPTURE_SECONDS)
    except Exception as exc:  # PortAudio errors are plain exceptions here
        print(f"STREAM ERROR: {exc}")
        return 1

    samples = np.concatenate(blocks).ravel() if blocks else np.zeros(0, dtype="float32")
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    rms_dbfs = 20 * np.log10(rms) if rms > 0 else float("-inf")
    print(f"Captured {samples.size} samples  peak={peak:.4f}  rms={rms_dbfs:.1f} dBFS")

    if samples.size == 0 or peak == 0.0:
        print(
            "ALL-ZERO CAPTURE — MIC PERMISSION SUSPECTED.\n"
            "Grant microphone access to your terminal in System Settings →\n"
            "Privacy & Security → Microphone, then quit and reopen the terminal."
        )
        return 2

    print("OK — live signal captured at 16 kHz.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
