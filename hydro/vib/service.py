"""Vibration runout evaluation.

The runout limit is a versioned configuration value: changing it bumps the
configuration generation and stores a snapshot, so a reading taken against an
older snapshot can be recognised as stale.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from hydro.domain.constants import VIB_RUNOUT_LIMIT
from hydro.domain.errors import NoHeadError
from hydro.judgment.threshold import Threshold, Window
from hydro.journal.store import RecordStore
from hydro.runtime.context import RuntimeContext
from hydro.versioning.artifacts import Snapshot
from hydro.versioning.generations import SCOPE_CONFIG

KIND_VIB = "vib"


class SensorSource(Protocol):
    def bearing_sensor(self, unit_id: str) -> str: ...


class VibService:
    def __init__(self, context: RuntimeContext, source: SensorSource) -> None:
        self._ctx = context
        self._journal: RecordStore = context.journal
        self._source = source
        self._lock = threading.RLock()

    def _payload(self, unit_id: str) -> dict[str, Any]:
        payload = self._journal.latest(KIND_VIB, unit_id)
        base: dict[str, Any] = {"limit": 0.0, "generation": 0, "last": False}
        if payload is not None:
            base.update(payload)
        return base

    def _write(self, unit_id: str, **changes: Any) -> dict[str, Any]:
        payload = self._payload(unit_id)
        payload.update(changes)
        self._journal.append_and_commit(KIND_VIB, unit_id, payload)
        return payload

    def set_limit(self, unit_id: str, value: float, tick: int) -> Snapshot:
        with self._lock:
            generation = self._ctx.generations.bump(SCOPE_CONFIG, unit_id)
            snapshot = self._ctx.artifacts.take_snapshot(
                unit_id, SCOPE_CONFIG, {"limit": float(value)}, tick
            )
            self._write(unit_id, limit=float(value), generation=generation)
            return snapshot

    def limit(self, unit_id: str) -> float:
        value = float(self._payload(unit_id)["limit"])
        return value if value > 0 else VIB_RUNOUT_LIMIT

    def limit_generation(self, unit_id: str) -> int:
        return int(self._payload(unit_id)["generation"])

    def snapshot(self, unit_id: str) -> Snapshot:
        return self._ctx.artifacts.latest_snapshot(unit_id, SCOPE_CONFIG)

    def validate_limit_snapshot(self, unit_id: str) -> Snapshot:
        snapshot = self.snapshot(unit_id)
        snapshot.validate(self._ctx.generations)
        return snapshot

    def threshold(self, unit_id: str) -> Threshold:
        return Threshold(self.limit(unit_id))

    def band(self, unit_id: str) -> Window:
        return Window(low=0.0, high=self.limit(unit_id), low_inclusive=True)

    def compare(self, value: float, limit: float) -> bool:
        return Threshold(limit).exceeded(value)

    def judge(self, unit_id: str, raw: dict[str, float], tick: int) -> bool:
        sensor = self.active_sensor(unit_id)
        if sensor not in raw:
            raise NoHeadError("no reading for sensor " + sensor)
        runout = self.compare(float(raw[sensor]), self.limit(unit_id))
        self._write(unit_id, last=runout)
        return runout

    def runout(self, unit_id: str) -> bool:
        return bool(self._payload(unit_id)["last"])

    def active_sensor(self, unit_id: str) -> str:
        with self._lock:
            sensor = self._source.bearing_sensor(unit_id)
            self._write(unit_id, sensor=sensor)
            return sensor

    def refresh(self, unit_id: str) -> str:
        return self.active_sensor(unit_id)

    def sensor_list(self, unit_id: str) -> list[str]:
        sensor = self.active_sensor(unit_id)
        return [sensor] if sensor else []
