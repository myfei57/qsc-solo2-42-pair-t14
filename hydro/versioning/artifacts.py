"""Confirmations, snapshots and baselines that carry a generation number."""

from __future__ import annotations

import dataclasses
from typing import Any

from hydro.domain.errors import ExpiredArtifactError, NotFoundError, StaleGenerationError
from hydro.store.keys import baseline_key, confirmation_key, snapshot_key
from hydro.store.kv import Store
from hydro.versioning.generations import GenerationBook


@dataclasses.dataclass(frozen=True)
class Confirmation:
    """A short lived permission slip bound to a generation and a tick budget."""

    unit_id: str
    scope: str
    generation: int
    issued_tick: int
    ttl_ticks: int

    @property
    def expires_at(self) -> int:
        return self.issued_tick + self.ttl_ticks

    def is_expired(self, now: int) -> bool:
        return now > self.expires_at

    def validate(self, book: GenerationBook, now: int) -> None:
        if self.generation != book.current(self.scope, self.unit_id):
            raise StaleGenerationError(
                "confirmation for {} scope {} is generation {}, current is {}".format(
                    self.unit_id, self.scope, self.generation, book.current(self.scope, self.unit_id)
                )
            )
        if self.is_expired(now):
            raise ExpiredArtifactError(
                "confirmation for {} scope {} expired at {} (now {})".format(
                    self.unit_id, self.scope, self.expires_at, now
                )
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "scope": self.scope,
            "generation": self.generation,
            "issued_tick": self.issued_tick,
            "ttl_ticks": self.ttl_ticks,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Confirmation":
        return cls(
            unit_id=str(data["unit_id"]),
            scope=str(data["scope"]),
            generation=int(data["generation"]),
            issued_tick=int(data["issued_tick"]),
            ttl_ticks=int(data["ttl_ticks"]),
        )


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """A frozen copy of a parameter set at a known generation."""

    unit_id: str
    scope: str
    generation: int
    payload: dict[str, Any]
    created_tick: int

    def is_stale(self, book: GenerationBook) -> bool:
        return self.generation < book.current(self.scope, self.unit_id)

    def validate(self, book: GenerationBook) -> None:
        if self.is_stale(book):
            raise StaleGenerationError(
                "snapshot for {} scope {} is generation {}".format(
                    self.unit_id, self.scope, self.generation
                )
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "scope": self.scope,
            "generation": self.generation,
            "payload": self.payload,
            "created_tick": self.created_tick,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        return cls(
            unit_id=str(data["unit_id"]),
            scope=str(data["scope"]),
            generation=int(data["generation"]),
            payload=dict(data.get("payload") or {}),
            created_tick=int(data.get("created_tick", 0)),
        )


@dataclasses.dataclass(frozen=True)
class Baseline:
    """A calibration baseline that expires after a number of ticks."""

    unit_id: str
    scope: str
    generation: int
    value: float
    created_tick: int
    ttl_ticks: int

    @property
    def expires_at(self) -> int:
        return self.created_tick + self.ttl_ticks

    def is_expired(self, now: int) -> bool:
        return now > self.expires_at

    def is_stale(self, book: GenerationBook) -> bool:
        return self.generation != book.current(self.scope, self.unit_id)

    def validate(self, book: GenerationBook, now: int) -> None:
        if self.is_stale(book):
            raise StaleGenerationError(
                "baseline for {} scope {} is generation {}, current is {}".format(
                    self.unit_id,
                    self.scope,
                    self.generation,
                    book.current(self.scope, self.unit_id),
                )
            )
        if self.is_expired(now):
            raise ExpiredArtifactError(
                "baseline for {} scope {} expired at {} (now {})".format(
                    self.unit_id, self.scope, self.expires_at, now
                )
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "scope": self.scope,
            "generation": self.generation,
            "value": self.value,
            "created_tick": self.created_tick,
            "ttl_ticks": self.ttl_ticks,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Baseline":
        return cls(
            unit_id=str(data["unit_id"]),
            scope=str(data["scope"]),
            generation=int(data["generation"]),
            value=float(data["value"]),
            created_tick=int(data.get("created_tick", 0)),
            ttl_ticks=int(data.get("ttl_ticks", 0)),
        )


class ArtifactLedger:
    """Issues and validates generation bound artifacts."""

    def __init__(self, store: Store, book: GenerationBook) -> None:
        self._store = store
        self._book = book

    @property
    def book(self) -> GenerationBook:
        return self._book

    def issue_confirmation(
        self, unit_id: str, scope: str, ttl_ticks: int, now: int
    ) -> Confirmation:
        if ttl_ticks <= 0:
            raise ValueError("ttl_ticks must be positive")
        confirmation = Confirmation(
            unit_id=unit_id,
            scope=scope,
            generation=self._book.current(scope, unit_id),
            issued_tick=now,
            ttl_ticks=ttl_ticks,
        )
        self._store.write_json(confirmation_key(scope, unit_id), confirmation.as_dict())
        return confirmation

    def load_confirmation(self, unit_id: str, scope: str) -> Confirmation:
        data = self._store.read_json(confirmation_key(scope, unit_id))
        if data is None:
            raise NotFoundError("confirmation not found for {} scope {}".format(unit_id, scope))
        return Confirmation.from_dict(data)

    def validate_confirmation(self, confirmation: Confirmation, now: int) -> None:
        confirmation.validate(self._book, now)

    def take_snapshot(
        self, unit_id: str, scope: str, payload: dict[str, Any], now: int
    ) -> Snapshot:
        snapshot = Snapshot(
            unit_id=unit_id,
            scope=scope,
            generation=self._book.current(scope, unit_id),
            payload=dict(payload),
            created_tick=now,
        )
        self._store.write_json(snapshot_key(scope, unit_id), snapshot.as_dict())
        return snapshot

    def latest_snapshot(self, unit_id: str, scope: str) -> Snapshot:
        data = self._store.read_json(snapshot_key(scope, unit_id))
        if data is None:
            raise NotFoundError("snapshot not found for {} scope {}".format(unit_id, scope))
        return Snapshot.from_dict(data)

    def publish_baseline(
        self, unit_id: str, scope: str, value: float, ttl_ticks: int, now: int
    ) -> Baseline:
        if ttl_ticks <= 0:
            raise ValueError("ttl_ticks must be positive")
        generation = self._book.bump(scope, unit_id)
        baseline = Baseline(
            unit_id=unit_id,
            scope=scope,
            generation=generation,
            value=float(value),
            created_tick=now,
            ttl_ticks=ttl_ticks,
        )
        self._store.write_json(baseline_key(scope, unit_id), baseline.as_dict())
        return baseline

    def load_baseline(self, unit_id: str, scope: str) -> Baseline:
        data = self._store.read_json(baseline_key(scope, unit_id))
        if data is None:
            raise NotFoundError(
                "baseline not found for {} scope {}".format(unit_id, scope)
            )
        return Baseline.from_dict(data)
