"""A single entry of the append only record stream."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class JournalRecord:
    """One immutable entry.

    ``seq`` is assigned by the log and never changes. ``entity`` is the key the
    payload belongs to inside its ``kind``. ``tombstone_of`` marks an entry as a
    rollback of an earlier sequence.
    """

    seq: int
    kind: str
    entity: str
    payload: dict[str, Any]
    dedup_key: str | None
    created_tick: int
    tombstone_of: int | None = None
    reason: str = ""

    @property
    def is_tombstone(self) -> bool:
        return self.tombstone_of is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "entity": self.entity,
            "payload": self.payload,
            "dedup_key": self.dedup_key,
            "created_tick": self.created_tick,
            "tombstone_of": self.tombstone_of,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JournalRecord":
        return cls(
            seq=int(data["seq"]),
            kind=str(data["kind"]),
            entity=str(data.get("entity", "")),
            payload=dict(data.get("payload") or {}),
            dedup_key=data.get("dedup_key"),
            created_tick=int(data.get("created_tick", 0)),
            tombstone_of=data.get("tombstone_of"),
            reason=str(data.get("reason", "")),
        )
