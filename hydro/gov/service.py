"""Governor control.

The governor owns the synchroniser confirmation and the oil calibration
baseline, both of which are generation bound and expire. Dispatch releases the
guide latch; overspeed sets the brake latch. Both latches therefore change
through the governor rather than by touching the other package's storage.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from hydro.domain.constants import (
    DEFAULT_OIL_GAIN,
    OUTPUT_COEFFICIENT,
    SPEED_BRAKE_THRESHOLD,
)
from hydro.domain.errors import (
    BrakeLatchedError,
    ControlError,
    GuideLatchedError,
    NotRegisteredError,
    OverspeedActiveError,
    SpeedTooHighError,
)
from hydro.journal.store import KIND_DISPATCH, KIND_GOV, RecordStore
from hydro.runtime.context import RuntimeContext
from hydro.versioning.artifacts import Confirmation
from hydro.versioning.generations import SCOPE_CONFIRM, SCOPE_OIL


class HeadLimitSource(Protocol):
    def head_for_limit(self, unit_id: str) -> float: ...

    def validate_baseline(self, unit_id: str, now: int) -> None: ...


class UnitChecker(Protocol):
    def exists(self, unit_id: str) -> bool: ...


class LatchReleaser(Protocol):
    def release_latch(self, unit_id: str, tick: int) -> bool: ...


class BrakeController(Protocol):
    def latch(self, unit_id: str) -> bool: ...

    def release_latch(self, unit_id: str) -> bool: ...

    def is_latched(self, unit_id: str) -> bool: ...


class GovService:
    def __init__(
        self,
        context: RuntimeContext,
        intake: HeadLimitSource,
        units: UnitChecker,
    ) -> None:
        self._ctx = context
        self._journal: RecordStore = context.journal
        self._intake = intake
        self._units = units
        self._guide: LatchReleaser | None = None
        self._brake: BrakeController | None = None
        self._lock = threading.RLock()

    # -------------------------------------------------------------- wiring

    def bind_guide(self, releaser: LatchReleaser) -> None:
        with self._lock:
            self._guide = releaser

    def bind_brake(self, brake: BrakeController) -> None:
        with self._lock:
            self._brake = brake

    def unit_exists(self, unit_id: str) -> bool:
        return self._units.exists(unit_id)

    # --------------------------------------------------------------- state

    def _payload(self, unit_id: str) -> dict[str, Any]:
        payload = self._journal.latest(KIND_GOV, unit_id)
        base: dict[str, Any] = {
            "sync_confirmed": False,
            "overspeed": False,
            "gain": 0.0,
            "pressure": 0.0,
            "threshold": SPEED_BRAKE_THRESHOLD,
            "speed": 0.0,
        }
        if payload is not None:
            base.update(payload)
        return base

    def _write(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append_and_commit(KIND_GOV, unit_id, payload)
        return payload

    # ---------------------------------------------------------- synchroniser

    def sync_confirm(self, unit_id: str, tick: int, ttl_ticks: int) -> Confirmation:
        with self._lock:
            generation = self._ctx.generations.bump(SCOPE_CONFIRM, unit_id)
            confirmation = self._ctx.artifacts.issue_confirmation(
                unit_id, SCOPE_CONFIRM, ttl_ticks, tick
            )
            self._write(
                unit_id,
                sync_confirmed=True,
                sync_generation=generation,
                sync_expires_at=confirmation.expires_at,
            )
            return confirmation

    def sync_confirmation(self, unit_id: str) -> Confirmation | None:
        payload = self._payload(unit_id)
        if not payload.get("sync_confirmed"):
            return None
        try:
            return self._ctx.artifacts.load_confirmation(unit_id, SCOPE_CONFIRM)
        except ControlError:
            return None

    def validate_sync(self, unit_id: str, now: int) -> Confirmation:
        confirmation = self._ctx.artifacts.load_confirmation(unit_id, SCOPE_CONFIRM)
        self._ctx.artifacts.validate_confirmation(confirmation, now)
        return confirmation

    def is_sync_confirmed(self, unit_id: str, now: int) -> bool:
        if not self._payload(unit_id).get("sync_confirmed"):
            return False
        try:
            self.validate_sync(unit_id, now)
        except ControlError:
            return False
        return True

    def sync_state(self, unit_id: str, now: int) -> str:
        if not self._payload(unit_id).get("sync_confirmed"):
            return "pending"
        try:
            self.validate_sync(unit_id, now)
        except ControlError as error:
            return "expired" if error.code == "expired-artifact" else "stale"
        return "confirmed"

    def reset_sync(self, unit_id: str) -> None:
        with self._lock:
            self._write(unit_id, sync_confirmed=False)

    # ---------------------------------------------------------------- speed

    def set_speed(self, unit_id: str, value: float) -> float:
        with self._lock:
            self._write(unit_id, speed=float(value))
            return float(value)

    def speed(self, unit_id: str) -> float:
        return float(self._payload(unit_id)["speed"])

    def set_threshold(self, unit_id: str, value: float) -> float:
        with self._lock:
            self._write(unit_id, threshold=float(value))
            return float(value)

    def threshold(self, unit_id: str) -> float:
        value = float(self._payload(unit_id)["threshold"])
        return value if value > 0 else SPEED_BRAKE_THRESHOLD

    def speed_below_threshold(self, unit_id: str) -> bool:
        return self.speed(unit_id) <= self.threshold(unit_id)

    # ------------------------------------------------------------------ oil

    def recalibrate_oil(
        self, unit_id: str, pressure: float, tick: int, ttl_ticks: int
    ) -> float:
        with self._lock:
            gain = pressure / SPEED_BRAKE_THRESHOLD
            self._ctx.artifacts.publish_baseline(
                unit_id, SCOPE_OIL, gain, ttl_ticks, tick
            )
            self._write(unit_id, gain=gain, pressure=float(pressure))
            return gain

    def oil_gain(self, unit_id: str, now: int) -> float:
        try:
            return self._ctx.artifacts.load_baseline(unit_id, SCOPE_OIL).value
        except ControlError:
            return DEFAULT_OIL_GAIN

    def validate_oil(self, unit_id: str, now: int) -> float:
        baseline = self._ctx.artifacts.load_baseline(unit_id, SCOPE_OIL)
        baseline.validate(self._ctx.generations, now)
        return baseline.value

    def oil_pressure(self, unit_id: str) -> float:
        return float(self._payload(unit_id)["pressure"])

    # ---------------------------------------------------------------- limit

    def head_used(self, unit_id: str) -> float:
        return self._intake.head_for_limit(unit_id)

    def limit_for(self, head: float) -> float:
        return head * OUTPUT_COEFFICIENT

    def limit(self, unit_id: str, now: int) -> float:
        self._intake.validate_baseline(unit_id, now)
        return self.limit_for(self.head_used(unit_id))

    def margin(self, unit_id: str, limit: float, now: int) -> float:
        return limit - self.limit(unit_id, now)

    def limit_status(self, unit_id: str, now: int) -> str:
        try:
            limit = self.limit(unit_id, now)
        except ControlError as error:
            return error.code
        if limit <= 0:
            return "blocked"
        if limit < 100:
            return "reduced"
        return "full"

    def output_status(self, unit_id: str, now: int) -> str:
        try:
            limit = self.limit(unit_id, now)
        except ControlError as error:
            return error.code
        if limit <= 0:
            return "no-head"
        return "limited"

    def setpoint(self, unit_id: str, load: float, now: int) -> float:
        limit = self.limit(unit_id, now)
        return limit if load > limit else float(load)

    def guard(self, unit_id: str) -> None:
        if not self.speed_below_threshold(unit_id):
            raise SpeedTooHighError("speed above the threshold for " + unit_id)

    # ------------------------------------------------------------- dispatch

    def dispatch(self, unit_id: str, tick: int) -> dict[str, Any]:
        if not self.unit_exists(unit_id):
            raise NotRegisteredError("unit not registered: " + unit_id)
        if self.overspeed(unit_id):
            raise OverspeedActiveError("overspeed is active for " + unit_id)
        with self._lock:
            guide = self._guide
        if guide is None:
            raise GuideLatchedError("guide latch controller is not wired")
        guide.release_latch(unit_id, tick)
        payload = {"released": True}
        self._journal.append_and_commit(KIND_DISPATCH, unit_id, payload)
        return payload

    def dispatch_state(self, unit_id: str, now: int) -> str:
        if self._intake.head_for_limit(unit_id) <= 0:
            return "no-head"
        return "released"

    # ------------------------------------------------------------ overspeed

    def set_overspeed(self, unit_id: str, active: bool, tick: int) -> bool:
        with self._lock:
            brake = self._brake
            if brake is None:
                raise OverspeedActiveError("brake controller is not wired")
            if active:
                brake.latch(unit_id)
            else:
                brake.release_latch(unit_id)
            self._write(unit_id, overspeed=bool(active))
            return bool(active)

    def clear_overspeed(self, unit_id: str, tick: int) -> bool:
        return self.set_overspeed(unit_id, False, tick)

    def overspeed(self, unit_id: str) -> bool:
        return bool(self._payload(unit_id)["overspeed"])

    # --------------------------------------------------------------- resume

    def resume(self, unit_id: str) -> None:
        if self.overspeed(unit_id):
            raise OverspeedActiveError("overspeed is active for " + unit_id)
        if not self.speed_below_threshold(unit_id):
            raise SpeedTooHighError("speed above the threshold for " + unit_id)
        with self._lock:
            brake = self._brake
        if brake is not None and brake.is_latched(unit_id):
            raise BrakeLatchedError("brake latch is engaged for " + unit_id)

    def can_resume(self, unit_id: str) -> bool:
        if self.overspeed(unit_id) or not self.speed_below_threshold(unit_id):
            return False
        with self._lock:
            brake = self._brake
        return brake is None or not brake.is_latched(unit_id)
