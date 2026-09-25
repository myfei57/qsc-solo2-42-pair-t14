"""Plain value objects exchanged across packages."""

from __future__ import annotations

import dataclasses
from typing import Any

from hydro.domain.states import UnitState


@dataclasses.dataclass
class Unit:
    id: str
    name: str
    state: UnitState = UnitState.IDLE

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "state": self.state.value}


@dataclasses.dataclass(frozen=True)
class HeadRecord:
    unit_id: str
    value: float
    seq: int
    generation: int
    created_tick: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "value": self.value,
            "seq": self.seq,
            "generation": self.generation,
            "created_tick": self.created_tick,
        }


@dataclasses.dataclass(frozen=True)
class AuditRecord:
    id: str
    unit_id: str
    event: str
    detail: str
    created_tick: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit_id": self.unit_id,
            "event": self.event,
            "detail": self.detail,
            "created_tick": self.created_tick,
        }


@dataclasses.dataclass(frozen=True)
class Alarm:
    unit_id: str
    kind: str
    active: bool
    raised_tick: int
    resolved_tick: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "active": self.active,
            "raised_tick": self.raised_tick,
            "resolved_tick": self.resolved_tick,
        }


@dataclasses.dataclass(frozen=True)
class Batch:
    """A unique operating batch (a run of commands for one unit)."""

    batch_id: str
    unit_id: str
    opened_tick: int
    stage: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "unit_id": self.unit_id,
            "opened_tick": self.opened_tick,
            "stage": self.stage,
        }


@dataclasses.dataclass(frozen=True)
class InterlockStage:
    """A single ordered stage of an operating sequence."""

    order: int
    name: str
    gates: tuple[str, ...]
    latch: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "name": self.name,
            "gates": list(self.gates),
            "latch": self.latch,
        }
