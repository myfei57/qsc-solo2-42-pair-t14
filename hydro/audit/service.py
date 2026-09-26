"""Audit events stored as journal records."""

from __future__ import annotations

from hydro.domain.types import AuditRecord
from hydro.journal.record import JournalRecord
from hydro.journal.store import KIND_AUDIT, RecordStore
from hydro.judgment.query import RecordQuery
from hydro.runtime.ids import IdAllocator


class AuditService:
    def __init__(self, journal: RecordStore, ids: IdAllocator) -> None:
        self._journal = journal
        self._ids = ids

    def stage(self, event: str, unit_id: str, detail: str, tick: int) -> AuditRecord:
        """Append an audit record without committing it yet.

        Staging lets a caller commit the audit entry together with the state
        change that produced it, so both become visible in one watermark step.
        """

        record_id = self._ids.next()
        payload = {
            "id": record_id,
            "unit_id": unit_id,
            "event": event,
            "detail": detail,
            "created_tick": int(tick),
        }
        self._journal.append(KIND_AUDIT, record_id, payload)
        return AuditRecord(
            id=record_id,
            unit_id=unit_id,
            event=event,
            detail=detail,
            created_tick=int(tick),
        )

    def record(self, event: str, unit_id: str, detail: str, tick: int) -> AuditRecord:
        audit = self.stage(event, unit_id, detail, tick)
        self._journal.commit()
        return audit

    def _pairs(self) -> list[tuple[JournalRecord, AuditRecord]]:
        # The audit stream is append only: every committed entry stays
        # readable, newer entries must never push older ones out of the trail.
        pairs: list[tuple[JournalRecord, AuditRecord]] = []
        for record in self._journal.records(KIND_AUDIT):
            payload = record.payload
            pairs.append(
                (
                    record,
                    AuditRecord(
                        id=str(payload["id"]),
                        unit_id=str(payload["unit_id"]),
                        event=str(payload["event"]),
                        detail=str(payload.get("detail", "")),
                        created_tick=int(payload.get("created_tick", 0)),
                    ),
                )
            )
        return pairs

    def _records(self) -> list[AuditRecord]:
        return [audit for _, audit in self._pairs()]

    def recent(self, limit: int) -> list[AuditRecord]:
        records = self._records()
        if limit <= 0:
            return []
        return records[-limit:]

    def by_unit(self, unit_id: str, limit: int) -> list[AuditRecord]:
        records = [record for record in self._records() if record.unit_id == unit_id]
        if limit <= 0:
            return []
        return records[-limit:]

    def events(self) -> list[str]:
        seen: list[str] = []
        for record in self._records():
            if record.event not in seen:
                seen.append(record.event)
        return seen

    def count(self) -> int:
        return len(self._records())

    def query(self, query: RecordQuery) -> list[AuditRecord]:
        """Apply a record query, matching the audit event as the record kind."""

        kept: list[AuditRecord] = []
        for raw, audit in self._pairs():
            view = JournalRecord(
                seq=raw.seq,
                kind=audit.event,
                entity=audit.unit_id,
                payload=raw.payload,
                dedup_key=raw.dedup_key,
                created_tick=raw.created_tick,
            )
            if query.matches(view):
                kept.append(audit)
        if query.newest_first:
            kept.reverse()
        if query.limit is not None and query.limit >= 0:
            kept = kept[: query.limit]
        return kept
