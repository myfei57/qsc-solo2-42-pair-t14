"""Durable latch with explicit set and release conditions."""

from __future__ import annotations

import threading
from typing import Callable

from hydro.domain.errors import LatchConditionError
from hydro.store.kv import Store

Condition = Callable[[str], bool]


class Latch:
    """A named two-state interlock flag.

    Setting or releasing the latch is refused unless the matching condition
    reports true, which keeps "already latched" from being silently overwritten
    during an emergency.
    """

    def __init__(
        self,
        name: str,
        store: Store,
        namespace: str = "latch",
        set_condition: Condition | None = None,
        release_condition: Condition | None = None,
    ) -> None:
        self.name = name
        self._store = store
        self._namespace = namespace.strip("/")
        self._set_condition = set_condition
        self._release_condition = release_condition
        self._lock = threading.RLock()

    def _key(self, unit_id: str) -> str:
        return "{}/{}/{}".format(self._namespace, self.name, unit_id)

    def is_set(self, unit_id: str) -> bool:
        with self._lock:
            return bool(self._store.read_json(self._key(unit_id), default=False))

    def set(self, unit_id: str, reason: str = "") -> None:
        with self._lock:
            if self._set_condition is not None and not self._set_condition(unit_id):
                raise LatchConditionError(self.name, "set", reason or None)
            self._store.write_json(self._key(unit_id), True)

    def release(self, unit_id: str, reason: str = "") -> None:
        with self._lock:
            if self._release_condition is not None and not self._release_condition(unit_id):
                raise LatchConditionError(self.name, "release", reason or None)
            self._store.write_json(self._key(unit_id), False)

    def reset(self, unit_id: str) -> None:
        with self._lock:
            self._store.write_json(self._key(unit_id), False)

    def state(self, unit_id: str) -> bool:
        return self.is_set(unit_id)
