# Environment and measurement log

Dated, running record of the machine, toolchain, and every measured number
— one section per checkpoint, Identity Lab style.

## Machine (verified 2026-08-06)

- MacBook Air (Mac14,15), Apple M2 — 4 performance + 4 efficiency cores,
  24 GB unified memory
- macOS 13.7.3 Ventura (22H417)
- Audio: "MacBook Air Microphone" (built-in, 1ch, 48 kHz); Bluetooth
  headsets appear as their own devices and may become the system default
  (observed: "Sony Headphones") — the app selects input by real device
  name rather than trusting the default
- Disk before install: 52 GB free on a 95%-full Data volume

## Toolchain

- Python **3.11.14, Homebrew arm64**, at
  `/opt/homebrew/opt/python@3.11/bin/python3.11`
- **PATH hazard**: bare `python3` on this machine is a python.org
  *universal2* 3.11.4 — creating the venv with it risks x86_64 wheels
  under Rosetta. Always use the explicit Homebrew path.
- The macOS-14 wheel cliff (this machine is on macOS 13):
  - `torch` 2.12+ ships `macosx_14_0` wheels only → pinned 2.11.0
  - `av` 16+ ships `macosx_14_0` wheels only → pinned 15.1.0
  - all MLX packages require macOS 14+ → unavailable
  - PySide6 6.11.1 is exactly at the `macosx_13_0` floor

## CP1–CP2 — scaffold and pinned install (2026-08-10)

- `pip install -r requirements.txt` into a fresh venv: **~30 s of wheel
  building failed on first attempt** (av sdist vs. stray Intel-prefix
  ffmpeg headers — see learnings.md Observation 001); after pinning
  `av==15.1.0`, full install completed in **25 s** (warm pip cache).
- Installed venv size: **2.1 GB** (torch alone dominates) — larger than
  the ~800 MB planning estimate; disk after install: **54 GB free**.
- Import sanity check (all arm64): torch 2.11.0, torchaudio 2.11.0,
  numpy 2.4.6, sounddevice 0.5.5 (PortAudio bundled), Qt 6.11.1,
  faster-whisper 1.2.1 (ctranslate2 4.8.1), speechbrain 1.1.0.
  Cold import of the full stack: ~42 s wall (cold disk cache; 4.8 s CPU).
- `scripts/smoke_test.py` on the built-in mic: **16 kHz mono stream opens
  in 141 ms** and captures live signal (quiet-room floor ≈ −54 dBFS) —
  CoreAudio resampling below PortAudio works as planned; no software
  resampler needed.
- **First-start transient**: the very first mic stream this process ever
  opened failed with PortAudio −9986 (AUHAL error during init) and then
  never failed again — the same "first attempt after a fresh permission
  grant fails" behavior Identity Lab documented for the camera. Mitigation
  (CP3): one automatic retry on stream-start failure before declaring
  `MIC ERROR`. Note `check_input_settings()` passed while the actual
  start failed — the check is not a reliable predictor.
