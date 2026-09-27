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

## CP4 gate — real-input level calibration (2026-08-10)

**Gate outcome (2026-08-10): PASSED after five fix rounds** — record →
review confirmed clean and clearly audible by ear once (a) the macOS
input volume was raised from 14% and surfaced in the UI, and (b) playback
moved off PortAudio onto QAudioSink/CoreAudio. Remaining optional check
(TCC revoke → `MIC PERMISSION SUSPECTED`) validated in code and against
real silent capture, not re-run manually.

## v0.1 release verification (2026-09-20)

- Test suite: **236 tests**, all passing, no microphone / models / network
  required (constructor injection throughout); runs in ~2 s.
- Latency budget on the M2 CPU: speaker embed 30–70 ms; STT
  (distil-small.en, int8) ~1.1 s for a 3 s utterance; both models load
  once at launch (ECAPA ~2 s warm, Whisper ~30 s warm — the dominant
  startup cost). End-to-end press-release → spoken reply is dominated by
  STT + LLM network round-trip, comfortably under the target for turn-
  based use.
- Repository privacy audit: full git history contains only source, tests,
  and docs — no databases, audio, models, keys, or settings ever committed
  (72 .py, 8 .md, 1 .txt, 1 .gitignore; largest blob ever 31 KB, a source
  file).
- Real-model gate results (two-person recognition + context isolation) are
  recorded in learnings.md Observations 012–018.

## CP5 — speaker model measurements (2026-08-10)

ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`, CPU): first-ever load
including ~85 MB download **11.9 s**; warm load **1.8 s**; speechbrain
import alone ~5 s cold. Per-clip embed (3 s clip): **29–45 ms** — latency
is a non-issue at this stage. Model files live in the Hugging Face cache
(the app-data `models/` dir holds symlinks).

## CP8 — speech-to-text measurements (2026-09-17)

- distil-small.en (faster-whisper, CPU int8): first-ever download ~330 MB
  — took **87 minutes** on this network due to unauthenticated HF rate
  limiting (one-time; normally minutes).
- Transcription of 3 s of clean synthetic speech: **1.0–1.4 s
  (RTF 0.34–0.47)**, transcript exact. A 5 s utterance ≈ 2–2.5 s STT.
- Embed remains 28–68 ms — STT dominates per-turn latency as planned.
- **Cached loads stalled for minutes when the HF hub was rate-limited**,
  even with all files local (both loaders revalidate online by default;
  first post-download in-app load also paid cold page cache on 330 MB).
  Fix: offline-first loading (`speech/hub.py` forces HF_HUB_OFFLINE for
  the attempt, falls back online only if the cache is incomplete).
  Result: **app start → MODEL READY (both models) = 3.2 s warm**,
  network-independent.

## Batch 2 gate — two-person recognition (2026-09-16): PASSED

- Enrolled: Cameron (6 samples, 2026-08-28), Riley (6 samples,
  2026-09-16), built-in mic.
- Calibration (leave-one-out genuine / cross-speaker impostor):
  genuine n=12 min 0.567 · median 0.662 · max 0.728; impostor n=12
  min 0.020 · median 0.077 · max 0.107. Auto-applied thresholds at this
  point: **recognition 0.34, private 0.52** (private later lowered to
  **0.44** by the live-variance calibration change — Observation 016 —
  which is the shipped v0.1 operating value).
- Live attribution: both speakers correctly named (Cameron 0.63–0.66 on
  sentence-length utterances; duration probe in Observation 011 — ~1 s
  clips score ~0.1 lower, curve saturates by ~3 s).
- Adversarial: `say -v Samantha` / `say -v Alex` played at the mic →
  UNKNOWN, best scores 0.16–0.19.
- Deferred to v0.1 acceptance: manage-dialog delete → re-UNKNOWN check
  (deletion is unit-tested; skipping avoids a pointless re-enrollment).
- Environment note: macOS input volume drifts (75 → 50 observed between
  sessions; external cause unknown). The panel surfaces `OS INPUT VOL`
  on every arm.

## CP4 gate context (2026-08-10)

Live recorder measurements on the built-in mic during the first user test:
quiet-room floor **−63 to −71 dBFS RMS**; a person speaking near the
laptop **≈ −45 dBFS RMS, peak ≈ 0.09**. The original −45 dBFS quiet gate
rejected real speech; lowered to **−55 dBFS** (learnings.md Observation
004). Silence remains rejected at the new gate.
