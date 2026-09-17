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

## Observation 004
The first real user test failed on a *guessed* constant: the "too quiet"
gate was set at −45 dBFS from intuition, but the built-in M2 mic delivers
normal speech at roughly −45 to −30 dBFS and a quiet room at −63 to −71
dBFS — so every genuine utterance was rejected and PLAY LAST CLIP never
lit up. All 31 unit tests passed because they tested the gate against
synthetic tones, not against what a real microphone produces.

Decision: gate lowered to −55 dBFS (still rejects the measured room floor
by a wide margin). More importantly: any threshold that touches real
signal gets measured against the actual device before it ships, and the
measurement goes in environment.md — synthetic tests prove logic, not
calibration.

## Observation 005
Two things the first user noticed that no test could: (a) armed vs.
recording was not visually distinct — the waveform brightening was too
subtle a cue for a state that matters this much; (b) PLAY LAST CLIP
"didn't play" although the output stream was verifiably active — the clip
peaked at ~3% of full scale and was simply inaudible through laptop
speakers. Push-to-talk clips from a laptop mic are quiet by nature.

Decision: recording state is now unmistakable (the PTT button inverts to
solid amber with a live duration counter); playback is peak-normalized to
a review level while stored/analyzed samples stay untouched. Interaction
feel is part of the research question, and it can only be judged by a
human at the gate — which is exactly why the gates exist.

## Observation 006
The playback fix from Observation 005 introduced a "crunching/beeping"
sound under the recording. Capture was verified clean (a 440 Hz test tone
recorded through the full AudioRecorder path came back spectrally pure
with zero overflows and no dropouts); the artifact was full peak-
normalization applying ~+27 dB, which lifted the built-in mic's own noise
floor — discrete hum at ~120 Hz and ~217 Hz sitting at −60 dBFS — up to
−33 dBFS, clearly audible. The signal chain is fine; the *ear* is a
sensitive instrument and the mic floor is not silent.

Decision: review gain capped at +12 dB. Also a note for Batch 2: the
embedding model will see that same hum on every clip; whether ECAPA is
robust to it is now a concrete thing to watch in the calibration data,
not a hypothetical. **Superseded by Observation 007 — the root cause was
upstream.**

## Observation 007
The user asked the right question: "every other program records clean
audio here — what is different?" The answer was the **macOS system input
volume, set to 14%**. The OS attenuates the microphone before any app
sees it; conferencing apps mask that with automatic gain control, a raw
PortAudio stream does not. Everything in Observations 004–006 was
downstream of one hidden system setting: speech arriving at −45 dBFS
(gate rejections), inaudible playback, and then hum when I compensated by
boosting. Two rounds of "fixes" treated symptoms because I inferred
instead of measuring the whole chain — including the OS layer.

Decision: no playback processing at all — clips play back exactly as
captured. The app now *shows* the OS input volume in the MICROPHONE panel
and warns when it is low, so a quiet signal is diagnosable at a glance.
General lesson, worth carrying to Batch 2 calibration: when a signal
looks wrong, measure every stage from the OS inward before touching
code; and a user's "this works everywhere else" is data, not noise.

## Observation 008
Crackle persisted through every gain change because the gain was never
the problem: playback ran through PortAudio's *output* side (sd.play)
while the input stream stayed armed — a full-duplex arrangement no other
macOS app uses, and the one stage of the chain that was never measured
(the acoustic loopback tests that tried turned out to be contaminated by
room noise and run-to-run routing variance — you cannot reliably measure
speaker output through a laptop mic in an uncontrolled room). "What do
all the working programs have in common that we don't" was the right
diagnostic question, asked by the user, twice.

Decision: playback moved off PortAudio entirely — QAudioSink plays clips
from memory through CoreAudio, the same output path every other macOS
app uses. PortAudio now handles input only; one library per direction.
Verified structurally (bit-exact samples reach the sink; real sink
constructs against the default output) — but the ear at the gate is the
only instrument that can confirm the crackle is gone.

