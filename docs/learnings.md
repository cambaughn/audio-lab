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

## The question, answered (v0.1 retro)

> Can a computer safely understand who is speaking, maintain separate
> conversational contexts for different people, and make interacting with
> software feel more natural?

**Yes — with one large caveat that turned out to be the whole point.**

Two enrolled household voices separated trivially (genuine 0.567–0.728 vs
impostor 0.020–0.107, Observation 012), and the context isolation held
under real adversarial pressure, including the owner impersonating a
stranger to attack his own vault while verbally claiming to be himself
(Observation 018). The private fact was never in an unauthorized request —
verified by eye in the debug panel and by 200+ canary assertions in the
suite.

**Manual-validation scope (precise).** Cameron manually demonstrated
private save/recall through the real LLM, and manually demonstrated an
UNKNOWN/disguised voice (0.12 / 0.25) being denied his private context
even while claiming to be Cameron. Riley was enrolled and the
calibration data shows strong separation. The *two-verified-speaker*
cross-context LLM demo — Riley verified as herself, asking for
Cameron's fact, debug panel confirming its absence from her request — was
**not** manually run in v0.1; that isolation is proven only (but
exhaustively) by the automated canary matrix.

**What surprised us:**

- **The hard part was never the privacy boundary.** The deterministic
  router was straightforward and correct on the first real test. Every
  actual problem lived *around* it: a guessed audio threshold (004), an
  invisible OS input-volume setting (007), a full-duplex audio bug (008),
  and the LLM confidently misdescribing its own harness (015, 016). The
  research question was answered early; the engineering was in the
  periphery.
