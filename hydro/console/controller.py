"""Composition root that wires every control package together."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydro.alarm.service import AlarmService
from hydro.audit.service import AuditService
from hydro.brake.service import BrakeService
from hydro.cooling.service import CoolingService
from hydro.domain.constants import SPEED_BRAKE_THRESHOLD, VIB_RUNOUT_LIMIT
from hydro.domain.errors import ControlError
from hydro.domain.states import can_start
from hydro.exc.service import ExcService
from hydro.gov.service import GovService
from hydro.guide.service import GuideService
from hydro.intake.service import IntakeService
from hydro.interlock.gates import Gate, GateRegistry
from hydro.interlock.latch import Latch
from hydro.judgment.batch import BatchRegistry
from hydro.judgment.history import StateHistory
from hydro.journal.store import KIND_TURBINE
from hydro.runtime.clock import Clock
from hydro.runtime.context import RuntimeContext
from hydro.sched.planner import Planner
from hydro.turbine.service import TurbineService
from hydro.units.registry import UnitRegistry
from hydro.vib.service import VibService

DEFAULT_TTL_TICKS = 1000
DEFAULT_UNITS = (("u1", "unit-1"), ("u2", "unit-2"), ("u3", "unit-3"))


class Controller:
    def __init__(self, data_dir: str | Path, clock: Clock | None = None) -> None:
        self.context = RuntimeContext.build(data_dir, clock)
        ctx = self.context

        self.units = UnitRegistry(ctx.journal)
        self.audit = AuditService(ctx.journal, ctx.ids)
        self.intake = IntakeService(ctx)
        self.cooling = CoolingService(ctx)
        self.history = StateHistory()
        self.batches = BatchRegistry(ctx.store)
        self.alarms = AlarmService(ctx)

        guide_ref: dict[str, GuideService] = {}
        self.guide_latch = Latch(
            "guide",
            ctx.store,
            namespace="latch",
            set_condition=lambda unit_id: guide_ref["svc"].is_open(unit_id),
            release_condition=lambda unit_id: guide_ref["svc"].release_allowed(unit_id),
        )
        self.guide = GuideService(ctx, self.intake, self.audit, self.guide_latch)
        guide_ref["svc"] = self.guide

        self.brake_latch = Latch("brake", ctx.store, namespace="latch")
        self.gov = GovService(ctx, self.intake, self.units)
        self.exc = ExcService(ctx, self.gov)
        self.brake = BrakeService(ctx, self.gov, self.brake_latch)
        self.runner = TurbineService(ctx, self.cooling, self.history)
        self.vib = VibService(ctx, self.runner)

        self.gov.bind_guide(self.guide)
        self.gov.bind_brake(self.brake)
        self.guide.bind_gain(self.gov)
        self.guide.bind_overspeed(lambda unit_id: self.gov.overspeed(unit_id))

        self.gates = GateRegistry()
        self._register_gates()
        self.planner = Planner(self.gates, ctx.store, self.guide)
        self._replay_history()

        from hydro.console.router import build_router

        self.router = build_router()

    def _replay_history(self) -> None:
        """Rebuild the state chain from committed runner records."""

        for record in self.context.journal.records(KIND_TURBINE):
            state = record.payload.get("state")
            if state is None:
                continue
            self.history.record(record.entity, str(state), record.created_tick, "replay")

    # --------------------------------------------------------------- wiring

    def head_persisted(self, unit_id: str) -> bool:
        try:
            self.intake.validate(unit_id)
        except ControlError:
            return False
        return True

    def _register_gates(self) -> None:
        self.gates.register(
            Gate(
                "head-persisted",
                "head must be written to durable storage before the guide opens",
                self.head_persisted,
            )
        )
        self.gates.register(
            Gate("cooling-open", "cooling water must be open", self.cooling.is_open)
        )
        self.gates.register(
            Gate(
                "unit-startable",
                "runner must accept a start command",
                lambda unit_id: can_start(self.runner.state(unit_id)),
            )
        )
        self.gates.register(
            Gate(
                "sync-confirmed",
                "synchroniser confirmation must still be valid",
                lambda unit_id: self.gov.is_sync_confirmed(unit_id, self.context.now()),
            )
        )
        self.gates.register(
            Gate(
                "speed-low",
                "speed must be at or below the threshold",
                self.gov.speed_below_threshold,
            )
        )
        self.gates.register(
            Gate(
                "guide-released",
                "guide latch must be released",
                lambda unit_id: not self.guide.is_latched(unit_id),
            )
        )

    # ------------------------------------------------------------- commands

    def tick(self) -> int:
        return self.context.tick()

    def now(self) -> int:
        return self.context.now()

    def ttl(self, request_ttl: int) -> int:
        return request_ttl if request_ttl > 0 else DEFAULT_TTL_TICKS

    def seed(self) -> dict[str, Any]:
        created: list[str] = []
        for unit_id, name in DEFAULT_UNITS:
            self.units.register(unit_id, name, self.tick())
            self.runner.register(unit_id, self.tick())
            self.intake.set_baseline(unit_id, 60.0, self.tick(), DEFAULT_TTL_TICKS)
            self.gov.recalibrate_oil(unit_id, 80.0, self.tick(), DEFAULT_TTL_TICKS)
            self.gov.set_threshold(unit_id, SPEED_BRAKE_THRESHOLD)
            self.vib.set_limit(unit_id, VIB_RUNOUT_LIMIT, self.tick())
            self.runner.swap_bearing(unit_id, "s1")
            created.append(unit_id)
        self.audit.record("seed", "all", "units registered", self.tick())
        return {"units": created, "tick": self.now()}

    def module_names(self) -> list[str]:
        return [
            "units",
            "intake",
            "guide",
            "cooling",
            "turbine",
            "gov",
            "exc",
            "brake",
            "vib",
            "alarm",
            "audit",
            "journal",
            "versioning",
            "interlock",
            "judgment",
            "sched",
            "store",
            "runtime",
            "console",
        ]
