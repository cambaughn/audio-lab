# Storage

*(Living document — schemas land with their checkpoints: speakers.db at
CP5, conversations.db at CP9.)*

Two SQLite files in `~/Library/Application Support/AudioLab/`, both using
the Identity Lab store discipline: versioned `_MIGRATIONS` dict applied
inside a `schema_migrations` bookkeeping table, typed error hierarchy,
`PRAGMA secure_delete=ON`, `PRAGMA quick_check` on open, reset + VACUUM.

## speakers.db (biometrics — planned, CP5)

A separate file so "delete all voice data" is one self-contained,
VACUUM-scrubbed operation.

- `speakers(id, display_name UNIQUE(lower), created_at, enrollment_version)`
- `voice_samples(id, speaker_id FK CASCADE, embedding BLOB, dim, dtype,
  model_id, duration_s, created_at)`

Embedding codec: little-endian `<f4`, no header, blob length exactly
`dim * 4`, dim and model_id in their own columns, validation on encode and
decode — ported verbatim from Identity Lab (`docs/storage.md` there
documents the format in full).

## conversations.db (planned, CP9)

- `contexts(id, scope CHECK IN ('PRIVATE','SHARED'), speaker_id,
  created_at, CHECK(scope='PRIVATE' ⟺ speaker_id NOT NULL))`
  + UNIQUE(scope, speaker_id)
- `messages(id, context_id FK CASCADE, role, content, speaker_id,
  decision, similarity, created_at)`
- `facts(id, context_id FK CASCADE, content, created_by_speaker_id,
  created_at)`

`speaker_id` in conversations.db is a soft cross-file reference to
speakers.db (documented, not enforced across files).

## EPHEMERAL — deliberately not in storage

Ephemeral guest/under-verified context is held in plain in-memory objects
(`conversation/ephemeral.py`) and never touches SQLite. Deletability at
session end is a structural property, not a cleanup job.

## What is never stored

Raw audio (any form, any duration), audio of un-enrolled speakers,
embeddings of un-enrolled speakers, API keys (the LLM key lives in an
environment variable; `llm.json` names only the variable).
