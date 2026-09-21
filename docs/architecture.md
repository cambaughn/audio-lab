# Architecture

## Pipeline

```
Microphone
  → push-to-talk recording        (audio/capture.py — samples kept only while PTT held)
  → clip quality gates            (audio/clip.py — duration / level / clipping / silence)
  → speaker embedding             (speech/embedder.py — ECAPA-TDNN, local, ~30-70ms)
  → speaker matching              (identity/matcher.py — cosine, top-k, margin)
  → recognition decision          (identity/decision.py — two thresholds, monotone privilege)
  → speech-to-text                (speech/transcriber.py — faster-whisper distil-small.en, ~1.1s)
  → deterministic context router  (conversation/router.py — selects ONLY authorized context)
  → LLM request                   (llm/ — frozen inspectable LlmRequest; text only leaves the machine)
  → text response
  → spoken response               (tts/speaker.py — macOS `say`)
```

"Who spoke?" (embedding → matching → decision) and "what was said?"
(transcription) are separate computations, joined only at the router. Both
run in one pass on the SpeechWorker thread per accepted clip.

## The turn, end to end

`MainWindow` is the conductor. Per accepted push-to-talk clip:

1. `AppState → PROCESSING`; the clip goes to `SpeechWorker` (embed +
   transcribe on its own thread).
2. `SpeechAnalysis` comes back → matcher scores the embedding → `decide()`
   maps it to an `AccessTier` → SPEAKER / AUTHORIZATION / TRANSCRIPT
   readouts update, and the attributed turn appears in the conversation.
3. If the transcript starts with "remember", `handle_remember()` runs
   (deterministic, no LLM) and the ack is spoken.
4. Otherwise `route()` builds a `ContextBundle`, `build_request()` composes
   the `LlmRequest` from **only that bundle**, `AppState → THINKING`, and
   `LlmWorker` calls the adapter off-thread.
5. The reply is recorded into the same scope it was routed from,
   `AppState → SPEAKING`, `say` speaks it, then a 300 ms cooldown returns
   to `READY`.

The recorder can capture only in `READY`, so the app can never transcribe
its own speech.

## Design invariants

- **Deterministic privacy boundary**: the router selects context from the
  recognition decision alone; the system prompt never contains withholding
  instructions; unauthorized content is *absent* from the request, and
  tests scan `LlmRequest.serialized()` to prove it.
- **Monotone privilege**: every uncertain or failed identity path routes to
  a strictly lower access tier (ambiguous margin → UNKNOWN even at high
  similarity; missing evidence → UNKNOWN).
- **No standing recording**: the armed stream meters and discards; samples
  exist in memory only between PTT press and release; raw audio never
  touches disk.
- **Ephemeral is structural**: guest / under-verified context lives in
  plain Python objects (`conversation/ephemeral.py`), never SQLite, so it
  cannot outlive the session.
- **One network egress**: the composed `LlmRequest` text is the only thing
  that leaves the machine (see the LLM adapter). Audio and embeddings never
  do.

## Threads

| Thread | Owner | Lifetime |
|---|---|---|
| Main (Qt) | UI, matching, decision, routing, `say` (QProcess) | app |
| PortAudio callback | mic capture (no QThread — see Observation 003) | per ARM |
| SpeechWorker | ECAPA + Whisper, per-clip embed+transcribe | app |
| LlmWorker | adapter calls | app |

Identity Lab worker pattern throughout: QObject + moveToThread, errors as
signals (never exceptions across threads), `closeEvent` quit/wait.

## LLM adapter boundary

`llm/types.py` defines the frozen `LlmRequest`; `serialized()` is the
canary-scan surface. `llm/adapter.py` has the `FakeLlmAdapter` (the only
adapter until the privacy suite was green) and the `RecordingAdapter`
wrapper that gives the debug panel ground truth. `anthropic_adapter.py` —
the only network code in the tree — builds its payload solely from the
request's fields, with server-side refusal fallbacks. `llm/config.py`
reads `llm.json` (provider/model/key-env-var name); the key lives only in
the environment.

## Module map

Deterministic core: `conversation/router.py`. Inspectable boundary:
`llm/types.py::LlmRequest.serialized()`. Everything else supports getting a
clean, attributed, authorized turn to and from those two.
