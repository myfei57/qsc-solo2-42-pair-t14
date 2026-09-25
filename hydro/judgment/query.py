"""Filtering rules applied to committed journal records."""

from __future__ import annotations

import dataclasses
from typing import Any, Iterable

from hydro.journal.record import JournalRecord


@dataclasses.dataclass(frozen=True)
class RecordQuery:
    """Declarative filter over records.

    Filters combine with AND. ``tick_from`` is inclusive and ``tick_to`` is
    inclusive as well, which keeps a window query reproducible across restarts.
    """

    kinds: tuple[str, ...] | None = None
    entities: tuple[str, ...] | None = None
    tick_from: int | None = None
    tick_to: int | None = None
    limit: int | None = None
    newest_first: bool = False
    exclude_tombstones: bool = True

    def matches(self, record: JournalRecord) -> bool:
        if self.exclude_tombstones and record.is_tombstone:
            return False
        if self.kinds is not None and record.kind not in self.kinds:
            return False
        if self.entities is not None and record.entity not in self.entities:
            return False
        if self.tick_from is not None and record.created_tick < self.tick_from:
            return False
        if self.tick_to is not None and record.created_tick > self.tick_to:
            return False
        return True

    def apply(self, records: Iterable[JournalRecord]) -> list[JournalRecord]:
        selected = [record for record in records if self.matches(record)]
        if self.newest_first:
            selected.reverse()
        if self.limit is not None and self.limit >= 0:
            selected = selected[: self.limit]
        return selected

    def describe(self) -> dict[str, Any]:
        return {
            "kinds": list(self.kinds) if self.kinds else None,
            "entities": list(self.entities) if self.entities else None,
            "tick_from": self.tick_from,
            "tick_to": self.tick_to,
            "limit": self.limit,
            "newest_first": self.newest_first,
        }
