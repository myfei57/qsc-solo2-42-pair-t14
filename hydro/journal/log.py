"""Append only log with an explicit commit watermark."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable

from hydro.domain.errors import (
    DuplicateRecordError,
    NotFoundError,
    WatermarkError,
)
from hydro.journal.record import JournalRecord
from hydro.store.kv import Store


class RecordLog:
    """Durable append only stream.

    Appends are written to disk immediately but stay invisible until ``commit``
    raises the watermark past them. A process that restarts reads the log and the
    persisted watermark, so anything that was appended but never committed is
    dropped from the replayed state.
    """

    def __init__(
        self,
        store: Store,
        namespace: str = "journal",
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._store = store
        self._namespace = namespace.strip("/")
        self._clock = clock or (lambda: 0)
        self._lock = threading.RLock()
        self._records: list[JournalRecord] = []
        self._watermark = 0
        self._load()

    @property
    def records_key(self) -> str:
        return self._namespace + "/records.jsonl"

    @property
    def watermark_key(self) -> str:
        return self._namespace + "/watermark"

    def _load(self) -> None:
        self._watermark = self._store.read_int(self.watermark_key, default=0)
        path = self._store.path(self.records_key)
        if not path.is_file():
            return
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                self._records.append(JournalRecord.from_dict(json.loads(line)))

    @property
    def watermark(self) -> int:
        with self._lock:
            return self._watermark

    @property
    def max_seq(self) -> int:
        with self._lock:
            return self._records[-1].seq if self._records else 0

    def append(
        self,
        kind: str,
        entity: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
    ) -> JournalRecord:
        with self._lock:
            if dedup_key is not None and self._is_duplicate(kind, entity, dedup_key):
                raise DuplicateRecordError(
                    "duplicate record for {}/{}: {}".format(kind, entity, dedup_key)
                )
            record = JournalRecord(
                seq=self.max_seq + 1,
                kind=kind,
                entity=entity,
                payload=dict(payload),
                dedup_key=dedup_key,
                created_tick=int(self._clock()),
            )
            self._write_line(record)
            self._records.append(record)
            return record

    def rollback(self, seq: int, reason: str = "") -> JournalRecord:
        with self._lock:
            target = self.get(seq)
            if target is None:
                raise NotFoundError("sequence not found: {}".format(seq))
            if target.is_tombstone:
                raise WatermarkError("sequence {} is already a tombstone".format(seq))
            record = JournalRecord(
                seq=self.max_seq + 1,
                kind=target.kind,
                entity=target.entity,
                payload={},
                dedup_key=None,
                created_tick=int(self._clock()),
                tombstone_of=seq,
                reason=reason,
            )
            self._write_line(record)
            self._records.append(record)
            return record

    def _write_line(self, record: JournalRecord) -> None:
        path = self._store.path(self.records_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def commit(self) -> int:
        with self._lock:
            if not self._records:
                return self._watermark
            return self.commit_upto(self.max_seq)

    def commit_upto(self, seq: int) -> int:
        with self._lock:
            if seq < self._watermark:
                raise WatermarkError("watermark cannot move backwards")
            if seq > self.max_seq:
                raise WatermarkError(
                    "watermark {} beyond last sequence {}".format(seq, self.max_seq)
                )
            self._watermark = int(seq)
            self._store.write_int(self.watermark_key, self._watermark)
            return self._watermark

    def get(self, seq: int) -> JournalRecord | None:
        with self._lock:
            for record in self._records:
                if record.seq == seq:
                    return record
            return None

    def all_records(self) -> list[JournalRecord]:
        with self._lock:
            return list(self._records)

    def pending(self) -> list[JournalRecord]:
        with self._lock:
            return [record for record in self._records if record.seq > self._watermark]

    def committed(self) -> list[JournalRecord]:
        with self._lock:
            return [record for record in self._records if record.seq <= self._watermark]

    def tombstoned_seqs(self) -> set[int]:
        with self._lock:
            return {
                int(record.tombstone_of)
                for record in self._records
                if record.is_tombstone and record.seq <= self._watermark
            }

    def _live_records(self) -> list[JournalRecord]:
        dead = self.tombstoned_seqs()
        return [
            record
            for record in self._records
            if not record.is_tombstone and record.seq not in dead
        ]

    def visible(self) -> list[JournalRecord]:
        with self._lock:
            return [record for record in self._live_records() if record.seq <= self._watermark]

    def visible_for(self, kind: str, entity: str | None = None) -> list[JournalRecord]:
        with self._lock:
            return [
                record
                for record in self._live_records()
                if record.seq <= self._watermark
                and record.kind == kind
                and (entity is None or record.entity == entity)
            ]

    def latest(self, kind: str, entity: str) -> JournalRecord | None:
        records = self.visible_for(kind, entity)
        return records[-1] if records else None

    def _is_duplicate(self, kind: str, entity: str, dedup_key: str) -> bool:
        dead = self.tombstoned_seqs()
        for record in self._records:
            if record.is_tombstone or record.seq in dead:
                continue
            if (
                record.kind == kind
                and record.entity == entity
                and record.dedup_key == dedup_key
            ):
                return True
        return False

    def replay(self) -> "RecordLog":
        """Re-open the log from disk and rebuild the in-memory index."""

        with self._lock:
            self._records = []
            self._watermark = 0
            self._load()
            return self
