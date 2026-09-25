"""Guide vane control.

Opening the vanes is gated on the head already being written to durable storage,
and adjusting them is gated on the dispatch latch being released. Both gates are
evaluated against the state that the other packages publish, never against a
private copy.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from hydro.domain.constants import GUIDE_MAX_OPENING
from hydro.domain.errors import GuideLatchedError, HeadNotPersistedError, NoHeadError
from hydro.interlock.latch import Latch
from hydro.journal.store import KIND_GUIDE, RecordStore
from hydro.runtime.context import RuntimeContext


class HeadSource(Protocol):
    def current_head(self, unit_id: str) -> float: ...

    def latest(self, unit_id: str) -> float: ...


class GainSource(Protocol):
    def oil_gain(self, unit_id: str, now: int) -> float: ...


class AuditSink(Protocol):
    def record(self, event: str, unit_id: str, detail: str, tick: int) -> Any: ...


class GuideService:
    def __init__(
        self,
        context: RuntimeContext,
        head: HeadSource,
        audit: AuditSink,
        latch: Latch,
    ) -> None:
        self._ctx = context
        self._journal: RecordStore = context.journal
        self._head = head
        self._audit = audit
        self._latch = latch
        self._gain: GainSource | None = None
        self._overspeed: Any = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------- wiring

    def bind_gain(self, source: GainSource) -> None:
        with self._lock:
            self._gain = source

    def bind_overspeed(self, source: Any) -> None:
        with self._lock:
            self._overspeed = source

    def release_allowed(self, unit_id: str) -> bool:
        if self._overspeed is None:
            return True
        return not self._overspeed(unit_id)

    # --------------------------------------------------------------- state

    def _payload(self, unit_id: str) -> dict[str, Any]:
        payload = self._journal.latest(KIND_GUIDE, unit_id)
        base = {
            "open": False,
            "opening": 0.0,
            "applied_head": 0.0,
            "stroke": 0.0,
        }
        if payload is not None:
            base.update(
                {
                    "open": bool(payload.get("open", False)),
                    "opening": float(payload.get("opening", 0.0)),
                    "applied_head": float(payload.get("applied_head", 0.0)),
                    "stroke": float(payload.get("stroke", 0.0)),
                }
            )
        return base

    def _write(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append_and_commit(KIND_GUIDE, unit_id, payload)
        return payload

    def _stage(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append(KIND_GUIDE, unit_id, payload)
        return payload

    # -------------------------------------------------------------- actions

    def open(self, unit_id: str, tick: int) -> dict[str, Any]:
        head_value = self._head.current_head(unit_id)
        if head_value <= 0:
            raise NoHeadError("head must be positive before opening guide vanes")
        latest = self._head.latest(unit_id)
        if latest > 0 and latest != head_value:
            raise HeadNotPersistedError(
                "measured head {} is not the persisted head {}".format(latest, head_value)
            )
        payload = self._stage(unit_id, open=True, applied_head=head_value)
        self._audit.stage("guide-open", unit_id, "opened with persisted head", tick)
        self._journal.commit()
        return payload

    def close(self, unit_id: str, tick: int) -> dict[str, Any]:
        payload = self._stage(unit_id, open=False)
        self._audit.stage("guide-close", unit_id, "guide vanes closed", tick)
        self._journal.commit()
        return payload

    def restore(self, unit_id: str, tick: int) -> dict[str, Any]:
        head_value = self._head.current_head(unit_id)
        if head_value <= 0:
            raise NoHeadError("head must be positive before restoring guide vanes")
        payload = self._write(unit_id, open=True, applied_head=head_value)
        self._audit.record("guide-restore", unit_id, "restored from persisted head", tick)
        return payload

    def adjust(self, unit_id: str, target: float, tick: int) -> float:
        self.require_released(unit_id)
        opening = self.clamp_opening(target)
        self._write(unit_id, opening=opening, stroke=opening)
        self._audit.record("guide-adjust", unit_id, "adjusted guide vanes", tick)
        return opening

    def stroke(self, unit_id: str, millimetres: float, now: int) -> float:
        if self._gain is None:
            return millimetres
        return millimetres * self._gain.oil_gain(unit_id, now)

    def last_stroke(self, unit_id: str) -> float:
        return float(self._payload(unit_id)["stroke"])

    def is_open(self, unit_id: str) -> bool:
        return bool(self._payload(unit_id)["open"])

    def open_state(self, unit_id: str) -> str:
        return "open" if self.is_open(unit_id) else "closed"

    def applied_head(self, unit_id: str) -> float:
        return float(self._payload(unit_id)["applied_head"])

    def opening(self, unit_id: str) -> float:
        return float(self._payload(unit_id)["opening"])

    def opening_percent(self, unit_id: str) -> float:
        return self.opening(unit_id) / GUIDE_MAX_OPENING

    def clamp_opening(self, value: float) -> float:
        if value < 0:
            return 0.0
        if value > GUIDE_MAX_OPENING:
            return GUIDE_MAX_OPENING
        return float(value)

    # -------------------------------------------------------------- latches

    def latch(self, unit_id: str, tick: int) -> bool:
        self._latch.set(unit_id, "guide must be open to latch")
        self._audit.record("guide-latch", unit_id, "guide latch set", tick)
        return True

    def release_latch(self, unit_id: str, tick: int) -> bool:
        self._latch.release(unit_id, "guide latch release blocked while overspeed is active")
        self._audit.record("guide-release", unit_id, "guide latch released", tick)
        return False

    def is_latched(self, unit_id: str) -> bool:
        return self._latch.is_set(unit_id)

    def require_released(self, unit_id: str) -> None:
        if self.is_latched(unit_id):
            raise GuideLatchedError("guide vanes are latched for " + unit_id)