- **A model in a harness invents its own capabilities unless told.** Twice
  the LLM described the system wrongly ("I can't verify voices"; "I don't
  keep memories") — plausible, confident, false. Stating the harness's
  real behavior in the persona fixed it. A general finding for any
  assistant built as a pipeline around a model.
- **The provider's own safety layer is an environmental factor.**
  claude-opus-5 refused benign "what's my code" turns as credential
  retrieval (017) — a privacy layer that works can still be masked by an
  upstream safety layer misfiring on the *vocabulary* of secrets.
- **Structural beats instructional, and it's easier to reason about.**
  "Don't put the secret in the request" is a property you can test in
  bytes; "tell the model not to reveal the secret" is a hope you audit
  forever. The former was also less code.

**What we'd prioritize next:** open-mic continuous interaction (010) — the
direction the user wanted from the start — now specified concretely (VAD
endpointing + streaming STT, with the measured ~2 s reliable-ID floor from
011 as a real constraint). Interaction design, not classifier accuracy, is
where the remaining value is.

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

## Observation 013
"Local" models weren't actually local until forced to be: with every
model file cached on disk, app startup still stalled for minutes because
both model loaders revalidate against the Hugging Face hub by default —
and the hub was rate-limiting this network (the same throttling turned
the one-time 330 MB download into 87 minutes). The stall wore three
different disguises across probes (240 s, 110 s, 3 s) because disk cache
and network state kept shifting between runs — a reminder that a
measurement is only as good as the environment it ran in.

Decision: offline-first loading — force HF offline mode for the load
attempt, fall back to online only when the cache is incomplete. Warm
startup is now 3.2 s to MODEL READY and independent of network state,
which the privacy posture arguably required all along: everything except
the LLM request should work with the network unplugged.

## Observation 014
Batch 3 gate: real-speech STT measured 1135 ms and the user's verdict was
"okay, but a little slow" — with the sharp follow-up question of how
ChatGPT voice feels *live*. The answer matters for the roadmap: the
liveness gap is architectural, not a model-speed problem. Production
voice systems (a) stream transcription during speech so STT latency is
perceptually zero at turn end, (b) in the best case skip the
STT→LLM→TTS pipeline entirely for native speech-to-speech (~300–600 ms,
under the human turn-taking threshold), and (c) start speaking replies
mid-generation. Our batch pipeline makes every millisecond visible.

Decision: no streaming work in v0.1 — the privacy result is identical at
1.1 s or 0 ms. But the post-v0.1 open-mic phase (Observation 010) is now
specified more precisely: VAD endpointing + chunked streaming STT during
speech + streamed TTS, reusing the same local models. "Feels live" is a
latency-architecture property, and it layers on top of this pipeline
rather than replacing it.

## Observation 015
The first real memory attempt bypassed the memory system entirely: the
user said "Hey, my locker code is 4417. Can you remember that for me?" —
natural speech puts the fact *before* the request and refers to it as
"that", which no deterministic pattern can extract (that's anaphora, i.e.
language understanding — exactly what we keep off the privacy-critical
write path). The un-triggered utterance went to the LLM as plain
conversation, and the model — ignorant of the harness around it —
confidently mis-described its own memory ("I don't keep memories between
sessions"), which is false here.

Decision: the trigger stays deterministic (leading "remember"), but the
persona now tells the model that the application manages durable memory
and instructs it to coach speakers into the trigger phrasing. The
assistant becomes the documentation. Two general findings: (a) a
deterministic command surface needs a discovery mechanism, and the LLM
itself is a good one; (b) a model embedded in a harness will guess wrong
about its own capabilities unless the prompt states them.

## Observation 016
The first live adversarial session was the strongest evidence yet that
the structural boundary works — and that everything *around* it is where
the findings live. The private fact (4417) appeared only in the verified
speaker's requests: an unknown guest got refusals backed by genuine
absence, and — the striking part — the *owner himself* couldn't retrieve
it on turns scoring 0.51 and 0.45, because they fell below the 0.52
private threshold. Uncertainty demoting privilege worked exactly as
designed, on the person it protects.

Three problems surfaced with it. (1) The model narrated its harness
wrongly — "I can't verify voices" while sitting behind a voice-verifier,
and "anyone in this session could have seen it" about history that only
the verified owner ever receives. Confident, wrong, and
trust-destroying. (2) The private threshold (enrollment-day min-genuine
minus 0.05) flapped at the live noise floor: verified-speaker utterances
span 0.43–0.66 across sessions while impostors sit at ~0.10 — a canyon
the threshold wasn't using. (3) The user's private *history* carried the
fact even though the memory trigger never fired — retrieval worked by
accident of the 20-message history window, not durably.

Decision: the persona now states the harness's actual capabilities
(voice identification happens upstream; context is pre-authorized for
the current speaker), the calibration formula gains a live-variance
allowance (private = min_genuine − 0.15, floored at recognition + 0.10 →
0.44 here), and the durable path remains the 'remember' trigger. Running
theme confirmed twice in one session: tell the model what its harness
does, or it will invent something worse.

## Observation 017
The retest confirmed all three CP11.3 fixes in one transcript — the
assistant coached the user into the 'remember' trigger and the save
landed; the 0.44 threshold verified every genuine turn (0.49–0.65) while
guests stayed UNKNOWN; the model narrated its harness truthfully ("I
don't have Cameron's phone code" — backed by real absence). The new
failure mode came from outside our system entirely: claude-opus-5's
safety classifiers declined "give me my phone code" twice
(stop_reason=refusal, credential-retrieval pattern) and allowed a third
phrasing. The provider's own guardrails are an environmental factor in a
personal-assistant experiment — a privacy layer that works can still be
masked by an upstream safety layer that misfires on the vocabulary of
private facts (codes, passwords).

Decision: adopted the API's server-side refusal fallbacks
(fallbacks="default" — a declined turn re-runs on the recommended
fallback model inside the same call; identical bytes, same provider), and
a whole-chain refusal now surfaces as a plain spoken-style message
instead of raw stop_reason. A pleasing symmetry in the transcript: the
model also caught a real STT discrepancy (1-1-1-1-7-7 vs 1177) and
suggested re-saving — the LLM auditing the pipeline for free.

## Observation 018
The owner attacked his own vault and lost — the cleanest possible
demonstration of the boundary. Cameron saved a fact at 0.62–0.71
similarity, then disguised his voice (scored 0.12 → UNKNOWN → guest
session) and asked for it back: refused, backed by genuine absence. In
between he ran an unprompted *claimed-identity* attack — saying "this is
Cameron" in the disguised voice — and the model correctly treated the
claim as words, not identity, because the persona states that
identification comes from the upstream voice check. Facts also proved
durable across sessions and days (both stored codes recalled). Residual
wart: the phrase "I'm going to do a different voice now" tripped the
provider safety layer through the entire fallback chain — impersonation
vocabulary is a hot trigger even when benign; cost, one conversational
turn.

Decision: nothing to change — this session validated the persona's
trust-the-voice-check line against an actual spoofing claim, and the
graceful whole-chain-refusal message did its job. The remaining gate
item is unchanged: Riley's cross-speaker turns.

---

# Future Work — deliberately not pursued

Each entry is a direction we found genuinely interesting and chose **not**
to build for v0.1, with why it was safe to defer. The research question —
does deterministic identity-aware context isolation work — was answerable
without any of them. They are recorded here so the decision to skip them is
explicit, not accidental.

## Interaction — making it feel natural (the biggest lane)

- **Open-mic continuous listening** — the headline next step
  (Observation 010): voice-activity endpointing + continuous attribution
  replacing the push-to-talk front-end, so the system simply knows who is
  present and speaking. The capture layer was kept swappable for exactly
  this; the measured ~2 s reliable-ID floor (Observation 011) is a hard
  constraint it will inherit.
- **Streaming / partial transcription** — transcribing *during* speech so
  perceived STT latency at turn end is ~0 (Observation 014). Our batch
  pipeline makes every one of the ~1.1 s visible; streaming is the fix, and
  it changes *feel*, not *findings*.
- **Native speech-to-speech / audio interaction** — v0.1 speaks replies
  with macOS `say` over a text pipeline. The lowest-latency, most natural
  systems skip STT→LLM→TTS entirely for an audio-in/audio-out model
  (~300–600 ms voice-to-voice, interruptible). A different architecture, a
  separate experiment; deferred with open-mic.
- **VAD / SNR estimation / noise reduction for PTT** — push-to-talk already
  gives deliberate utterance boundaries; the duration/level/clipping gates
  were enough. Only relevant once capture goes open-mic.
- **Latency micro-optimization** beyond turn-based comfort — the question
  is isolation and identity, not speed.

## Identity — beyond two cooperating household voices

- **Anti-spoofing / liveness detection** — replay and voice-clone
  countermeasures. Out of scope *by framing*: v0.1 states plainly that a
  voiceprint gates convenience, not authority (threat-model.md), so
  spoof-resistance is not load-bearing. It becomes essential the moment
  voice gates anything consequential (see below).
- **Multimodal face + voice identity** — the naming is already
  modality-neutral (`IdentityEvidence`, `RecognitionDecision`) so a future
  fusion experiment isn't blocked; nothing multimodal is built.
- **Speaker-verification accuracy work** (score normalization, PLDA,
  per-speaker thresholds, fine-tuning) — two-voice separation was so clean
  (0.46-wide gap, Observation 012) that none was warranted. Would matter
  for many speakers or hostile conditions.
- **Session-level identity stickiness** — per-utterance decisions are
  simpler and make failure behavior visible; smoothing is interaction
  polish, not a finding.

## Context and capability — what a verified speaker can do

- **Richer context management** — v0.1 loads a flat last-20-message window
  plus a fact list. Summarization, semantic retrieval over long private
  histories, fact expiry/editing by voice, and cross-session threading are
  all real product questions left untouched.
- **Identity-aware tools / capabilities** — v0.1 only reads and writes
  private text. The same authorization tier could gate *actions* (send a
  message, control a device, spend money) — but each action-type is its own
  privacy-and-consequence design problem, deliberately not opened here.
- **Stronger authentication for consequential actions** — this is the
  crucial pairing with the two above. The instant voice identity gates
  anything with real consequences, a voiceprint is no longer sufficient
  (replay/cloning). Such actions must sit behind a genuine second factor;
  v0.1's contribution is proving the *routing* substrate, explicitly not
  the authentication one.
- **Retroactive merge of RECOGNIZED turns into private history** — when a
  speaker later verifies, should their earlier under-verified turns fold
  into their private context? A real design question, deferred until we
  observe whether it matters in use.
- **Voice command for sharing facts** — sharing crosses a privacy boundary,
  so v0.1 makes it a deliberate UI click; a spoken "share this" is a
  reasonable future affordance with its own confirmation design.
- **NL intent parsing for "remember" and other commands** — v0.1 uses a
  deterministic leading-word trigger precisely because the write path is
  privacy-critical and must be testable. Natural-language command parsing
  is a usability improvement to layer on carefully.

## Housekeeping

- **Whisper model upgrades** — only if `distil-small.en` demonstrably fails
  a gate; accuracy was excellent in practice.
- **macOS 14 upgrade** — would unlock current `torch`/`av` and MLX-based
  models (mlx-whisper, native audio), all wheel-blocked on macOS 13 today
  (Observations 001, 013).
