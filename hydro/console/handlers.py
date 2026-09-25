"""Request handlers for every console route."""

from __future__ import annotations

from typing import Any

from hydro.console.http import Request, Response, bad_request, not_found, ok
from hydro.domain.errors import ControlError
from hydro.judgment.query import RecordQuery
from hydro.versioning.generations import SCOPE_CONFIRM, SCOPE_OIL

BIG_TICK = 1 << 30


class HandlerSet:
    """Stateless dispatcher around a :class:`Controller`."""

    # -------------------------------------------------------------- meta

    def health(self, c: Any, request: Request) -> Response:
        return ok(
            {
                "status": "ok",
                "units": c.units.count(),
                "audit_events": c.audit.count(),
                "alarms": c.alarms.active_count(),
                "cooling_open": c.cooling.open_units(c.units.ids()),
                "watermark": c.context.journal.watermark,
            }
        )

    def meta(self, c: Any, request: Request) -> Response:
        return ok(
            {
                "modules": c.module_names(),
                "unit_count": c.units.count(),
                "store_dir": str(c.context.store.root),
                "watermark": c.context.journal.watermark,
                "routes": c.router.count(),
                "tick": c.now(),
            }
        )

    def routes(self, c: Any, request: Request) -> Response:
        return ok({"routes": c.router.routes()})

    def units(self, c: Any, request: Request) -> Response:
        return ok({"units": [unit.as_dict() for unit in c.units.list()], "tick": c.now()})

    # ------------------------------------------------------------- queries

    def state(self, c: Any, request: Request) -> Response:
        now = c.now()
        out: list[dict[str, Any]] = []
        for unit in c.units.list():
            uid = unit.id
            try:
                limit = c.gov.limit(uid, now)
                output_status = "limited" if limit > 0 else "no-head"
                limit_status = c.gov.limit_status(uid, now)
                margin = c.gov.margin(uid, limit, now)
            except ControlError as error:
                limit = None
                output_status = error.code
                limit_status = error.code
                margin = None
            out.append(
                {
                    "id": uid,
                    "name": c.units.name(uid),
                    "state": c.runner.state(uid).value,
                    "running": c.runner.is_running(uid),
                    "start_ready": c.runner.start_ready(uid),
                    "speed_band": c.runner.speed_band(uid),
                    "head": c.intake.latest(uid),
                    "head_persisted": c.head_persisted(uid),
                    "head_state": c.intake.head_state(uid),
                    "head_generation": c.intake.head_generation(uid),
                    "baseline": c.intake.baseline(uid),
                    "offset": c.intake.offset(uid),
                    "cooling_open": c.cooling.is_open(uid),
                    "cooling_flow": c.cooling.flow(uid),
                    "cooling_held": c.runner.cooling_held(uid),
                    "sync_state": c.gov.sync_state(uid, now),
                    "speed": c.runner.speed(uid),
                    "high_speed": c.runner.above_stop_threshold(uid),
                    "brake_engaged": c.brake.is_engaged(uid),
                    "brake_latched": c.brake.is_latched(uid),
                    "excitation": c.exc.is_applied(uid),
                    "breaker_closed": c.exc.breaker_closed(uid),
                    "guide_open": c.guide.is_open(uid),
                    "guide_state": c.guide.open_state(uid),
                    "guide_opening": c.guide.opening(uid),
                    "guide_percent": c.guide.opening_percent(uid),
                    "guide_latched": c.guide.is_latched(uid),
                    "guide_stroke": c.guide.last_stroke(uid),
                    "overspeed": c.gov.overspeed(uid),
                    "runout": c.vib.runout(uid),
                    "vib_sensor": c.vib.active_sensor(uid),
                    "oil_gain": c.gov.oil_gain(uid, now),
                    "oil_pressure": c.gov.oil_pressure(uid),
                    "output_limit": limit,
                    "output_status": output_status,
                    "limit_status": limit_status,
                    "margin": margin,
                    "dispatch_state": c.gov.dispatch_state(uid, now),
                    "resume_allowed": c.gov.can_resume(uid),
                    "vib_limit": c.vib.limit(uid),
                    "brake_threshold": c.gov.threshold(uid),
                    "alarms": [
                        alarm.kind for alarm in c.alarms.by_unit(uid) if alarm.active
                    ],
                    "generations": c.context.generations.snapshot(uid),
                }
            )
        return ok({"units": out, "tick": now})

    def audit(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        event = request.text("event")
        tick_from = request.integer("tick_from", -1)
        tick_to = request.integer("tick_to", -1)
        limit = request.integer("limit", 50)
        query = RecordQuery(
            kinds=(event,) if event else None,
            entities=(unit_id,) if unit_id else None,
            tick_from=tick_from if tick_from >= 0 else None,
            tick_to=tick_to if tick_to >= 0 else None,
            limit=limit,
            newest_first=request.text("order") == "desc",
        )
        if event or tick_from >= 0 or tick_to >= 0 or query.newest_first:
            records = c.audit.query(query)
        elif unit_id:
            records = c.audit.by_unit(unit_id, limit)
        else:
            records = c.audit.recent(limit)
        return ok(
            {
                "records": [record.as_dict() for record in records],
                "events": c.audit.events(),
                "count": c.audit.count(),
                "filter": query.describe(),
                "tick": c.now(),
            }
        )

    def alarms(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        records = c.alarms.by_unit(unit_id) if unit_id else c.alarms.list()
        return ok(
            {
                "unit_id": unit_id,
                "alarms": [alarm.as_dict() for alarm in records],
                "active_kinds": c.alarms.active_kinds(),
                "active_count": c.alarms.active_count(),
                "count": c.alarms.count(),
            }
        )

    def history(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        tick = request.integer("tick", -1)
        end = BIG_TICK if tick < 0 else tick
        current = c.history.current(unit_id)
        at = c.history.at(unit_id, tick) if tick >= 0 else None
        return ok(
            {
                "unit_id": unit_id,
                "current": current.as_dict() if current else None,
                "at": at.as_dict() if at else None,
                "entries": [entry.as_dict() for entry in c.history.between(unit_id, 0, end)],
                "transitions": c.history.transitions(unit_id),
                "changed": c.history.changed_between(unit_id, 0, end),
                "length": c.history.length(unit_id),
                "units": c.history.units(),
            }
        )

    # ---------------------------------------------------------- scheduling

    def sched_plan(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        name = request.text("sequence", "startup")
        blocked = c.planner.first_blocked(name, unit_id)
        return ok(
            {
                "unit_id": unit_id,
                "sequence": name,
                "ready": blocked is None,
                "blocked": blocked,
                "next_stage": c.planner.next_stage(name, unit_id),
                "completed": list(c.planner.completed(name, unit_id)),
                "complete": c.planner.is_complete(name, unit_id),
                "stages": c.planner.stage_names(name),
                "plan": c.planner.plan(name, unit_id),
                "guide_released": c.planner.guide_released(unit_id),
                "guide_opened": c.planner.guide_opened(unit_id),
            }
        )

    def sched_blocked(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "startup_ready": c.planner.startup_ready(unit_id),
                "shutdown_ready": c.planner.shutdown_ready(unit_id),
                "startup_blocked": c.planner.first_blocked("startup", unit_id),
                "shutdown_blocked": c.planner.first_blocked("shutdown", unit_id),
                "gates": c.gates.evaluate(
                    unit_id,
                    ("head-persisted", "cooling-open", "unit-startable"),
                ),
            }
        )

    def sched_advance(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        name = request.text("sequence", "startup")
        stage = request.text("stage")
        advanced = c.planner.advance(name, unit_id, stage, c.tick())
        c.audit.record(
            "stage-" + name, unit_id, "advanced stage " + advanced.name, c.tick()
        )
        return ok(
            {
                "unit_id": unit_id,
                "sequence": name,
                "stage": advanced.name,
                "completed": list(c.planner.completed(name, unit_id)),
            }
        )

    # --------------------------------------------------------------- views

    def guide_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "open": c.guide.is_open(unit_id),
                "state": c.guide.open_state(unit_id),
                "opening": c.guide.opening(unit_id),
                "percent": c.guide.opening_percent(unit_id),
                "applied_head": c.guide.applied_head(unit_id),
                "last_stroke": c.guide.last_stroke(unit_id),
                "latched": c.guide.is_latched(unit_id),
            }
        )

    def cooling_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "open": c.cooling.is_open(unit_id),
                "flow": c.cooling.flow(unit_id),
            }
        )

    def runner_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "state": c.runner.state(unit_id).value,
                "running": c.runner.is_running(unit_id),
                "start_ready": c.runner.start_ready(unit_id),
                "speed": c.runner.speed(unit_id),
                "band": c.runner.speed_band(unit_id),
                "above_stop": c.runner.above_stop_threshold(unit_id),
                "cooling_held": c.runner.cooling_held(unit_id),
                "sensor": c.runner.bearing_sensor(unit_id),
                "sensors": c.runner.sensors(unit_id),
            }
        )

    def gov_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        now = c.now()
        confirmation = c.gov.sync_confirmation(unit_id)
        return ok(
            {
                "unit_id": unit_id,
                "sync_state": c.gov.sync_state(unit_id, now),
                "sync_confirmation": confirmation.as_dict() if confirmation else None,
                "sync_generation": c.context.generations.current(SCOPE_CONFIRM, unit_id),
                "overspeed": c.gov.overspeed(unit_id),
                "speed": c.gov.speed(unit_id),
                "speed_below_threshold": c.gov.speed_below_threshold(unit_id),
                "threshold": c.gov.threshold(unit_id),
                "oil_gain": c.gov.oil_gain(unit_id, now),
                "oil_pressure": c.gov.oil_pressure(unit_id),
                "oil_generation": c.context.generations.current(SCOPE_OIL, unit_id),
                "can_resume": c.gov.can_resume(unit_id),
                "dispatch_state": c.gov.dispatch_state(unit_id, now),
            }
        )

    def gov_limit(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        now = c.now()
        head = c.gov.head_used(unit_id)
        payload: dict[str, Any] = {
            "unit_id": unit_id,
            "head": head,
            "limit_for": c.gov.limit_for(head),
            "status": c.gov.limit_status(unit_id, now),
            "output_status": c.gov.output_status(unit_id, now),
        }
        try:
            limit = c.gov.limit(unit_id, now)
            payload["limit"] = limit
            payload["margin"] = c.gov.margin(unit_id, limit, now)
        except ControlError as error:
            payload["limit"] = None
            payload["margin"] = None
            payload["error"] = error.message
            payload["code"] = error.code
        return ok(payload)

    def exc_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "applied": c.exc.is_applied(unit_id),
                "breaker_closed": c.exc.breaker_closed(unit_id),
                "sync_state": c.gov.sync_state(unit_id, c.now()),
            }
        )

    def brake_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "engaged": c.brake.is_engaged(unit_id),
                "latched": c.brake.is_latched(unit_id),
            }
        )

    def intake_head(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        try:
            head = c.intake.current_head(unit_id)
        except ControlError as error:
            return not_found(error.message)
        return ok(
            {
                "unit_id": unit_id,
                "head": head,
                "seq": c.intake.head_seq(unit_id),
                "generation": c.intake.head_generation(unit_id),
                "state": c.intake.head_state(unit_id),
            }
        )

    def intake_baseline(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        now = c.now()
        payload: dict[str, Any] = {
            "unit_id": unit_id,
            "baseline": c.intake.baseline(unit_id),
            "offset": c.intake.offset(unit_id),
            "head_for_limit": c.intake.head_for_limit(unit_id),
            "calibrated_at": c.intake.calibrated_at(unit_id),
            "meta": c.intake.baseline_meta(unit_id),
        }
        try:
            c.intake.validate_baseline(unit_id, now)
            payload["valid"] = True
        except ControlError as error:
            payload["valid"] = False
            payload["code"] = error.code
        return ok(payload)

    def vib_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        payload: dict[str, Any] = {
            "unit_id": unit_id,
            "limit": c.vib.limit(unit_id),
            "generation": c.vib.limit_generation(unit_id),
            "threshold": c.vib.threshold(unit_id).as_dict(),
            "band": c.vib.band(unit_id).as_dict(),
            "runout": c.vib.runout(unit_id),
            "sensor": c.vib.active_sensor(unit_id),
            "sensors": c.vib.sensor_list(unit_id),
        }
        try:
            snapshot = c.vib.validate_limit_snapshot(unit_id)
            payload["snapshot"] = snapshot.as_dict()
            payload["snapshot_valid"] = True
        except ControlError as error:
            payload["snapshot"] = None
            payload["snapshot_valid"] = False
            payload["snapshot_code"] = error.code
        return ok(payload)

    def vib_sensor(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        return ok(
            {
                "unit_id": unit_id,
                "sensor": c.vib.refresh(unit_id),
                "sensors": c.vib.sensor_list(unit_id),
                "bearing": c.runner.bearing_sensor(unit_id),
                "all": c.runner.sensors(unit_id),
            }
        )

    def batch_view(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        batches = c.batches.by_unit(unit_id) if unit_id else c.batches.all()
        return ok(
            {
                "unit_id": unit_id,
                "batches": [batch.as_dict() for batch in batches],
                "count": c.batches.count(),
            }
        )

    # ------------------------------------------------------------- commands

    def guide_open(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        payload = c.guide.open(unit_id, c.tick())
        return ok({"unit_id": unit_id, "open": payload["open"], "head": payload["applied_head"]})

    def guide_restore(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        payload = c.guide.restore(unit_id, c.tick())
        return ok({"unit_id": unit_id, "open": payload["open"], "head": payload["applied_head"]})

    def guide_stroke(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        stroke = c.guide.stroke(unit_id, request.number("value"), c.now())
        return ok(
            {
                "unit_id": unit_id,
                "stroke": stroke,
                "last": c.guide.last_stroke(unit_id),
            }
        )

    def guide_close(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        payload = c.guide.close(unit_id, c.tick())
        return ok({"unit_id": unit_id, "open": payload["open"]})

    def guide_adjust(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        opening = c.guide.adjust(unit_id, request.number("value"), c.tick())
        return ok({"unit_id": unit_id, "opening": opening})

    def guide_latch(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.guide.latch(unit_id, c.tick())
        return ok({"unit_id": unit_id, "latched": c.guide.is_latched(unit_id)})

    def guide_release_latch(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.guide.release_latch(unit_id, c.tick())
        return ok({"unit_id": unit_id, "latched": c.guide.is_latched(unit_id)})

    def cooling_open(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.cooling.open(unit_id, c.tick())
        return ok({"unit_id": unit_id, "open": c.cooling.is_open(unit_id)})

    def cooling_stop(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        speed = request.number("value", c.runner.speed(unit_id))
        c.cooling.stop(unit_id, speed, c.tick())
        return ok({"unit_id": unit_id, "open": c.cooling.is_open(unit_id)})

    def runner_start(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        state = c.runner.start(unit_id, c.tick())
        return ok({"unit_id": unit_id, "state": state.value})

    def runner_hot_start(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        state = c.runner.start_hot(unit_id, c.tick())
        return ok({"unit_id": unit_id, "state": state.value})

    def runner_stop(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        state = c.runner.stop(unit_id, c.tick())
        return ok({"unit_id": unit_id, "state": state.value})

    def runner_rundown(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        state = c.runner.rundown(unit_id, c.tick())
        return ok({"unit_id": unit_id, "state": state.value})

    def runner_trip(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        state = c.runner.trip(unit_id, c.tick())
        return ok({"unit_id": unit_id, "state": state.value})

    def runner_reset(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        state = c.runner.reset(unit_id, c.tick())
        return ok({"unit_id": unit_id, "state": state.value})

    def runner_speed(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        value = c.runner.set_speed(unit_id, request.number("value"))
        return ok({"unit_id": unit_id, "speed": value, "band": c.runner.speed_band(unit_id)})

    def runner_swap_bearing(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        sensor = request.text("sensor_id")
        if not sensor:
            return bad_request("sensor_id is required")
        c.runner.swap_bearing(unit_id, sensor)
        return ok({"unit_id": unit_id, "sensor": c.runner.bearing_sensor(unit_id)})

    def gov_sync(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        confirmation = c.gov.sync_confirm(unit_id, c.tick(), c.ttl(request.integer("ttl", 0)))
        return ok(
            {
                "unit_id": unit_id,
                "sync_confirmed": c.gov.is_sync_confirmed(unit_id, c.now()),
                "confirmation": confirmation.as_dict(),
            }
        )

    def gov_reset_sync(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.gov.reset_sync(unit_id)
        return ok({"unit_id": unit_id, "sync_state": c.gov.sync_state(unit_id, c.now())})

    def gov_speed(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        value = c.gov.set_speed(unit_id, request.number("value"))
        return ok(
            {
                "unit_id": unit_id,
                "speed": value,
                "below_threshold": c.gov.speed_below_threshold(unit_id),
            }
        )

    def gov_threshold(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        value = c.gov.set_threshold(unit_id, request.number("value"))
        return ok({"unit_id": unit_id, "threshold": value})

    def gov_dispatch(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.gov.dispatch(unit_id, c.tick())
        return ok({"unit_id": unit_id, "latched": c.guide.is_latched(unit_id)})

    def gov_recalibrate_oil(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        gain = c.gov.recalibrate_oil(
            unit_id, request.number("value"), c.tick(), c.ttl(request.integer("ttl", 0))
        )
        return ok(
            {
                "unit_id": unit_id,
                "gain": gain,
                "pressure": c.gov.oil_pressure(unit_id),
            }
        )

    def gov_overspeed(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.gov.set_overspeed(unit_id, True, c.tick())
        c.alarms.set(unit_id, "overspeed", c.tick())
        return ok(
            {
                "unit_id": unit_id,
                "overspeed": c.gov.overspeed(unit_id),
                "brake_latched": c.brake.is_latched(unit_id),
            }
        )

    def gov_clear_overspeed(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.gov.clear_overspeed(unit_id, c.tick())
        c.alarms.resolve(unit_id, "overspeed", c.tick())
        return ok(
            {
                "unit_id": unit_id,
                "overspeed": c.gov.overspeed(unit_id),
                "brake_latched": c.brake.is_latched(unit_id),
            }
        )

    def gov_resume(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.gov.resume(unit_id)
        return ok({"unit_id": unit_id, "can_resume": c.gov.can_resume(unit_id)})

    def gov_setpoint(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        setpoint = c.gov.setpoint(unit_id, request.number("value"), c.now())
        return ok({"unit_id": unit_id, "setpoint": setpoint})

    def gov_guard(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.gov.guard(unit_id)
        return ok({"unit_id": unit_id, "guarded": True})

    def exc_apply(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.exc.apply(unit_id, c.tick())
        return ok({"unit_id": unit_id, "applied": c.exc.is_applied(unit_id)})

    def exc_apply_retry(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.exc.apply_retry(unit_id, c.tick())
        return ok({"unit_id": unit_id, "applied": c.exc.is_applied(unit_id)})

    def exc_reset(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.exc.reset(unit_id)
        return ok({"unit_id": unit_id, "applied": c.exc.is_applied(unit_id)})

    def exc_breaker(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.exc.close_breaker(unit_id)
        return ok({"unit_id": unit_id, "breaker_closed": c.exc.breaker_closed(unit_id)})

    def exc_trip(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.exc.trip_breaker(unit_id)
        return ok({"unit_id": unit_id, "breaker_closed": c.exc.breaker_closed(unit_id)})

    def brake_engage(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.brake.engage(unit_id)
        return ok({"unit_id": unit_id, "engaged": c.brake.is_engaged(unit_id)})

    def brake_emergency(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.brake.engage_emergency(unit_id)
        return ok(
            {
                "unit_id": unit_id,
                "engaged": c.brake.is_engaged(unit_id),
                "latched": c.brake.is_latched(unit_id),
            }
        )

    def brake_release(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.brake.release(unit_id)
        return ok({"unit_id": unit_id, "engaged": c.brake.is_engaged(unit_id)})

    def brake_reset(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        c.brake.reset(unit_id)
        return ok(
            {
                "unit_id": unit_id,
                "engaged": c.brake.is_engaged(unit_id),
                "latched": c.brake.is_latched(unit_id),
            }
        )

    def intake_measure(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        head = c.intake.record(unit_id, request.number("value"), True, c.tick())
        return ok(
            {
                "unit_id": unit_id,
                "head": head.value if head else c.intake.latest(unit_id),
                "seq": c.intake.head_seq(unit_id),
                "persisted": c.intake.head_state(unit_id) == "persisted",
            }
        )

    def intake_recalibrate(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        offset = c.intake.recalibrate(
            unit_id, request.number("value"), c.tick(), c.ttl(request.integer("ttl", 0))
        )
        return ok(
            {
                "unit_id": unit_id,
                "offset": offset,
                "baseline": c.intake.baseline(unit_id),
                "head_for_limit": c.intake.head_for_limit(unit_id),
                "calibrated_at": c.intake.calibrated_at(unit_id),
            }
        )

    def intake_convert(self, c: Any, request: Request) -> Response:
        head = c.intake.pressure_head(request.number("pressure"), request.number("density"))
        return ok({"head": head})

    def vib_judge(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        runout = c.vib.judge(unit_id, request.raw_map(), c.tick())
        if runout:
            c.alarms.set(unit_id, "runout", c.tick())
        else:
            c.alarms.resolve(unit_id, "runout", c.tick())
        return ok(
            {
                "unit_id": unit_id,
                "runout": runout,
                "sensor": c.vib.active_sensor(unit_id),
                "limit": c.vib.limit(unit_id),
            }
        )

    def vib_limit(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        snapshot = c.vib.set_limit(unit_id, request.number("value"), c.tick())
        return ok(
            {
                "unit_id": unit_id,
                "limit": c.vib.limit(unit_id),
                "generation": c.vib.limit_generation(unit_id),
                "snapshot": snapshot.as_dict(),
            }
        )

    def batch_open(self, c: Any, request: Request) -> Response:
        unit_id = request.unit_id()
        batch = c.batches.open(
            request.text("batch_id"), unit_id, request.text("stage", "open"), c.tick()
        )
        return ok({"batch": batch.as_dict(), "count": c.batches.count()})

    def batch_advance(self, c: Any, request: Request) -> Response:
        batch = c.batches.advance(request.text("batch_id"), request.text("stage"))
        return ok({"batch": batch.as_dict(), "count": c.batches.count()})
