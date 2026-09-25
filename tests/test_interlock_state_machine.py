"""Contract C: ordered stages, prerequisite gates and latch conditions."""

from __future__ import annotations

import pytest

from hydro.domain.errors import (
    BrakeLatchedError,
    GateBlockedError,
    GuideLatchedError,
    LatchConditionError,
    OutOfOrderError,
)
from hydro.interlock.gates import Gate, GateRegistry


def run_startup(controller, unit: str = "u1") -> None:
    controller.cooling.open(unit, controller.tick())
    controller.planner.advance("startup", unit, "head-persist", controller.tick())
    controller.planner.advance("startup", unit, "cooling-open", controller.tick())
    controller.planner.advance("startup", unit, "unit-start", controller.tick())
    controller.gov.sync_confirm(unit, controller.tick(), 1000)
    controller.planner.advance("startup", unit, "sync-confirm", controller.tick())
    controller.planner.advance("startup", unit, "excitation", controller.tick())


def test_startup_sequence_advances_in_order(seeded):
    run_startup(seeded)
    assert list(seeded.planner.completed("startup", "u1")) == [
        "head-persist",
        "cooling-open",
        "unit-start",
        "sync-confirm",
        "excitation",
    ]


def test_startup_sequence_rejects_out_of_order_stage(seeded):
    with pytest.raises(OutOfOrderError):
        seeded.planner.advance("startup", "u1", "cooling-open", seeded.tick())


def test_startup_sequence_blocks_when_head_not_persisted(controller):
    controller.units.register("u1", "unit-1", controller.tick())
    blocked = controller.planner.first_blocked("startup", "u1")
    assert blocked is not None and blocked["gate"] == "head-persisted"
    with pytest.raises(GateBlockedError):
        controller.planner.advance("startup", "u1", "head-persist", controller.tick())


def test_startup_sequence_blocks_when_cooling_closed(seeded):
    seeded.planner.advance("startup", "u1", "head-persist", seeded.tick())
    with pytest.raises(GateBlockedError):
        seeded.planner.advance("startup", "u1", "cooling-open", seeded.tick())


def test_startup_excitation_is_blocked_until_sync_confirmed(seeded):
    seeded.cooling.open("u1", seeded.tick())
    for stage in ("head-persist", "cooling-open", "unit-start"):
        seeded.planner.advance("startup", "u1", stage, seeded.tick())
    with pytest.raises(GateBlockedError):
        seeded.planner.advance("startup", "u1", "sync-confirm", seeded.tick())


def test_sequence_is_complete_after_last_stage(seeded):
    run_startup(seeded)
    assert seeded.planner.next_stage("startup", "u1") is None
    with pytest.raises(OutOfOrderError):
        seeded.planner.advance("startup", "u1", "excitation", seeded.tick())


def test_sequence_reset_returns_to_first_stage(seeded):
    run_startup(seeded)
    seeded.planner.reset("startup", "u1")
    assert seeded.planner.next_stage("startup", "u1") == "head-persist"
    assert list(seeded.planner.completed("startup", "u1")) == []


def test_sequence_plan_marks_completed_and_next(seeded):
    seeded.planner.advance("startup", "u1", "head-persist", seeded.tick())
    plan = seeded.planner.plan("startup", "u1")
    assert plan[0]["state"] == "complete"
    assert plan[1]["state"] == "next"
    assert plan[4]["state"] == "pending"
    assert plan[1]["gates"][0]["name"] == "cooling-open"


def test_shutdown_sequence_blocks_when_speed_high(seeded):
    seeded.gov.set_speed("u1", 50.0)
    seeded.planner.advance("shutdown", "u1", "unload", seeded.tick())
    blocked = seeded.planner.first_blocked("shutdown", "u1")
    assert blocked is not None and blocked["gate"] == "speed-low"
    with pytest.raises(GateBlockedError):
        seeded.planner.advance("shutdown", "u1", "speed-drop", seeded.tick())


def test_shutdown_sequence_advances_when_speed_low(seeded):
    seeded.cooling.open("u1", seeded.tick())
    seeded.gov.set_speed("u1", 20.0)
    for stage in ("unload", "speed-drop", "brake-engage", "rundown", "cooling-stop"):
        seeded.planner.advance("shutdown", "u1", stage, seeded.tick())
    assert len(seeded.planner.completed("shutdown", "u1")) == 5


def test_gate_registry_reports_first_unsatisfied():
    gates = GateRegistry()
    gates.register(Gate("ready", "always ready", lambda unit_id: True))
    gates.register(Gate("blocked", "never ready", lambda unit_id: False))
    assert gates.first_unsatisfied("u1", ("ready", "blocked")) == "blocked"
    assert gates.first_unsatisfied("u1", ("ready",)) is None


def test_gate_registry_evaluate_reports_satisfaction():
    gates = GateRegistry()
    gates.register(Gate("open", "valve open", lambda unit_id: unit_id == "u1"))
    report = gates.evaluate("u1", ("open",))
    assert report == [{"name": "open", "description": "valve open", "satisfied": True}]
    assert gates.satisfied("u2", "open") is False


def test_gate_registry_rejects_duplicate_name():
    gates = GateRegistry()
    gates.register(Gate("open", "valve open", lambda unit_id: True))
    with pytest.raises(ValueError):
        gates.register(Gate("open", "duplicate", lambda unit_id: True))


def test_gate_registry_unknown_name_raises_key_error():
    gates = GateRegistry()
    gates.register(Gate("open", "valve open", lambda unit_id: True))
    with pytest.raises(KeyError):
        gates.get("missing")


def test_gate_check_raises_gate_blocked_error():
    gate = Gate("open", "valve must be open", lambda unit_id: False)
    with pytest.raises(GateBlockedError) as info:
        gate.check("u1")
    assert info.value.gate == "open"


def test_guide_latch_requires_open_guide(seeded):
    assert seeded.guide.is_open("u1") is False
    with pytest.raises(LatchConditionError):
        seeded.guide.latch("u1", seeded.tick())


def test_guide_latch_blocks_vane_adjustment(seeded):
    seeded.guide.open("u1", seeded.tick())
    seeded.guide.latch("u1", seeded.tick())
    with pytest.raises(GuideLatchedError):
        seeded.guide.adjust("u1", 40.0, seeded.tick())


def test_dispatch_releases_the_guide_latch(seeded):
    seeded.guide.open("u1", seeded.tick())
    seeded.guide.latch("u1", seeded.tick())
    seeded.gov.dispatch("u1", seeded.tick())
    assert seeded.guide.is_latched("u1") is False
    assert seeded.guide.adjust("u1", 40.0, seeded.tick()) == 40.0


def test_overspeed_sets_the_brake_latch(seeded):
    seeded.gov.set_overspeed("u1", True, seeded.tick())
    assert seeded.gov.overspeed("u1") is True
    assert seeded.brake.is_latched("u1") is True


def test_guide_latch_release_is_blocked_while_overspeed_active(seeded):
    seeded.guide.open("u1", seeded.tick())
    seeded.guide.latch("u1", seeded.tick())
    seeded.gov.set_overspeed("u1", True, seeded.tick())
    with pytest.raises(LatchConditionError):
        seeded.guide.release_latch("u1", seeded.tick())


def test_brake_latch_blocks_resume(seeded):
    seeded.gov.set_speed("u1", 10.0)
    seeded.brake.latch("u1")
    assert seeded.gov.can_resume("u1") is False
    with pytest.raises(BrakeLatchedError):
        seeded.gov.resume("u1")
