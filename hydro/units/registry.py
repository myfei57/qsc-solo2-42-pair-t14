"""Durable registry of generating units."""

from __future__ import annotations

import threading

from hydro.domain.errors import NotFoundError
from hydro.domain.states import UnitState
from hydro.domain.types import Unit
from hydro.journal.store import KIND_UNIT, RecordStore


class UnitRegistry:
    """Keeps unit identity and lifecycle state in the record stream."""

    def __init__(self, journal: RecordStore) -> None:
        self._journal = journal
        self._lock = threading.RLock()

    def register(self, unit_id: str, name: str, tick: int) -> Unit:
        with self._lock:
            existing = self._load(unit_id)
            if existing is not None:
                return existing
            unit = Unit(id=unit_id, name=name, state=UnitState.IDLE)
            payload = {"id": unit_id, "name": name, "state": unit.state.value}
            self._journal.append_and_commit(
                KIND_UNIT, unit_id, payload, dedup_key="register"
            )
            return unit

    def _load(self, unit_id: str) -> Unit | None:
        payload = self._journal.latest(KIND_UNIT, unit_id)
        if payload is None:
            return None
        return Unit(
            id=str(payload["id"]),
            name=str(payload["name"]),
            state=UnitState(payload.get("state", UnitState.IDLE.value)),
        )

    def exists(self, unit_id: str) -> bool:
        return self._journal.latest(KIND_UNIT, unit_id) is not None

    def get(self, unit_id: str) -> Unit:
        unit = self._load(unit_id)
        if unit is None:
            raise NotFoundError("unit not registered: " + unit_id)
        return unit

    def name(self, unit_id: str) -> str:
        try:
            return self.get(unit_id).name
        except NotFoundError:
            return unit_id

    def list(self) -> list[Unit]:
        units: list[Unit] = []
        for record in self._journal.records(KIND_UNIT):
            unit = self._load(record.entity)
            if unit is not None and unit not in units:
                units.append(unit)
        return sorted(units, key=lambda unit: unit.id)

    def count(self) -> int:
        return len(self.list())

    def ids(self) -> list[str]:
        return [unit.id for unit in self.list()]
