"""Record store facade: append a full snapshot, commit, then read it back."""

from __future__ import annotations

import threading
from typing import Any, Callable

from hydro.journal.log import RecordLog
from hydro.journal.record import JournalRecord
from hydro.store.kv import Store

KIND_UNIT = "unit"
KIND_HEAD = "head"
KIND_GUIDE = "guide"
KIND_COOLING = "cooling"
KIND_EXC = "exc"
KIND_GOV = "gov"
KIND_DISPATCH = "dispatch"
KIND_TURBINE = "turbine"
KIND_BATCH = "batch"
KIND_STAGE = "stage"
KIND_ALARM = "alarm"
KIND_AUDIT = "audit"


class RecordStore:
    """Convenience layer over :class:`RecordLog`.

    Every write appends a full payload snapshot for a ``(kind, entity)`` key and
    then commits. Reads only consult committed records, therefore a write that
    has not been committed yet is invisible to the component that issued it.
    """

    def __init__(
        self,
        store: Store,
        namespace: str = "journal",
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._store = store
        self._log = RecordLog(store, namespace=namespace, clock=clock)
        self._lock = threading.RLock()

    @property
    def log(self) -> RecordLog:
        return self._log

    @property
    def watermark(self) -> int:
        return self._log.watermark

    def append(
        self,
        kind: str,
        entity: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
    ) -> JournalRecord:
        with self._lock:
            return self._log.append(kind, entity, payload, dedup_key=dedup_key)

    def append_and_commit(
        self,
        kind: str,
        entity: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
    ) -> JournalRecord:
        with self._lock:
            record = self._log.append(kind, entity, payload, dedup_key=dedup_key)
            self._log.commit()
            return record

    def commit(self) -> int:
        with self._lock:
            return self._log.commit()

    def rollback(self, seq: int, reason: str = "") -> JournalRecord:
        with self._lock:
            return self._log.rollback(seq, reason)

    def latest(self, kind: str, entity: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._log.latest(kind, entity)
            return dict(record.payload) if record else None

    def records(self, kind: str, entity: str | None = None) -> list[JournalRecord]:
        with self._lock:
            return self._log.visible_for(kind, entity)

    def replay(self) -> "RecordStore":
        with self._lock:
            self._log.replay()
            return self
