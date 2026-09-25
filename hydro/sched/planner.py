"""Ordered startup and shutdown plans built on the interlock sequences."""

from __future__ import annotations

from typing import Any, Protocol

from hydro.domain.types import InterlockStage
from hydro.interlock.gates import GateRegistry
from hydro.interlock.sequence import StageSequence
from hydro.store.kv import Store

STARTUP_STAGES = (
    InterlockStage(1, "head-persist", ("head-persisted",)),
    InterlockStage(2, "cooling-open", ("cooling-open",)),
    InterlockStage(3, "unit-start", ("cooling-open", "unit-startable")),
    InterlockStage(4, "sync-confirm", ("sync-confirmed",)),
    InterlockStage(5, "excitation", ("sync-confirmed", "guide-released")),
)

SHUTDOWN_STAGES = (
    InterlockStage(1, "unload", ()),
    InterlockStage(2, "speed-drop", ("speed-low",)),
    InterlockStage(3, "brake-engage", ("speed-low",)),
    InterlockStage(4, "rundown", ("speed-low", "cooling-open")),
    InterlockStage(5, "cooling-stop", ("speed-low",)),
)


class GuideView(Protocol):
    def is_latched(self, unit_id: str) -> bool: ...

    def is_open(self, unit_id: str) -> bool: ...


class Planner:
    """Builds and advances the ordered operating plans."""

    def __init__(self, gates: GateRegistry, store: Store, guide: GuideView) -> None:
        self._gates = gates
        self._guide = guide
        self.startup = StageSequence("startup", STARTUP_STAGES, gates, store, "sequence")
        self.shutdown = StageSequence(
            "shutdown", SHUTDOWN_STAGES, gates, store, "sequence"
        )

    def stage_names(self, sequence_name: str) -> list[str]:
        return self._sequence(sequence_name).stage_names()

    def _sequence(self, sequence_name: str) -> StageSequence:
        if sequence_name == "startup":
            return self.startup
        if sequence_name == "shutdown":
            return self.shutdown
        raise KeyError("unknown sequence: " + sequence_name)

    def plan(self, sequence_name: str, unit_id: str) -> list[dict[str, Any]]:
        return self._sequence(sequence_name).plan(unit_id)

    def advance(
        self, sequence_name: str, unit_id: str, stage: str, tick: int
    ) -> InterlockStage:
        return self._sequence(sequence_name).advance(unit_id, stage, tick)

    def reset(self, sequence_name: str, unit_id: str) -> None:
        self._sequence(sequence_name).reset(unit_id)

    def completed(self, sequence_name: str, unit_id: str) -> tuple[str, ...]:
        return self._sequence(sequence_name).completed(unit_id)

    def next_stage(self, sequence_name: str, unit_id: str) -> str | None:
        stage = self._sequence(sequence_name).next_stage(unit_id)
        return stage.name if stage else None

    def is_complete(self, sequence_name: str, unit_id: str) -> bool:
        return self._sequence(sequence_name).is_complete(unit_id)

    def first_blocked(self, sequence_name: str, unit_id: str) -> dict[str, Any] | None:
        sequence = self._sequence(sequence_name)
        stage = sequence.next_stage(unit_id)
        if stage is None:
            return None
        blocked = self._gates.first_unsatisfied(unit_id, stage.gates)
        if blocked is None:
            return None
        gate = self._gates.get(blocked)
        return {
            "sequence": sequence_name,
            "stage": stage.name,
            "gate": gate.name,
            "description": gate.description,
        }

    def ready(self, sequence_name: str, unit_id: str) -> bool:
        return self.first_blocked(sequence_name, unit_id) is None

    def startup_ready(self, unit_id: str) -> bool:
        return self.ready("startup", unit_id)

    def shutdown_ready(self, unit_id: str) -> bool:
        return self.ready("shutdown", unit_id)

    def guide_released(self, unit_id: str) -> bool:
        return not self._guide.is_latched(unit_id)

    def guide_opened(self, unit_id: str) -> bool:
        return self._guide.is_open(unit_id)
