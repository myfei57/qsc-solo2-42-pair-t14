"""Ordered multi-stage sequences with gate checks before each stage."""

from __future__ import annotations

import dataclasses
import threading
from typing import Any, Iterable

from hydro.domain.errors import OutOfOrderError
from hydro.domain.types import InterlockStage
from hydro.interlock.gates import GateRegistry
from hydro.store.kv import Store


@dataclasses.dataclass(frozen=True)
class StageProgress:
    unit_id: str
    position: int
    completed: tuple[str, ...]
    updated_tick: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "position": self.position,
            "completed": list(self.completed),
            "updated_tick": self.updated_tick,
        }


class StageSequence:
    """A strict ordered sequence of interlocked stages.

    A stage can only be entered when every earlier stage has already completed,
    and when all of its own prerequisite gates evaluate to true.
    """

    def __init__(
        self,
        name: str,
        stages: Iterable[InterlockStage],
        gates: GateRegistry,
        store: Store,
        namespace: str = "sequence",
    ) -> None:
        self.name = name
        self._stages = tuple(stages)
        if not self._stages:
            raise ValueError("a sequence needs at least one stage")
        self._gates = gates
        self._store = store
        self._namespace = namespace.strip("/")
        self._lock = threading.RLock()

    @property
    def stages(self) -> tuple[InterlockStage, ...]:
        return self._stages

    def stage_names(self) -> list[str]:
        return [stage.name for stage in self._stages]

    def _key(self, unit_id: str) -> str:
        return "{}/{}/{}".format(self._namespace, self.name, unit_id)

    def progress(self, unit_id: str) -> StageProgress:
        with self._lock:
            data = self._store.read_json(self._key(unit_id))
            if data is None:
                return StageProgress(unit_id=unit_id, position=0, completed=(), updated_tick=0)
            return StageProgress(
                unit_id=unit_id,
                position=int(data.get("position", 0)),
                completed=tuple(data.get("completed", [])),
                updated_tick=int(data.get("updated_tick", 0)),
            )

    def position(self, unit_id: str) -> int:
        return self.progress(unit_id).position

    def is_complete(self, unit_id: str) -> bool:
        return self.position(unit_id) >= len(self._stages)

    def next_stage(self, unit_id: str) -> InterlockStage | None:
        position = self.position(unit_id)
        if position >= len(self._stages):
            return None
        return self._stages[position]

    def plan(self, unit_id: str) -> list[dict[str, Any]]:
        position = self.position(unit_id)
        out: list[dict[str, Any]] = []
        for index, stage in enumerate(self._stages):
            if index < position:
                state = "complete"
            elif index == position:
                state = "next"
            else:
                state = "pending"
            out.append(
                {
                    "order": stage.order,
                    "name": stage.name,
                    "state": state,
                    "gates": self._gates.evaluate(unit_id, stage.gates),
                    "latch": stage.latch,
                }
            )
        return out

    def advance(self, unit_id: str, stage_name: str, tick: int) -> InterlockStage:
        with self._lock:
            progress = self.progress(unit_id)
            if progress.position >= len(self._stages):
                raise OutOfOrderError(
                    "sequence {} is already complete for {}".format(self.name, unit_id)
                )
            expected = self._stages[progress.position]
            if stage_name != expected.name:
                raise OutOfOrderError(
                    "expected stage {} before {}, got {}".format(
                        expected.name, progress.completed[-1] if progress.completed else "-", stage_name
                    )
                )
            self._gates.check_all(unit_id, expected.gates)
            completed = tuple(progress.completed) + (expected.name,)
            self._store.write_json(
                self._key(unit_id),
                {
                    "unit_id": unit_id,
                    "position": progress.position + 1,
                    "completed": list(completed),
                    "updated_tick": int(tick),
                },
            )
            return expected

    def completed(self, unit_id: str) -> tuple[str, ...]:
        return self.progress(unit_id).completed

    def reset(self, unit_id: str) -> None:
        with self._lock:
            self._store.write_json(
                self._key(unit_id),
                {
                    "unit_id": unit_id,
                    "position": 0,
                    "completed": [],
                    "updated_tick": 0,
                },
            )
