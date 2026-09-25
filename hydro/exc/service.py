"""Excitation application behind a synchroniser confirmation.

Excitation only applies while the confirmation issued by the governor is still
valid. A confirmation that has expired or that belongs to a superseded
generation is refused, so a stale slip can never energise the field.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from hydro.domain.errors import SyncNotConfirmedError
from hydro.journal.store import KIND_EXC, RecordStore
from hydro.runtime.context import RuntimeContext


class SyncSource(Protocol):
    def is_sync_confirmed(self, unit_id: str, now: int) -> bool: ...


class ExcService:
    def __init__(self, context: RuntimeContext, gov: SyncSource) -> None:
        self._journal: RecordStore = context.journal
        self._gov = gov
        self._lock = threading.RLock()

    def _payload(self, unit_id: str) -> dict[str, Any]:
        payload = self._journal.latest(KIND_EXC, unit_id)
        base: dict[str, Any] = {"applied": False, "breaker": False}
        if payload is not None:
            base["applied"] = bool(payload.get("applied", False))
            base["breaker"] = bool(payload.get("breaker", False))
        return base

    def _write(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append_and_commit(KIND_EXC, unit_id, payload)
        return payload

    def sync_guard(self, unit_id: str, now: int) -> None:
        if not self._gov.is_sync_confirmed(unit_id, now):
            raise SyncNotConfirmedError("synchroniser has not confirmed " + unit_id)

    def apply(self, unit_id: str, now: int) -> bool:
        with self._lock:
            self.sync_guard(unit_id, now)
            self._write(unit_id, applied=True)
            return True

    def apply_retry(self, unit_id: str, now: int) -> bool:
        return self.apply(unit_id, now)

    def reset(self, unit_id: str) -> bool:
        with self._lock:
            self._write(unit_id, applied=False)
            return False

    def is_applied(self, unit_id: str) -> bool:
        return bool(self._payload(unit_id)["applied"])

    def close_breaker(self, unit_id: str) -> bool:
        with self._lock:
            self._write(unit_id, breaker=True)
            return True

    def breaker_closed(self, unit_id: str) -> bool:
        return bool(self._payload(unit_id)["breaker"])

    def trip_breaker(self, unit_id: str) -> bool:
        with self._lock:
            self._write(unit_id, breaker=False)
            return False
