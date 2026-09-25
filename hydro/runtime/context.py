"""Shared infrastructure handed to every control package."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from hydro.journal.store import RecordStore
from hydro.runtime.clock import Clock, TickClock
from hydro.runtime.ids import IdAllocator
from hydro.store.kv import Store
from hydro.versioning.artifacts import ArtifactLedger
from hydro.versioning.generations import GenerationBook


@dataclasses.dataclass
class RuntimeContext:
    """Bundles the store, clock, journal and versioning primitives."""

    store: Store
    clock: Clock
    journal: RecordStore
    ids: IdAllocator
    generations: GenerationBook
    artifacts: ArtifactLedger

    @classmethod
    def build(cls, root: str | Path, clock: Clock | None = None) -> "RuntimeContext":
        store = Store(root)
        active_clock = clock or TickClock()
        journal = RecordStore(store, namespace="journal", clock=active_clock.now)
        generations = GenerationBook(store)
        artifacts = ArtifactLedger(store, generations)
        ids = IdAllocator(store, "ids/audit", "audit")
        return cls(
            store=store,
            clock=active_clock,
            journal=journal,
            ids=ids,
            generations=generations,
            artifacts=artifacts,
        )

    def tick(self) -> int:
        return self.clock.advance()

    def now(self) -> int:
        return self.clock.now()
