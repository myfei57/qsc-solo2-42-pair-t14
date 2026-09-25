"""Mechanical brake control.

The brake may only engage once the governor reports the speed is at or below
the brake threshold. The overspeed path additionally latches the brake so a
restart cannot silently clear it.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from hydro.domain.errors import SpeedTooHighError
from hydro.interlock.latch import Latch
from hydro.journal.store import RecordStore
from hydro.runtime.context import RuntimeContext

KIND_BRAKE = "brake"


class SpeedSource(Protocol):
    def speed_below_threshold(self, unit_id: str) -> bool: ...


class BrakeService:
    def __init__(
        self, context: RuntimeContext, gov: SpeedSource, latch: Latch
    ) -> None:
        self._journal: RecordStore = context.journal
        self._gov = gov
        self._latch = latch
        self._lock = threading.RLock()

    def _payload(self, unit_id: str) -> dict[str, Any]:
        payload = self._journal.latest(KIND_BRAKE, unit_id)
        base: dict[str, Any] = {"engaged": False}
        if payload is not None:
            base["engaged"] = bool(payload.get("engaged", False))
        return base

    def _write(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append_and_commit(KIND_BRAKE, unit_id, payload)
        return payload

    def engage_guard(self, unit_id: str) -> None:
        if not self._gov.speed_below_threshold(unit_id):
            raise SpeedTooHighError("speed above the brake threshold for " + unit_id)

    def engage(self, unit_id: str) -> bool:
        with self._lock:
            self.engage_guard(unit_id)
            self._write(unit_id, engaged=True)
            return True

    def engage_emergency(self, unit_id: str) -> bool:
        with self._lock:
            self.engage_guard(unit_id)
            self._latch.set(unit_id, "emergency engagement latches the brake")
            self._write(unit_id, engaged=True)
            return True

    def release(self, unit_id: str) -> bool:
        with self._lock:
            self._write(unit_id, engaged=False)
            return False

    def reset(self, unit_id: str) -> bool:
        with self._lock:
            self._latch.reset(unit_id)
            self._write(unit_id, engaged=False)
            return False

    def is_engaged(self, unit_id: str) -> bool:
        return bool(self._payload(unit_id)["engaged"])

    def latch(self, unit_id: str) -> bool:
        with self._lock:
            self._latch.set(unit_id, "brake latch set")
            return True

    def release_latch(self, unit_id: str) -> bool:
        with self._lock:
            self._latch.release(unit_id, "brake latch release blocked")
            return False

    def is_latched(self, unit_id: str) -> bool:
        return self._latch.is_set(unit_id)
