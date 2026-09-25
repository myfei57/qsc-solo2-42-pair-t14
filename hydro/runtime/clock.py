"""A logical tick clock.

The runtime never reads the wall clock and never sleeps. Every timestamp that
ends up in a record is produced by this clock, so two runs that receive the same
command sequence observe exactly the same ticks.
"""

from __future__ import annotations

import threading


def format_stamp(tick: int) -> str:
    """Render a tick as a fixed width, sortable stamp."""

    if tick < 0:
        raise ValueError("tick must not be negative")
    return "t{:08d}".format(tick)


class Clock:
    """Base contract for a deterministic clock."""

    def now(self) -> int:
        raise NotImplementedError

    def stamp(self) -> str:
        return format_stamp(self.now())

    def advance(self, ticks: int = 1) -> int:
        raise NotImplementedError

    def set(self, tick: int) -> None:
        raise NotImplementedError


class TickClock(Clock):
    """Monotonic tick counter advanced explicitly by callers."""

    def __init__(self, start: int = 0, step: int = 1) -> None:
        if step <= 0:
            raise ValueError("step must be positive")
        self._tick = int(start)
        self._step = int(step)
        self._lock = threading.Lock()

    def now(self) -> int:
        with self._lock:
            return self._tick

    def advance(self, ticks: int = 1) -> int:
        if ticks < 0:
            raise ValueError("ticks must not be negative")
        with self._lock:
            self._tick += self._step * ticks
            return self._tick

    def set(self, tick: int) -> None:
        if tick < 0:
            raise ValueError("tick must not be negative")
        with self._lock:
            self._tick = int(tick)

    def reset(self) -> None:
        with self._lock:
            self._tick = 0
