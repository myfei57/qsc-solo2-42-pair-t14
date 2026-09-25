"""Restart behaviour: replay from the watermark across every package."""

from __future__ import annotations

import pytest

from hydro.console.controller import Controller
from hydro.runtime.clock import TickClock


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


def open_controller(data_dir) -> Controller:
    return Controller(data_dir, TickClock())


def test_restart_replays_the_committed_head(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.intake.record("u1", 55.0, True, controller.tick())
    assert controller.intake.current_head("u1") == pytest.approx(55.0)
    reopened = open_controller(data_dir)
    assert reopened.intake.current_head("u1") == pytest.approx(55.0)
    assert reopened.intake.head_seq("u1") == 2


def test_restart_drops_the_uncommitted_head(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    pending = controller.context.journal.append(
        "head",
        "u1",
        {"unit_id": "u1", "value": 999.0, "seq": 99, "generation": 9, "created_tick": 1},
    )
    assert pending.seq > controller.context.journal.watermark
    reopened = open_controller(data_dir)
    assert reopened.intake.current_head("u1") == pytest.approx(60.0)
    assert reopened.context.journal.latest("head", "u1")["value"] == pytest.approx(60.0)


def test_restart_keeps_the_unit_registry(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    reopened = open_controller(data_dir)
    assert reopened.units.count() == 3
    assert [unit.id for unit in reopened.units.list()] == ["u1", "u2", "u3"]
    assert reopened.units.name("u2") == "unit-2"


def test_restart_keeps_the_guide_open_state(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.guide.open("u1", controller.tick())
    controller.guide.adjust("u1", 35.0, controller.tick())
    reopened = open_controller(data_dir)
    assert reopened.guide.is_open("u1") is True
    assert reopened.guide.opening("u1") == pytest.approx(35.0)


def test_restart_keeps_sequence_progress(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.planner.advance("startup", "u1", "head-persist", controller.tick())
    reopened = open_controller(data_dir)
    assert list(reopened.planner.completed("startup", "u1")) == ["head-persist"]
    assert reopened.planner.next_stage("startup", "u1") == "cooling-open"


def test_restart_keeps_generation_counters(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.gov.recalibrate_oil("u1", 80.0, controller.tick(), 100)
    controller.gov.recalibrate_oil("u1", 100.0, controller.tick(), 100)
    before = controller.context.generations.current("oil", "u1")
    reopened = open_controller(data_dir)
    assert reopened.context.generations.current("oil", "u1") == before
    assert before == 3


def test_restart_keeps_the_batch_registry(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.batches.open("batch-1", "u1", "open", controller.tick())
    reopened = open_controller(data_dir)
    assert reopened.batches.exists("batch-1") is True
    assert reopened.batches.get("batch-1").unit_id == "u1"


def test_restart_keeps_alarm_state(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.alarms.set("u1", "overspeed", controller.tick())
    reopened = open_controller(data_dir)
    assert reopened.alarms.is_active("u1", "overspeed") is True
    assert reopened.alarms.active_count() == 1


def test_restart_keeps_the_brake_latch(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.gov.set_overspeed("u1", True, controller.tick())
    reopened = open_controller(data_dir)
    assert reopened.brake.is_latched("u1") is True
    assert reopened.gov.overspeed("u1") is True


def test_restart_keeps_the_audit_trail(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.guide.open("u1", controller.tick())
    before = controller.audit.count()
    reopened = open_controller(data_dir)
    assert reopened.audit.count() == before
    assert "guide-open" in reopened.audit.events()


def test_restart_keeps_the_state_history(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.cooling.open("u1", controller.tick())
    controller.runner.start("u1", controller.tick())
    assert controller.history.current("u1").state == "running"
    reopened = open_controller(data_dir)
    current = reopened.history.current("u1")
    assert current is not None and current.state == "running"
    assert "idle" in reopened.history.transitions("u1")


def test_restart_keeps_the_vibration_limit(data_dir):
    controller = open_controller(data_dir)
    controller.seed()
    controller.vib.set_limit("u1", 3.5, controller.tick())
    reopened = open_controller(data_dir)
    assert reopened.vib.limit("u1") == pytest.approx(3.5)
