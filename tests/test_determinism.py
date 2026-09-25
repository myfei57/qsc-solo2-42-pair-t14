"""The same command sequence must always produce the same record stream."""

from __future__ import annotations

from hydro.console.controller import Controller
from hydro.runtime.clock import TickClock


def run_scenario(controller: Controller) -> list[dict]:
    controller.seed()
    controller.cooling.open("u1", controller.tick())
    controller.runner.start("u1", controller.tick())
    controller.guide.open("u1", controller.tick())
    controller.guide.adjust("u1", 42.5, controller.tick())
    controller.gov.sync_confirm("u1", controller.tick(), 500)
    controller.exc.apply("u1", controller.tick())
    controller.gov.set_speed("u1", 25.0)
    controller.brake.engage("u1")
    controller.vib.judge("u1", {"s1": 7.5}, controller.tick())
    controller.alarms.set("u1", "runout", controller.tick())
    controller.batches.open("b1", "u1", "open", controller.tick())
    return [record.to_dict() for record in controller.context.journal.log.all_records()]


def test_two_fresh_controllers_produce_identical_record_streams(tmp_path):
    first = run_scenario(Controller(tmp_path / "a", TickClock()))
    second = run_scenario(Controller(tmp_path / "b", TickClock()))
    assert first == second


def test_record_stream_is_unchanged_by_reopening_the_data_directory(tmp_path):
    before = run_scenario(Controller(tmp_path / "data", TickClock()))
    after = [
        record.to_dict()
        for record in Controller(tmp_path / "data", TickClock()).context.journal.log.all_records()
    ]
    assert after == before


def test_repeated_scenarios_do_not_drift_the_watermark(tmp_path):
    controller = Controller(tmp_path / "data", TickClock())
    run_scenario(controller)
    watermark = controller.context.journal.watermark
    reopened = Controller(tmp_path / "data", TickClock())
    assert reopened.context.journal.watermark == watermark
