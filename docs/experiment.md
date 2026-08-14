# The Audio Lab experiment

## Question

Can a computer safely understand who is speaking, maintain separate
conversational contexts for different people, and make interacting with
software feel more natural?

Audio Lab is a research project — not an assistant, not a product. Every
implementation decision optimizes for learning over completeness. If a
simpler implementation answers the same research question, we build the
simpler one. Engineering rabbit-holes (DSP, verification accuracy, latency
tuning) get one test: *does solving this materially change what we learn?*
If not, they are recorded as Future Work in [learnings.md](learnings.md)
and skipped.

## Success demonstration

v0.1 succeeds when this sequence works repeatedly:

1. Cameron deliberately enrolls his voice.
2. Riley deliberately enrolls hers.
3. Cameron push-to-talks a private fact.
4. The system recognizes Cameron, transcribes the utterance, and stores it
   **only** in Cameron's private context.
5. Riley speaks later and is recognized as Riley.
6. Riley asks for Cameron's private information.
7. The system does not reveal it — **because Cameron's private context was
   never placed into Riley's model request** (verifiable in debug mode).
8. Cameron returns and the system recalls his own private fact.
9. An unknown speaker receives an ephemeral guest context with no access
   to anyone's private information.
10. Debug mode exposes speaker attribution, similarity, authorization
    decision, selected context scope, transcript, and a safe summary of
    what was supplied to the LLM.

Everything in this repository exists only because it supports that
demonstration.

## The critical privacy rule

The LLM must not enforce privacy by instruction. The application
deterministically selects only the context authorized for the current
speaker **before** constructing the model request. Unauthorized content is
absent from the request, not merely "off limits." Tests inspect the exact
serialized request to prove it.

## Context classes

- **PRIVATE** — belongs to one enrolled identity; available only when that
  identity meets the stricter private-access verification threshold.
- **SHARED** — explicitly designated (by a deliberate UI action) as
  available to all recognized household members. Unknown guests get
  nothing.
- **EPHEMERAL** — a temporary in-memory context for unknown or
  under-verified speakers. No access to private data; discarded at session
  end by construction.

**Uncertainty never grants more access.** Every failure branch of the
recognition decision routes to a strictly lower privilege tier.

## Two verification thresholds

1. **Conversational-recognition threshold** — enough to tentatively
   identify and personalize ("probably Cameron").
2. **Private-access threshold** — stricter evidence required before any
   private context is loaded.

Passing the first but not the second yields a visible
"recognized-but-not-verified" state: shared facts only, and a hint to
speak a longer phrase (which naturally produces better identity evidence).

A voiceprint is never treated as a password — see
[threat-model.md](threat-model.md).

## What would falsify success

- Any test or debug inspection showing another speaker's private content
  in an outbound request.
- Two enrolled household speakers who cannot be reliably distinguished at
  usable thresholds.
- A pipeline too slow or brittle for two people to alternate turns
  naturally.

## Deliberately out of scope for v0.1

Overlapping speech · always-on recording · speaker localization · mic
arrays · face+voice fusion · automatic enrollment · voice cloning ·
production authentication · emotion inference · email/calendar · arbitrary
tool calls · general long-term memory · mobile/vehicle/robot versions ·
fully offline LLM.
