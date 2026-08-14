# Learnings

A running research log — one of the primary deliverables of Audio Lab.
Not a TODO list: numbered observations, each with the decision it drove.
Updated at the checkpoint where the observation happened, not at release.

Format:

```
## Observation NNN
What we observed, in one or two sentences.

Decision: what we did (or deliberately did not do) because of it.
```

---

## Observation 001
The macOS-14 wheel cliff identified for torch during planning turned out to
be a *pattern*, not a single package: `av` (faster-whisper's audio decoder)
also ships only `macosx_14_0` wheels from v16 onward, and its sdist fails
to compile against this machine's stray Intel-prefix ffmpeg headers. On a
deliberately back-level OS, every native dependency needs its last
compatible wheel identified and pinned.

Decision: pinned `av==15.1.0` (the last macosx_13 wheel) alongside torch
2.11.0, and documented the cliff pattern in requirements.txt so future
upgrades check wheels before bumping any native package.

## Observation 002
The very first microphone stream a process opens can fail with an opaque
PortAudio internal error (−9986) and then work forever after — the same
first-attempt-after-permission-grant flakiness Identity Lab saw with the
camera. Meanwhile `check_input_settings()` said 16 kHz was supported even
while the start was failing, so capability *checks* are not predictive;
only actually starting the stream is.

Decision: capture opens with one automatic retry before surfacing
`MIC ERROR`, and we trust empirical stream starts over capability queries.
16 kHz direct capture is confirmed working (141 ms open), so no software
resampler is built.

## Observation 003
The planned dedicated capture QThread turned out to be unnecessary:
PortAudio's callback already runs on its own native thread, so all the
worker thread would have done is forward data. Identity Lab needed a
camera thread because OpenCV capture is a blocking *pull* loop; audio
capture is *push*.

Decision: AudioRecorder lives on the main thread — the callback mutates
lock-protected state, a 15 Hz QTimer publishes signals. One less thread,
one less lifecycle to test, identical learning value.

---

# Future Work — declined rabbit-holes

Each entry is something we chose **not** to build for v0.1, with one line
on why it doesn't change what we learn.

- **VAD / SNR estimation / noise reduction** — push-to-talk already gives
  deliberate utterance boundaries; duration/level/clipping gates are
  enough to answer the question.
- **Streaming / partial STT** — turn latency is measured and reported;
  streaming changes feel, not findings, at this stage.
- **Latency micro-optimization** beyond the <8 s end-to-end target —
  the question is isolation and identity, not speed.
- **Speaker-verification accuracy work** (score normalization, PLDA,
  fine-tuning) beyond threshold calibration — two-household-voice
  separation either works with a stock model or that is itself the
  finding.
- **Anti-spoofing / liveness** — out of scope by framing: voiceprints are
  not authentication here (see threat-model.md).
- **Session-level identity stickiness** — per-utterance decisions are
  simpler and make failure behavior visible; stickiness is interaction
  polish.
- **Retroactive merge of RECOGNIZED turns into private history** —
  a real design question, deferred until we observe whether it matters.
- **Voice command for sharing facts** — sharing crosses a privacy
  boundary; a deliberate UI click answers the question safely.
- **NL intent parsing for "remember"** — a literal prefix is deterministic
  and testable.
- **Multimodal (face+voice) identity** — naming keeps the door open
  (IdentityEvidence, RecognitionDecision); nothing is built.
- **Whisper model upgrades** — only if `distil-small.en` demonstrably
  fails a gate.
