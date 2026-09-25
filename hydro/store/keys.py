"""Canonical key names for durable controller state."""


def head_key(unit_id: str) -> str:
    return "head/" + unit_id


def gate_key(unit_id: str) -> str:
    return "gate/" + unit_id


def cooling_key(unit_id: str) -> str:
    return "cooling/" + unit_id


def sync_key(unit_id: str) -> str:
    return "sync/" + unit_id


def gain_key(unit_id: str) -> str:
    return "gain/" + unit_id


def offset_key(unit_id: str) -> str:
    return "offset/" + unit_id


def state_key(unit_id: str) -> str:
    return "state/" + unit_id


def sensor_key(unit_id: str) -> str:
    return "sensor/" + unit_id


def brake_key(unit_id: str) -> str:
    return "brake/" + unit_id


def exc_key(unit_id: str) -> str:
    return "exc/" + unit_id


def unit_key(unit_id: str) -> str:
    return "units/" + unit_id


def audit_key(record_id: str) -> str:
    return "audit/" + record_id


def threshold_key(unit_id: str) -> str:
    return "threshold/" + unit_id


def limit_key(unit_id: str) -> str:
    return "vib-limit/" + unit_id


def alarm_key(unit_id: str, kind: str) -> str:
    return "alarm/" + unit_id + "/" + kind


def dispatch_key(unit_id: str) -> str:
    return "dispatch/" + unit_id


def latch_key(unit_id: str) -> str:
    return "brake-latch/" + unit_id


def generation_key(scope: str, unit_id: str) -> str:
    return "generation/" + scope + "/" + unit_id


def baseline_key(scope: str, unit_id: str) -> str:
    return "baseline/" + scope + "/" + unit_id


def snapshot_key(scope: str, unit_id: str) -> str:
    return "snapshot/" + scope + "/" + unit_id


def confirmation_key(scope: str, unit_id: str) -> str:
    return "confirmation/" + scope + "/" + unit_id
