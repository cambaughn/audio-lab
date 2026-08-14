# Architecture

*(Living document — sections fill in as their checkpoints land.)*

## Pipeline

```
Microphone
  → push-to-talk recording        (audio/capture.py — samples kept only while PTT held)
  → clip quality gates            (audio/clip.py — duration / level / clipping / silence)
  → speaker embedding             (speech/embedder.py — ECAPA-TDNN, local)
  → speaker matching              (identity/matcher.py — cosine, top-k, margin)
  → recognition decision          (identity/decision.py — two thresholds, monotone privilege)
  → speech-to-text                (speech/transcriber.py — faster-whisper, local)
  → deterministic context router  (conversation/router.py — selects ONLY authorized context)
  → LLM request                   (llm/ — frozen inspectable LlmRequest; text only leaves the machine)
  → text response
  → spoken response               (tts/speaker.py — macOS `say`)
```

"Who spoke?" (embedding → matching → decision) and "what was said?"
(transcription) are separate computations joined only at the router.

## Design invariants

- **Deterministic privacy boundary**: the router selects context from the
  recognition decision alone; the system prompt never contains withholding
  instructions; unauthorized content is absent from the request, and tests
  scan the serialized request to prove it.
- **Monotone privilege**: every uncertain or failed identity path routes to
  a strictly lower access tier.
- **No standing recording**: the armed stream meters and discards; samples
  exist in memory only between PTT press and release; raw audio never
  touches disk.
- **Ephemeral is structural**: guest/under-verified context lives in plain
  Python objects, never SQLite.

## Threads

| Thread | Owner | Lifetime |
|---|---|---|
| Main (Qt) | UI, matching, decision, routing | app |
| CaptureWorker | mic stream + PTT buffering | per ARM session |
| SpeechWorker | ECAPA + Whisper models, per-clip embed+transcribe | app (loads at launch) |
| LlmWorker | adapter calls | app |
| SayWorker | `say` subprocess | app |

Identity Lab worker pattern throughout: QObject + moveToThread, errors as
signals (never exceptions across threads), closeEvent quit/wait.

## Module map

See the repository tree in README; the deterministic core is
`conversation/router.py`, and the inspectable boundary is
`llm/types.py::LlmRequest.serialized()`.
