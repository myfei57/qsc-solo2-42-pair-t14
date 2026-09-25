"""Cooling water control.

The supply must be open before the unit starts and must stay open until the
shaft is below the stop threshold, so the stop path checks speed before it
closes the valve.
"""

from __future__ import annotations

import threading

from hydro.domain.constants import OPEN_FLOW_RATE, SPEED_STOP_THRESHOLD, STOP_FLOW_RATE
from hydro.domain.errors import SpeedTooHighError
from hydro.journal.store import KIND_COOLING, RecordStore
from hydro.runtime.context import RuntimeContext


class CoolingService:
    def __init__(self, context: RuntimeContext) -> None:
        self._journal: RecordStore = context.journal
        self._lock = threading.RLock()

    def _open_value(self, unit_id: str) -> bool:
        payload = self._journal.latest(KIND_COOLING, unit_id)
        return bool(payload.get("open", False)) if payload else False

    def _write(self, unit_id: str, open_value: bool) -> bool:
        self._journal.append_and_commit(KIND_COOLING, unit_id, {"open": open_value})
        return open_value

    def open(self, unit_id: str, tick: int) -> bool:
        with self._lock:
            return self._write(unit_id, True)

    def stop_guard(self, speed: float) -> None:
        if speed > SPEED_STOP_THRESHOLD:
            raise SpeedTooHighError(
                "speed {:.4g} above stop threshold {:.4g}".format(speed, SPEED_STOP_THRESHOLD)
            )

    def stop(self, unit_id: str, speed: float, tick: int) -> bool:
        with self._lock:
            self.stop_guard(speed)
            return self._write(unit_id, False)

    def is_open(self, unit_id: str) -> bool:
        return self._open_value(unit_id)

    def flow(self, unit_id: str) -> float:
        return OPEN_FLOW_RATE if self.is_open(unit_id) else STOP_FLOW_RATE

    def open_units(self, unit_ids: list[str]) -> list[str]:
        return [unit_id for unit_id in unit_ids if self.is_open(unit_id)]
