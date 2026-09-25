"""Cross module control chains and their interlocked failure paths."""

from __future__ import annotations

import pytest

from hydro.domain.errors import (
    CoolingClosedError,
    HeadNotPersistedError,
    NoHeadError,
    NotRegisteredError,
    OverspeedActiveError,
    SpeedTooHighError,
    SyncNotConfirmedError,
)
from hydro.domain.states import UnitState


def test_guide_open_requires_a_persisted_head(controller):
    controller.units.register("u1", "unit-1", controller.tick())
    controller.intake.measure("u1", 60.0)
    with pytest.raises(HeadNotPersistedError):
        controller.guide.open("u1", controller.tick())


def test_guide_open_rejects_a_non_positive_persisted_head(controller):
    controller.units.register("u1", "unit-1", controller.tick())
    controller.intake.record("u1", 0.0, True, controller.tick())
    with pytest.raises(NoHeadError):
        controller.guide.open("u1", controller.tick())


def test_guide_open_rejects_a_measurement_that_was_not_persisted(seeded):
    seeded.intake.measure("u1", 70.0)
    with pytest.raises(HeadNotPersistedError):
        seeded.guide.open("u1", seeded.tick())


def test_guide_open_succeeds_with_a_persisted_head(seeded):
    payload = seeded.guide.open("u1", seeded.tick())
    assert payload["open"] is True
    assert payload["applied_head"] == pytest.approx(60.0)


def test_runner_start_is_blocked_when_cooling_is_closed(seeded):
    with pytest.raises(CoolingClosedError):
        seeded.runner.start("u1", seeded.tick())


def test_runner_start_is_allowed_when_cooling_is_open(seeded):
    seeded.cooling.open("u1", seeded.tick())
    assert seeded.runner.start("u1", seeded.tick()) is UnitState.RUNNING


def test_runner_start_is_rejected_from_a_running_state(seeded):
    seeded.cooling.open("u1", seeded.tick())
    seeded.runner.start("u1", seeded.tick())
    with pytest.raises(NotRegisteredError):
        seeded.runner.start("u1", seeded.tick())


def test_excitation_is_blocked_without_a_sync_confirmation(seeded):
    with pytest.raises(SyncNotConfirmedError):
        seeded.exc.apply("u1", seeded.tick())


def test_excitation_is_allowed_with_a_valid_confirmation(seeded):
    seeded.gov.sync_confirm("u1", seeded.tick(), 100)
    assert seeded.exc.apply("u1", seeded.tick()) is True
    assert seeded.exc.is_applied("u1") is True


def test_brake_engage_is_blocked_when_speed_is_above_threshold(seeded):
    seeded.gov.set_speed("u1", 50.0)
    with pytest.raises(SpeedTooHighError):
        seeded.brake.engage("u1")


def test_brake_engage_is_allowed_when_speed_is_low(seeded):
    seeded.gov.set_speed("u1", 20.0)
    assert seeded.brake.engage("u1") is True


def test_cooling_stop_is_blocked_while_speed_is_high(seeded):
    seeded.cooling.open("u1", seeded.tick())
    with pytest.raises(SpeedTooHighError):
        seeded.cooling.stop("u1", 50.0, seeded.tick())
    assert seeded.cooling.is_open("u1") is True


def test_rundown_closes_cooling_only_when_speed_is_low(seeded):
    seeded.cooling.open("u1", seeded.tick())
    seeded.gov.set_speed("u1", 10.0)
    assert seeded.runner.rundown("u1", seeded.tick()) is UnitState.RUNDOWN
    assert seeded.cooling.is_open("u1") is False


def test_overspeed_latches_the_brake_and_blocks_resume(seeded):
    seeded.gov.set_speed("u1", 10.0)
    seeded.gov.set_overspeed("u1", True, seeded.tick())
    assert seeded.gov.can_resume("u1") is False
    with pytest.raises(OverspeedActiveError):
        seeded.gov.resume("u1")


def test_dispatch_is_blocked_while_overspeed_is_active(seeded):
    seeded.gov.set_overspeed("u1", True, seeded.tick())
    with pytest.raises(OverspeedActiveError):
        seeded.gov.dispatch("u1", seeded.tick())


def test_dispatch_rejects_an_unregistered_unit(seeded):
    with pytest.raises(NotRegisteredError):
        seeded.gov.dispatch("ghost", seeded.tick())


def test_recalibration_sets_the_offset_against_the_baseline(seeded):
    offset = seeded.intake.recalibrate("u1", 55.0, seeded.tick(), 1000)
    assert offset == pytest.approx(-5.0)
    assert seeded.intake.baseline("u1") == pytest.approx(60.0)
    assert seeded.intake.head_for_limit("u1") == pytest.approx(55.0)


def test_vibration_runout_is_flagged_above_the_limit(seeded):
    assert seeded.vib.judge("u1", {"s1": 6.0}, seeded.tick()) is True
    assert seeded.vib.runout("u1") is True


def test_vibration_runout_clears_below_the_limit(seeded):
    seeded.vib.judge("u1", {"s1": 6.0}, seeded.tick())
    assert seeded.vib.judge("u1", {"s1": 1.0}, seeded.tick()) is False
    assert seeded.vib.runout("u1") is False


def test_vibration_judgment_requires_the_active_sensor(seeded):
    with pytest.raises(NoHeadError):
        seeded.vib.judge("u1", {"other": 1.0}, seeded.tick())


def test_alarms_raise_and_resolve(seeded):
    seeded.alarms.set("u1", "runout", seeded.tick())
    assert seeded.alarms.is_active("u1", "runout") is True
    assert seeded.alarms.active_count() == 1
    seeded.alarms.resolve("u1", "runout", seeded.tick())
    assert seeded.alarms.is_active("u1", "runout") is False
    assert seeded.alarms.active_kinds() == []


def test_setpoint_is_clamped_to_the_output_limit(seeded):
    limit = seeded.gov.limit("u1", seeded.now())
    assert seeded.gov.setpoint("u1", 1000.0, seeded.now()) == pytest.approx(limit)
    assert seeded.gov.setpoint("u1", 10.0, seeded.now()) == pytest.approx(10.0)


def test_guide_stroke_scales_stroke_by_the_oil_gain(seeded):
    assert seeded.guide.stroke("u1", 10.0, seeded.now()) == pytest.approx(20.0)


def test_limit_status_is_full_for_a_high_head(seeded):
    assert seeded.gov.limit_status("u1", seeded.now()) == "full"
    assert seeded.gov.output_status("u1", seeded.now()) == "limited"


def test_pressure_head_conversion_rejects_zero_density(seeded):
    assert seeded.intake.pressure_head(64.0, 2.0) == pytest.approx(32.0)
    with pytest.raises(NoHeadError):
        seeded.intake.pressure_head(64.0, 0.0)


def test_audit_collects_events_from_the_control_chain(seeded):
    seeded.guide.open("u1", seeded.tick())
    seeded.guide.close("u1", seeded.tick())
    events = seeded.audit.events()
    assert "guide-open" in events
    assert "guide-close" in events
    assert seeded.audit.count() >= 3
