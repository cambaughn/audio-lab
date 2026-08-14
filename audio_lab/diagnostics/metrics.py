"""The status event log.

Diagnostics never contain audio, embeddings, or transcript-derived private
facts — text events and numbers only. Nothing here persists to disk.
Ported from Identity Lab v0.1.0 (FpsCounter dropped: no frame loop here).
"""

import time
from collections import deque


class StatusLog:
    """Bounded in-memory event log: (HH:MM:SS, message) pairs, newest last."""

    def __init__(self, capacity: int = 200, clock=time.localtime) -> None:
        self._clock = clock
        self._events: deque[tuple[str, str]] = deque(maxlen=capacity)

    def add(self, message: str) -> tuple[str, str]:
        t = self._clock()
        stamp = f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
        event = (stamp, message)
        self._events.append(event)
        return event

    def events(self) -> list[tuple[str, str]]:
        return list(self._events)

    @staticmethod
    def format_event(event: tuple[str, str]) -> str:
        return f"{event[0]}  {event[1]}"
