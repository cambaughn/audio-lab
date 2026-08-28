"""Print genuine/impostor score distributions and advisory thresholds.

Run after enrolling speakers:
    .venv/bin/python scripts/calibrate_thresholds.py

Reads the real speakers.db; writes nothing. Record the output in
docs/environment.md and docs/learnings.md, then set the sliders.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audio_lab.config.settings import APP_DATA_DIR  # noqa: E402
from audio_lab.identity.calibration import (  # noqa: E402
    score_distributions,
    suggest_thresholds,
    summarize,
)
from audio_lab.identity.store import DEFAULT_DB_FILENAME, IdentityStore  # noqa: E402
from audio_lab.speech.embedder import MODEL_ID  # noqa: E402


def main() -> int:
    db_path = APP_DATA_DIR / DEFAULT_DB_FILENAME
    if not db_path.exists():
        print(f"no database at {db_path} — enroll speakers first")
        return 1
    with IdentityStore(db_path) as store:
        names = [
            f"{r.display_name} ({r.sample_count} samples)"
            for r in store.list_identities()
        ]
        print("enrolled:", ", ".join(names) or "nobody")
        dist = score_distributions(store, MODEL_ID)
    print(f"genuine  (same speaker, leave-one-out): {summarize(dist.genuine)}")
    print(f"impostor (cross-speaker):               {summarize(dist.impostor)}")
    suggestion = suggest_thresholds(dist)
    if suggestion is None:
        print("no enrolled samples — nothing to calibrate")
        return 1
    print(
        f"\nsuggested operating points ({suggestion.basis}) — the app applies\n"
        f"these automatically on every enrollment change:\n"
        f"  recognition threshold    ~ {suggestion.recognition:.2f}\n"
        f"  private-access threshold ~ {suggestion.private_access:.2f}"
    )
    if dist.genuine and dist.impostor and min(dist.genuine) <= max(dist.impostor):
        print(
            "\nWARNING: genuine and impostor distributions OVERLAP — these "
            "voices may not separate reliably at any threshold. That itself "
            "is a finding; record it in learnings.md."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
