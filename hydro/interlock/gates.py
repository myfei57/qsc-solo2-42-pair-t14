"""Named prerequisite gates evaluated against the live control state."""

from __future__ import annotations

import dataclasses
from typing import Callable

from hydro.domain.errors import GateBlockedError


@dataclasses.dataclass(frozen=True)
class Gate:
    """A single prerequisite condition for a stage."""

    name: str
    description: str
    predicate: Callable[[str], bool]

    def satisfied(self, unit_id: str) -> bool:
        return bool(self.predicate(unit_id))

    def check(self, unit_id: str) -> None:
        if not self.satisfied(unit_id):
            raise GateBlockedError(self.name, self.description)


class GateRegistry:
    """Ordered collection of gates keyed by name."""

    def __init__(self) -> None:
        self._gates: dict[str, Gate] = {}

    def register(self, gate: Gate) -> Gate:
        if gate.name in self._gates:
            raise ValueError("gate already registered: " + gate.name)
        self._gates[gate.name] = gate
        return gate

    def get(self, name: str) -> Gate:
        try:
            return self._gates[name]
        except KeyError as exc:
            raise KeyError("unknown gate: " + name) from exc

    def names(self) -> list[str]:
        return list(self._gates.keys())

    def satisfied(self, unit_id: str, name: str) -> bool:
        return self.get(name).satisfied(unit_id)

    def first_unsatisfied(self, unit_id: str, names: tuple[str, ...]) -> str | None:
        for name in names:
            if not self.satisfied(unit_id, name):
                return name
        return None

    def check_all(self, unit_id: str, names: tuple[str, ...]) -> None:
        blocked = self.first_unsatisfied(unit_id, names)
        if blocked is not None:
            self.get(blocked).check(unit_id)

    def evaluate(self, unit_id: str, names: tuple[str, ...]) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for name in names:
            gate = self.get(name)
            out.append(
                {
                    "name": gate.name,
                    "description": gate.description,
                    "satisfied": gate.satisfied(unit_id),
                }
            )
        return out
