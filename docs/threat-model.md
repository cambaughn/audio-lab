# Threat model

## The one-sentence version

A speaker embedding is a similarity score, not an authentication factor;
Audio Lab uses voice identity to *select* conversational context, never to
grant authority beyond that, and enforces its privacy boundary structurally
rather than by prompting.

## Why a voiceprint is not a password

- **Replay is trivial.** A few seconds of a household member's voice
  recorded on any phone and played at the microphone defeats
  cosine-similarity verification. The replayed signal *is* the genuine
  voice.
- **Cloning is cheap.** Current TTS and voice-conversion tools reproduce a
  voice from seconds of reference audio.
- **The model has no countermeasure.** ECAPA-TDNN is trained for speaker
  discrimination on honest trials (VoxCeleb, ~0.8% EER). It has no
  liveness, replay, or synthesis detection. The ASVspoof challenge series
  exists precisely because speaker verification without countermeasures is
  defeatable.

Consequently, "PRIVATE ACCESS GRANTED" in Audio Lab means "confident enough
to load this person's conversational context in a consenting household
experiment" — never "authenticated."

## What v0.1 defends

- **Honest-household context isolation.** Two cooperating enrolled
  speakers, plus guests, each receive only their authorized context. This
  is the research question.
- **Structural enforcement.** Another user's private content is absent
  from an unauthorized model request — not present-but-forbidden. Tests
  scan the exact serialized request bytes for canary strings; a regression
  test pins that the system prompt never contains withholding instructions.
- **Monotone privilege under uncertainty.** Ambiguous margin, low score,
  short clip, failed embedding — every failure branch yields a strictly
  lower tier (UNKNOWN → ephemeral, no shared facts).
- **No standing microphone.** While armed, the input stream is metered and
  samples are discarded; audio is retained in memory only between
  push-to-talk press and release, and raw audio never touches disk.
- **Self-echo capture.** Push-to-talk is locked out while the app speaks
  (plus a cooldown); if TTS audio is captured anyway, the synthetic voice
  matches no enrolled gallery → UNKNOWN → ephemeral. No privilege gained.
- **Deliberate identity.** No persistent identity exists without an
  explicit multi-utterance enrollment; no persistent record of un-enrolled
  speakers is ever created.
- **Deletability.** Voice data lives in its own SQLite file
  (`secure_delete` on, VACUUM after reset); ephemeral sessions are
  in-memory objects that cannot outlive the app by construction.

## What v0.1 does NOT defend

- **Adversarial impersonation** — replay, cloning, mimicry. Out of scope;
  the mitigation is the framing (this is not authentication) and the
  household consent boundary.
- **A hostile household member** — someone with physical access to this
  Mac can read the SQLite files directly.
- **Overlapping or simultaneous speech** — one speaker per turn is assumed.
- **Coercion or shoulder-listening** — spoken responses are audible to the
  room.
- **The LLM provider** — the text of authorized context and transcripts is
  sent to the configured cloud LLM. Only text; never audio or embeddings.

## Data flow summary

Local: capture → embedding → matching → decision → routing → storage.
Outbound (network): exactly one thing — the composed LLM text request
(system prompt + authorized message history + transcript) to the
configured provider. Raw audio and voice embeddings never leave the
machine and raw audio is never written to disk.
