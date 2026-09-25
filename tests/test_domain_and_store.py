"""Domain constants, state machine helpers and storage primitives."""

from __future__ import annotations

import pytest

from hydro.domain.errors import NotFoundError
from hydro.domain.states import UnitState, can_start, can_stop, next_state
from hydro.runtime.clock import TickClock, format_stamp
from hydro.runtime.ids import IdAllocator
from hydro.store.kv import Store


def test_can_start_allows_idle_stopping_and_rundown():
    assert can_start(UnitState.IDLE) is True
    assert can_start(UnitState.STOPPING) is True
    assert can_start(UnitState.RUNDOWN) is True
    assert can_start(UnitState.RUNNING) is False
    assert can_start(UnitState.TRIPPED) is False


def test_can_stop_allows_running_and_starting():
    assert can_stop(UnitState.RUNNING) is True
    assert can_stop(UnitState.STARTING) is True
    assert can_stop(UnitState.IDLE) is False


def test_next_state_maps_every_action():
    assert next_state(UnitState.IDLE, "start") is UnitState.RUNNING
    assert next_state(UnitState.RUNNING, "stop") is UnitState.STOPPING
    assert next_state(UnitState.STOPPING, "rundown") is UnitState.RUNDOWN
    assert next_state(UnitState.RUNNING, "trip") is UnitState.TRIPPED
    assert next_state(UnitState.TRIPPED, "reset") is UnitState.IDLE


def test_next_state_keeps_current_state_for_unknown_action():
    assert next_state(UnitState.RUNNING, "pause") is UnitState.RUNNING


def test_store_json_roundtrip(tmp_path):
    store = Store(tmp_path / "kv")
    store.write_json("head/u1", {"value": 60.0, "seq": 1})
    assert store.read_json("head/u1") == {"value": 60.0, "seq": 1}


def test_store_missing_key_raises_not_found(tmp_path):
    store = Store(tmp_path / "kv")
    with pytest.raises(NotFoundError):
        store.read_bytes("missing/key")
    assert store.read_json("missing/key") is None
    assert store.read_json("missing/key", default={"value": 0}) == {"value": 0}


def test_store_list_keys_filters_by_prefix(tmp_path):
    store = Store(tmp_path / "kv")
    store.write_json("head/u1", 1)
    store.write_json("head/u2", 2)
    store.write_json("gate/u1", True)
    assert store.list_keys("head/") == ["head/u1", "head/u2"]
    assert store.list_keys() == ["gate/u1", "head/u1", "head/u2"]


def test_store_remove_deletes_the_key(tmp_path):
    store = Store(tmp_path / "kv")
    store.write_json("gate/u1", True)
    assert store.exists("gate/u1") is True
    store.remove("gate/u1")
    assert store.exists("gate/u1") is False


def test_store_int_helpers_use_defaults(tmp_path):
    store = Store(tmp_path / "kv")
    assert store.read_int("counter", default=7) == 7
    store.write_int("counter", 12)
    assert store.read_int("counter") == 12


def test_id_allocator_is_sequential(tmp_path):
    store = Store(tmp_path / "kv")
    allocator = IdAllocator(store, "ids/audit", "audit")
    assert allocator.next() == "audit-000001"
    assert allocator.next() == "audit-000002"
    assert allocator.current() == 2


def test_id_allocator_continues_after_reopen(tmp_path):
    store = Store(tmp_path / "kv")
    IdAllocator(store, "ids/audit", "audit").next()
    reopened = IdAllocator(store, "ids/audit", "audit")
    assert reopened.next() == "audit-000002"


def test_id_allocator_reset_restarts_the_sequence(tmp_path):
    store = Store(tmp_path / "kv")
    allocator = IdAllocator(store, "ids/audit", "audit")
    allocator.next()
    allocator.reset()
    assert allocator.next() == "audit-000001"


def test_tick_clock_advances_deterministically():
    clock = TickClock(start=5, step=2)
    assert clock.now() == 5
    assert clock.advance() == 7
    assert clock.advance(3) == 13
    assert clock.stamp() == "t00000013"


def test_tick_clock_rejects_negative_advance():
    clock = TickClock()
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_tick_clock_set_and_reset():
    clock = TickClock()
    clock.set(40)
    assert clock.now() == 40
    clock.reset()
    assert clock.now() == 0


def test_tick_clock_rejects_non_positive_step():
    with pytest.raises(ValueError):
        TickClock(step=0)


def test_format_stamp_zero_pads_the_tick():
    assert format_stamp(0) == "t00000000"
    assert format_stamp(12345) == "t00012345"


def test_format_stamp_rejects_negative_ticks():
    with pytest.raises(ValueError):
        format_stamp(-1)
