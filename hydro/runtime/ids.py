"""Deterministic identifier allocation backed by the key/value store."""

from __future__ import annotations

import threading

from hydro.store.kv import Store


class IdAllocator:
    """Allocates sequential identifiers that survive process restarts.

    The counter lives in the key/value store, so a process that is restarted on
    the same data directory continues the sequence instead of repeating names.
    """

    def __init__(
        self,
        store: Store,
        key: str,
        prefix: str,
        width: int = 6,
        start: int = 1,
    ) -> None:
        if width <= 0:
            raise ValueError("width must be positive")
        if start <= 0:
            raise ValueError("start must be positive")
        self._store = store
        self._key = key
        self._prefix = prefix
        self._width = width
        self._start = start
        self._lock = threading.Lock()

    def current(self) -> int:
        return self._store.read_int(self._key, default=self._start - 1)

    def next(self) -> str:
        with self._lock:
            value = self.current() + 1
            self._store.write_int(self._key, value)
        return self.format(value)

    def format(self, value: int) -> str:
        return "{}-{:0{width}d}".format(self._prefix, value, width=self._width)

    def reset(self) -> None:
        with self._lock:
            self._store.write_int(self._key, self._start - 1)
