"""Alarms persisted as committed records."""

from __future__ import annotations

import threading

from hydro.domain.errors import NotFoundError
from hydro.domain.types import Alarm
from hydro.journal.store import KIND_ALARM, RecordStore
from hydro.runtime.context import RuntimeContext


class AlarmService:
    def __init__(self, context: RuntimeContext) -> None:
        self._journal: RecordStore = context.journal
        self._lock = threading.RLock()

    @staticmethod
    def _entity(unit_id: str, kind: str) -> str:
        return unit_id + "/" + kind

    def _payload(self, unit_id: str, kind: str) -> dict[str, object]:
        payload = self._journal.latest(KIND_ALARM, self._entity(unit_id, kind))
        if payload is None:
            raise NotFoundError("alarm not found: {} {}".format(unit_id, kind))
        return payload

    def set(self, unit_id: str, kind: str, tick: int) -> Alarm:
        with self._lock:
            alarm = Alarm(
                unit_id=unit_id,
                kind=kind,
                active=True,
                raised_tick=int(tick),
                resolved_tick=None,
            )
            self._journal.append_and_commit(
                KIND_ALARM, self._entity(unit_id, kind), alarm.as_dict()
            )
            return alarm

    def resolve(self, unit_id: str, kind: str, tick: int) -> Alarm:
        with self._lock:
            payload = self._payload(unit_id, kind)
            alarm = Alarm(
                unit_id=unit_id,
                kind=kind,
                active=False,
                raised_tick=int(payload.get("raised_tick", 0)),
                resolved_tick=int(tick),
            )
            self._journal.append_and_commit(
                KIND_ALARM, self._entity(unit_id, kind), alarm.as_dict()
            )
            return alarm

    def is_active(self, unit_id: str, kind: str) -> bool:
        try:
            return bool(self._payload(unit_id, kind).get("active", False))
        except NotFoundError:
            return False

    def list(self) -> list[Alarm]:
        latest: dict[str, Alarm] = {}
        for record in self._journal.records(KIND_ALARM):
            payload = record.payload
            latest[record.entity] = Alarm(
                unit_id=str(payload["unit_id"]),
                kind=str(payload["kind"]),
                active=bool(payload.get("active", False)),
                raised_tick=int(payload.get("raised_tick", 0)),
                resolved_tick=payload.get("resolved_tick"),
            )
        return sorted(latest.values(), key=lambda alarm: (alarm.unit_id, alarm.kind))

    def by_unit(self, unit_id: str) -> list[Alarm]:
        return [alarm for alarm in self.list() if alarm.unit_id == unit_id]

    def active_kinds(self) -> list[str]:
        kinds: list[str] = []
        for alarm in self.list():
            if alarm.active and alarm.kind not in kinds:
                kinds.append(alarm.kind)
        return kinds

    def active_count(self) -> int:
        return len([alarm for alarm in self.list() if alarm.active])

    def count(self) -> int:
        return len(self.list())
