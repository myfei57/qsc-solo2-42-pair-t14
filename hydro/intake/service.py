"""Intake head handling.

Measurement is transient until it is persisted. Persisting writes a committed
head record that carries the head generation, which every downstream readiness
check reads back from the record stream.
"""

from __future__ import annotations

import threading

from hydro.domain.constants import OPEN_FLOW_RATE
from hydro.domain.errors import HeadNotPersistedError, NoHeadError, NotFoundError
from hydro.domain.types import HeadRecord
from hydro.journal.store import KIND_HEAD, RecordStore
from hydro.runtime.context import RuntimeContext
from hydro.versioning.generations import SCOPE_BASELINE, SCOPE_HEAD


class IntakeService:
    def __init__(self, context: RuntimeContext) -> None:
        self._ctx = context
        self._journal: RecordStore = context.journal
        self._lock = threading.RLock()
        self._measured: dict[str, float] = {}

    # ------------------------------------------------------------- measuring

    def measure(self, unit_id: str, value: float) -> float:
        with self._lock:
            self._measured[unit_id] = float(value)
            return self._measured[unit_id]

    def latest(self, unit_id: str) -> float:
        with self._lock:
            return self._measured.get(unit_id, 0.0)

    def record(self, unit_id: str, raw: float, persist: bool, tick: int) -> HeadRecord | None:
        self.measure(unit_id, raw)
        if not persist:
            return None
        return self.persist_head(unit_id, tick)

    def pressure_head(self, pressure: float, density: float) -> float:
        if density <= 0:
            raise NoHeadError("density must be positive")
        return pressure / density * OPEN_FLOW_RATE

    # ------------------------------------------------------------ persistence

    def persist_head(self, unit_id: str, tick: int) -> HeadRecord:
        with self._lock:
            if unit_id not in self._measured:
                raise NoHeadError("no measured head for " + unit_id)
            value = self._measured[unit_id]
            generation = self._ctx.generations.bump(SCOPE_HEAD, unit_id)
            seq = self.head_seq(unit_id) + 1
            record = HeadRecord(
                unit_id=unit_id,
                value=value,
                seq=seq,
                generation=generation,
                created_tick=int(tick),
            )
            payload = record.as_dict()
            payload["offset"] = self._offset_value(unit_id)
            payload["calibrated_tick"] = self._calibrated_tick(unit_id)
            self._journal.append_and_commit(KIND_HEAD, unit_id, payload)
            return record

    def _head_payload(self, unit_id: str) -> dict[str, object]:
        payload = self._journal.latest(KIND_HEAD, unit_id)
        if payload is None:
            raise HeadNotPersistedError("head not persisted for " + unit_id)
        return payload

    def current_head(self, unit_id: str) -> float:
        return float(self._head_payload(unit_id)["value"])

    def validate(self, unit_id: str) -> None:
        self._head_payload(unit_id)

    def head_state(self, unit_id: str) -> str:
        try:
            self.validate(unit_id)
        except HeadNotPersistedError:
            return "missing"
        return "persisted"

    def head_seq(self, unit_id: str) -> int:
        payload = self._journal.latest(KIND_HEAD, unit_id)
        return int(payload["seq"]) if payload else 0

    def head_generation(self, unit_id: str) -> int:
        payload = self._journal.latest(KIND_HEAD, unit_id)
        return int(payload["generation"]) if payload else 0

    # ------------------------------------------------------------ calibration

    def set_baseline(
        self, unit_id: str, value: float, tick: int, ttl_ticks: int
    ) -> float:
        with self._lock:
            baseline = self._ctx.artifacts.publish_baseline(
                unit_id, SCOPE_BASELINE, value, ttl_ticks, tick
            )
            self.measure(unit_id, value)
            self.persist_head(unit_id, tick)
            return baseline.value

    def baseline(self, unit_id: str) -> float:
        try:
            return self._ctx.artifacts.load_baseline(unit_id, SCOPE_BASELINE).value
        except NotFoundError:
            return 0.0

    def baseline_meta(self, unit_id: str) -> dict[str, object]:
        try:
            return self._ctx.artifacts.load_baseline(unit_id, SCOPE_BASELINE).as_dict()
        except NotFoundError:
            return {}

    def validate_baseline(self, unit_id: str, now: int) -> None:
        try:
            baseline = self._ctx.artifacts.load_baseline(unit_id, SCOPE_BASELINE)
        except NotFoundError:
            return
        baseline.validate(self._ctx.generations, now)

    def recalibrate(
        self, unit_id: str, measured: float, tick: int, ttl_ticks: int
    ) -> float:
        with self._lock:
            baseline_value = self.baseline(unit_id)
            if baseline_value == 0.0:
                self._ctx.artifacts.publish_baseline(
                    unit_id, SCOPE_BASELINE, measured, ttl_ticks, tick
                )
                baseline_value = measured
            offset = measured - baseline_value
            self.measure(unit_id, measured)
            payload = {
                "unit_id": unit_id,
                "value": float(measured),
                "seq": self.head_seq(unit_id) + 1,
                "generation": self._ctx.generations.bump(SCOPE_HEAD, unit_id),
                "created_tick": int(tick),
                "offset": offset,
                "calibrated_tick": int(tick),
            }
            self._journal.append_and_commit(KIND_HEAD, unit_id, payload)
            return offset

    def _offset_value(self, unit_id: str) -> float:
        payload = self._journal.latest(KIND_HEAD, unit_id)
        return float(payload.get("offset", 0.0)) if payload else 0.0

    def _calibrated_tick(self, unit_id: str) -> int:
        payload = self._journal.latest(KIND_HEAD, unit_id)
        return int(payload.get("calibrated_tick", 0)) if payload else 0

    def offset(self, unit_id: str) -> float:
        return self._offset_value(unit_id)

    def head_for_limit(self, unit_id: str) -> float:
        return self.baseline(unit_id) + self.offset(unit_id)

    def calibrated_at(self, unit_id: str) -> int:
        return self._calibrated_tick(unit_id)
