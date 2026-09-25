"""Runner state machine.

Starting requires the cooling water to be open and every transition is recorded
so the judgment layer can compare the current state with the historical chain.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from hydro.domain.constants import SPEED_STOP_THRESHOLD
from hydro.domain.errors import CoolingClosedError, NotRegisteredError, SpeedTooHighError
from hydro.domain.states import UnitState, can_start, can_stop, next_state
from hydro.judgment.history import StateHistory
from hydro.journal.store import KIND_TURBINE, RecordStore
from hydro.runtime.context import RuntimeContext


class CoolingSource(Protocol):
    def is_open(self, unit_id: str) -> bool: ...

    def stop(self, unit_id: str, speed: float, tick: int) -> bool: ...


class TurbineService:
    def __init__(
        self,
        context: RuntimeContext,
        cooling: CoolingSource,
        history: StateHistory,
    ) -> None:
        self._journal: RecordStore = context.journal
        self._cooling = cooling
        self._history = history
        self._lock = threading.RLock()

    # --------------------------------------------------------------- state

    def _payload(self, unit_id: str) -> dict[str, Any]:
        payload = self._journal.latest(KIND_TURBINE, unit_id)
        base: dict[str, Any] = {
            "state": UnitState.IDLE.value,
            "speed": 0.0,
            "sensor": "",
        }
        if payload is not None:
            base.update(payload)
        return base

    def _write(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append_and_commit(KIND_TURBINE, unit_id, payload)
        return payload

    def register(self, unit_id: str, tick: int) -> UnitState:
        with self._lock:
            self._write(unit_id, state=UnitState.IDLE.value)
            self._history.record(unit_id, UnitState.IDLE.value, tick, "register")
            return UnitState.IDLE

    def state(self, unit_id: str) -> UnitState:
        return UnitState(self._payload(unit_id)["state"])

    def is_running(self, unit_id: str) -> bool:
        return self.state(unit_id) is UnitState.RUNNING

    def transition(self, unit_id: str, action: str, tick: int) -> UnitState:
        with self._lock:
            current = self.state(unit_id)
            if action == "start" and not can_start(current):
                raise NotRegisteredError(
                    "cannot start from state " + current.value
                )
            if action == "stop" and not can_stop(current):
                raise NotRegisteredError(
                    "cannot stop from state " + current.value
                )
            target = next_state(current, action)
            self._write(unit_id, state=target.value)
            self._history.record(unit_id, target.value, tick, action)
            return target

    # --------------------------------------------------------------- start

    def start_guard(self, unit_id: str) -> None:
        if not self._cooling.is_open(unit_id):
            raise CoolingClosedError("cooling water is closed for " + unit_id)

    def start(self, unit_id: str, tick: int) -> UnitState:
        self.start_guard(unit_id)
        return self.transition(unit_id, "start", tick)

    def start_hot(self, unit_id: str, tick: int) -> UnitState:
        self.start_guard(unit_id)
        return self.transition(unit_id, "start", tick)

    def start_ready(self, unit_id: str) -> bool:
        return self._cooling.is_open(unit_id)

    # ---------------------------------------------------------------- stop

    def stop(self, unit_id: str, tick: int) -> UnitState:
        if self.speed(unit_id) > SPEED_STOP_THRESHOLD:
            raise SpeedTooHighError("speed above the stop threshold for " + unit_id)
        return self.transition(unit_id, "stop", tick)

    def trip(self, unit_id: str, tick: int) -> UnitState:
        return self.transition(unit_id, "trip", tick)

    def reset(self, unit_id: str, tick: int) -> UnitState:
        return self.transition(unit_id, "reset", tick)

    def rundown_guard(self, unit_id: str) -> None:
        if self.speed(unit_id) > SPEED_STOP_THRESHOLD:
            raise SpeedTooHighError("speed above the stop threshold for " + unit_id)

    def rundown(self, unit_id: str, tick: int) -> UnitState:
        self.rundown_guard(unit_id)
        self._cooling.stop(unit_id, self.speed(unit_id), tick)
        return self.transition(unit_id, "rundown", tick)

    def cooling_held(self, unit_id: str) -> bool:
        return self._cooling.is_open(unit_id)

    # --------------------------------------------------------------- speed

    def set_speed(self, unit_id: str, value: float) -> float:
        with self._lock:
            self._write(unit_id, speed=float(value))
            return float(value)

    def speed(self, unit_id: str) -> float:
        return float(self._payload(unit_id)["speed"])

    def above_stop_threshold(self, unit_id: str) -> bool:
        return self.speed(unit_id) > 0

    def speed_band(self, unit_id: str) -> str:
        speed = self.speed(unit_id)
        if speed <= 0:
            return "stopped"
        if speed < SPEED_STOP_THRESHOLD:
            return "low"
        return "high"

    # -------------------------------------------------------------- sensors

    def swap_bearing(self, unit_id: str, sensor_id: str) -> str:
        with self._lock:
            self._write(unit_id, sensor=sensor_id)
            return sensor_id

    def bearing_sensor(self, unit_id: str) -> str:
        return str(self._payload(unit_id)["sensor"])

    def sensors(self, unit_id: str) -> list[str]:
        primary = self.bearing_sensor(unit_id)
        if not primary:
            return []
        return [primary, primary + "-aux"]
