"""Threshold and window comparisons with explicit boundary rules."""

from __future__ import annotations

import dataclasses
from typing import Any

from hydro.domain.errors import LimitExceededError


@dataclasses.dataclass(frozen=True)
class Threshold:
    """Compares a value against a single limit."""

    limit: float
    inclusive: bool = True

    def exceeded(self, value: float) -> bool:
        if self.inclusive:
            return value > self.limit
        return value >= self.limit

    def within(self, value: float) -> bool:
        return not self.exceeded(value)

    def require(self, subject: str, value: float) -> None:
        if self.exceeded(value):
            raise LimitExceededError(subject, value, self.limit)

    def as_dict(self) -> dict[str, Any]:
        return {"limit": self.limit, "inclusive": self.inclusive}


@dataclasses.dataclass(frozen=True)
class Window:
    """Compares a value against a bounded window."""

    low: float
    high: float
    low_inclusive: bool = True
    high_inclusive: bool = False

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError("high must not be below low")

    def _above_low(self, value: float) -> bool:
        if self.low_inclusive:
            return value >= self.low
        return value > self.low

    def _below_high(self, value: float) -> bool:
        if self.high_inclusive:
            return value <= self.high
        return value < self.high

    def contains(self, value: float) -> bool:
        return self._above_low(value) and self._below_high(value)

    def classify(self, value: float) -> str:
        if not self._above_low(value):
            return "below"
        if not self._below_high(value):
            return "above"
        return "inside"

    def require(self, subject: str, value: float) -> None:
        if not self.contains(value):
            edge = self.low if self.classify(value) == "below" else self.high
            raise LimitExceededError(subject, value, edge)

    def as_dict(self) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "low_inclusive": self.low_inclusive,
            "high_inclusive": self.high_inclusive,
        }
