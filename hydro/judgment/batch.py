"""Batch registry enforcing one live batch per identifier."""

from __future__ import annotations

import threading

from hydro.domain.errors import DuplicateBatchError, NotFoundError
from hydro.domain.types import Batch
from hydro.store.kv import Store


class BatchRegistry:
    """Each batch identifier may be opened exactly once."""

    def __init__(self, store: Store, namespace: str = "batch") -> None:
        self._store = store
        self._namespace = namespace.strip("/")
        self._lock = threading.RLock()

    def _key(self, batch_id: str) -> str:
        return "{}/{}".format(self._namespace, batch_id)

    def exists(self, batch_id: str) -> bool:
        return self._store.exists(self._key(batch_id))

    def get(self, batch_id: str) -> Batch:
        data = self._store.read_json(self._key(batch_id))
        if data is None:
            raise NotFoundError("batch not found: " + batch_id)
        return Batch(
            batch_id=str(data["batch_id"]),
            unit_id=str(data["unit_id"]),
            opened_tick=int(data["opened_tick"]),
            stage=str(data["stage"]),
        )

    def open(self, batch_id: str, unit_id: str, stage: str, tick: int) -> Batch:
        with self._lock:
            if self.exists(batch_id):
                raise DuplicateBatchError("batch already exists: " + batch_id)
            batch = Batch(
                batch_id=batch_id,
                unit_id=unit_id,
                opened_tick=int(tick),
                stage=stage,
            )
            self._store.write_json(self._key(batch_id), batch.as_dict())
            return batch

    def advance(self, batch_id: str, stage: str) -> Batch:
        with self._lock:
            batch = self.get(batch_id)
            updated = Batch(
                batch_id=batch.batch_id,
                unit_id=batch.unit_id,
                opened_tick=batch.opened_tick,
                stage=stage,
            )
            self._store.write_json(self._key(batch_id), updated.as_dict())
            return updated

    def by_unit(self, unit_id: str) -> list[Batch]:
        return [batch for batch in self.all() if batch.unit_id == unit_id]

    def all(self) -> list[Batch]:
        batches: list[Batch] = []
        for key in self._store.list_keys(self._namespace + "/"):
            data = self._store.read_json(key)
            if not data:
                continue
            batches.append(
                Batch(
                    batch_id=str(data["batch_id"]),
                    unit_id=str(data["unit_id"]),
                    opened_tick=int(data["opened_tick"]),
                    stage=str(data["stage"]),
                )
            )
        return sorted(batches, key=lambda batch: (batch.opened_tick, batch.batch_id))

    def count(self) -> int:
        return len(self.all())
