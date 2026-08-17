"""macOS system input volume — read-only, for diagnostics.

The OS input volume sits in front of every app's microphone stream. When
it is low, capture is quiet and the noise floor is proportionally worse,
which surfaced in Batch 1 as mystery TOO QUIET rejections and hum under
playback (learnings.md Observation 007). Most conferencing apps hide this
behind automatic gain control; a raw PortAudio stream does not. Audio Lab
shows the number rather than compensating for it.
"""

import subprocess

LOW_INPUT_VOLUME = 40  # below this, expect quiet capture; warn in the UI


def read_input_volume(runner=None) -> int | None:
    """Return the macOS input volume 0..100, or None if unavailable."""
    if runner is None:
        runner = subprocess.run
    try:
        result = runner(
            ["osascript", "-e", "input volume of (get volume settings)"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        return int(result.stdout.strip())
    except Exception:
        return None