---

## Observation 009
First real-voice calibration data (Cameron, 6 samples, built-in mic):
leave-one-out genuine scores 0.642–0.728 — comfortably above the guessed
0.55 private default, and no sign yet that the mic's hum floor
(Observation 006) hurts embeddings. But the gate surfaced a workflow
finding: a separate calibration script + manual slider-setting felt
clunky ("why can't it do that step automatically?"). Measurement that
requires a chore doesn't get done.

Decision: calibration now runs automatically on every enrollment change
and applies its suggested thresholds itself (single-speaker genuine-only
heuristic until a second speaker exists; sliders remain live overrides
between changes; overlap still warns loudly). The script survives only as
a detailed-numbers view for the docs.

## Observation 010
User direction after using push-to-talk: PTT is acceptable for v0.1, but
the desired end state is fluid, open-mic interaction — the audio analogue
of Identity Lab's continuous live recognition, where the system simply
knows who is present and speaking without a button.

Decision: v0.1 stays push-to-talk (deliberate utterance boundaries keep
the privacy experiment clean and honor the no-always-on-recording
boundary). Open-mic continuous listening is promoted from "declined
rabbit-hole" to the headline roadmap item for the next version — it needs
VAD utterance segmentation and continuous attribution, and the current
capture→evidence→decision→routing separation was kept clean so only the
capture front-end has to change.

## Observation 011
A structured live probe (one speaker, 9 utterances) quantified the
duration–evidence relationship on real hardware: ~1 s utterances scored
0.40–0.55 (one dropped below the recognition threshold → UNKNOWN), while
3 s and 6 s utterances scored 0.63–0.66 — indistinguishable from the
enrollment-time genuine distribution (0.64–0.73). A report of "low
confidence / random UNKNOWNs" was actually two stacked causes: short
test phrases, plus the OS input volume having silently drifted from 75
back to 50. Notably, longer speech beyond ~3 s bought nothing — the
evidence curve saturates fast.

Decision: no threshold changes — recognition on sentence-length speech is
healthy, and a short clip earning less access is the monotone-privilege
design working, now empirically grounded ("the extra verification turn is
just a longer phrase"). Added a visible hint when a sub-2 s clip yields a
non-private result, and the attribution log now records duration/level
per utterance so this data keeps collecting itself. The duration floor
for *reliable* ID (~2 s) is a hard finding to carry into the future
open-mic design: VAD segments shorter than that should expect weak
attribution.

## Observation 012
Two-person separation on real household voices is far better than the
experiment needs (Batch 2 gate, Cameron + Riley, 6 samples each,
built-in mic): genuine scores 0.567–0.728 vs impostor scores 0.020–0.107
— a 0.46-wide empty gap where thresholds can sit (auto-calibrated to
recognition 0.34 / private 0.52). Both enrolled speakers were correctly
attributed live, and macOS synthetic voices (Samantha, Alex) probed at
the microphone scored 0.16–0.19 → UNKNOWN. The pre-registered worry that
the mic's hum floor might compress the embedding space (Observation 006)
did not materialize.

Decision: speaker recognition is a solved sub-problem for this
experiment's conditions; no further verification-accuracy work (the
rabbit-hole register holds). The open question moves to where it always
belonged: the context-isolation layer — Batch 4.

---

# Future Work — declined rabbit-holes

Each entry is something we chose **not** to build for v0.1, with one line
on why it doesn't change what we learn.

- **Open-mic continuous listening** — the roadmap headline for after
  v0.1 (Observation 010): VAD utterance segmentation + continuous
  attribution replacing the PTT front-end. Deferred, not declined.
- **VAD / SNR estimation / noise reduction for PTT** — push-to-talk
  already gives deliberate utterance boundaries; duration/level/clipping
  gates are enough to answer the v0.1 question.
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
