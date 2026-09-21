# Audio Lab

A local desktop laboratory for experimenting with voice identity and
speaker-isolated conversational context.

Audio Lab is a **research project, not an assistant**. It exists to answer
one question: *can a computer safely understand who is speaking, maintain
separate conversational contexts for different people, and make interacting
with software feel more natural?* You push-to-talk, the system recognizes
who spoke, transcribes what was said, and routes the utterance into that
speaker's isolated conversational context — deterministically, so one
person's private information is never even present in another person's
model request.

> **⚠️ Experimental, non-commercial research software.** This is a private
> laboratory for exploring speaker-aware interaction — not a production
> biometric security system. A voiceprint is not a password: replaying a
> recording or cloning a voice defeats it trivially. Do not use it for
> access control or any consequential decision. **Use it only with the
> informed consent of every person whose voice is enrolled or recorded.**

The application foundation and visual system were derived from
[Identity Lab v0.1.0](https://github.com/cambaughn/identity-lab), the
sibling experiment that answered the same question for faces.

## Status

**v0.1** — the full experiment runs end to end: deliberate voice
enrollment, two-threshold recognition, attributed transcription,
deterministic identity-aware context routing, a real cloud LLM behind a
fake-adapter toggle, and spoken responses. See
[docs/experiment.md](docs/experiment.md) for the research brief and
[docs/learnings.md](docs/learnings.md) for the running observations log —
a primary deliverable of this project.

## What it does

- **Deliberate voice enrollment**: six guided utterances per person,
  quality-gated, reviewable, all-or-nothing save. No identity exists
  without an explicit enrollment.
- **Speaker recognition** with two thresholds — a conversational-
  recognition threshold and a stricter private-access threshold —
  auto-calibrated from your own voices. Uncertainty always demotes access;
  a voiceprint is a routing signal, never a password.
- **Attributed speech**: each push-to-talk turn becomes
  `[CAMERON] <transcript>`, transcribed locally.
- **Deterministic context isolation** (the point): the application selects
  only the context the current speaker is authorized for *before* building
  the model request. One person's private information is never present in
  another's request — not withheld by instruction, structurally absent.
  A debug panel shows the exact outbound request.
- **Spoken replies** via macOS `say`, with the microphone locked while the
  app speaks so it never hears itself.

Everything except the single configured LLM text request runs locally.

## Requirements

- macOS on Apple Silicon (developed on macOS 13 / M2; Intel untested)
- Python 3.11 — **Homebrew arm64 build** (see Setup)
- ~800 MB disk for the Python environment, plus ~400 MB of model downloads
- Internet once for model downloads, and for the (optional) cloud LLM call —
  all voice processing is local

## Setup

Use the explicit Homebrew interpreter path. On this machine a bare
`python3` resolves to a python.org *universal2* build, which can silently
select x86_64 wheels and run everything under Rosetta:

```bash
git clone <repo> audio-lab
cd audio-lab
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Launch

Run from the macOS **Terminal** app — microphone permission is granted to
the hosting application, not to the script:

```bash
.venv/bin/python -m audio_lab
```

## Tests

No microphone, models, or network required:

```bash
.venv/bin/python -m pytest tests/
```

## Microphone-permission troubleshooting

macOS attributes microphone access to the app that hosts the process — for
a terminal launch, that's Terminal itself.

- First run: macOS asks "Terminal would like to access the microphone" →
  Allow.
- Denied or missed permission does **not** produce an error — the stream
  delivers digital silence. Audio Lab detects all-zero input and shows
  `MIC PERMISSION SUSPECTED`; enable your terminal in System Settings →
  Privacy & Security → Microphone, then quit and reopen the terminal.

## What is stored — and what is not

Stored, locally only, in `~/Library/Application Support/AudioLab/`:

- display names and voice embeddings (192 float32 numbers per enrollment
  sample — see [docs/storage.md](docs/storage.md))
- conversational contexts: private per-speaker messages and facts, and
  explicitly shared facts
- app settings (`settings.json`)

**Never stored:** raw audio of any kind (enrollment and conversation
recordings live only in memory during a turn), continuous room audio
(the microphone meters but discards samples except while push-to-talk is
held), audio or embeddings of un-enrolled people, cloud telemetry. The only
data that leaves the machine is the text of the configured LLM request.

## Licensing

- **This repository:** private, non-commercial research code.
- SpeechBrain + ECAPA-TDNN pretrained model: Apache-2.0.
- faster-whisper + Whisper models (Systran): MIT.
- PySide6: LGPL-3.0. sounddevice: MIT. PyTorch: BSD-style.
