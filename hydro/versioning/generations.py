"""Per unit generation counters for parameters and configuration."""

from __future__ import annotations

import threading

from hydro.store.keys import generation_key
from hydro.store.kv import Store

SCOPE_HEAD = "head"
SCOPE_OIL = "oil"
SCOPE_BASELINE = "baseline"
SCOPE_CONFIRM = "confirm"
SCOPE_CONFIG = "config"

SCOPES = (SCOPE_HEAD, SCOPE_OIL, SCOPE_BASELINE, SCOPE_CONFIRM, SCOPE_CONFIG)


class GenerationBook:
    """Tracks the current generation of every versioned parameter scope.

    The counter is durable, so a restart keeps rejecting artifacts that were
    issued against a generation that has since been superseded.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.RLock()

    def current(self, scope: str, unit_id: str) -> int:
        with self._lock:
            return self._store.read_int(generation_key(scope, unit_id), default=0)

    def bump(self, scope: str, unit_id: str) -> int:
        with self._lock:
            value = self.current(scope, unit_id) + 1
            self._store.write_int(generation_key(scope, unit_id), value)
            return value

    def set(self, scope: str, unit_id: str, value: int) -> int:
        if value < 0:
            raise ValueError("generation must not be negative")
        with self._lock:
            self._store.write_int(generation_key(scope, unit_id), int(value))
            return int(value)

    def snapshot(self, unit_id: str) -> dict[str, int]:
        return {scope: self.current(scope, unit_id) for scope in SCOPES}
