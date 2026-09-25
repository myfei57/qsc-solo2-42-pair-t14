"""Contract D: thresholds, current versus history, batches and filters."""

from __future__ import annotations

import pytest

from hydro.domain.errors import DuplicateBatchError, LimitExceededError, NotFoundError
from hydro.journal.store import RecordStore
from hydro.judgment.batch import BatchRegistry
from hydro.judgment.history import StateHistory
from hydro.judgment.query import RecordQuery
from hydro.judgment.threshold import Threshold, Window
from hydro.store.kv import Store


def test_threshold_exceeded_is_strictly_greater():
    limit = Threshold(5.0)
    assert limit.exceeded(5.0) is False
    assert limit.exceeded(5.0001) is True
    assert Threshold(5.0, inclusive=False).exceeded(5.0) is True


def test_threshold_within_is_the_negation_of_exceeded():
    limit = Threshold(5.0)
    assert limit.within(4.0) is True
    assert limit.within(6.0) is False


def test_threshold_require_raises_limit_exceeded_error():
    with pytest.raises(LimitExceededError) as info:
        Threshold(5.0).require("runout", 9.0)
    assert info.value.subject == "runout"
    assert info.value.limit == 5.0


def test_window_contains_respects_inclusive_bounds():
    window = Window(low=0.0, high=5.0, low_inclusive=True, high_inclusive=False)
    assert window.contains(0.0) is True
    assert window.contains(4.999) is True
    assert window.contains(5.0) is False
    assert window.contains(-0.5) is False


def test_window_classifies_below_inside_and_above():
    window = Window(low=1.0, high=3.0)
    assert window.classify(0.5) == "below"
    assert window.classify(2.0) == "inside"
    assert window.classify(3.5) == "above"


def test_window_require_raises_for_value_outside_window():
    with pytest.raises(LimitExceededError):
        Window(low=1.0, high=3.0).require("speed", 4.0)


def test_window_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        Window(low=5.0, high=1.0)


def test_state_history_current_differs_from_historical_entries():
    history = StateHistory()
    history.record("u1", "idle", 0, "register")
    history.record("u1", "running", 10, "start")
    assert history.current("u1").state == "running"
    assert history.at("u1", 0).state == "idle"
    assert history.at("u1", 5).state == "idle"
    assert history.at("u1", 10).state == "running"


def test_state_history_between_filters_by_tick_window():
    history = StateHistory()
    for tick, state in ((0, "idle"), (5, "running"), (10, "stopping")):
        history.record("u1", state, tick)
    assert [entry.state for entry in history.between("u1", 5, 10)] == [
        "running",
        "stopping",
    ]


def test_state_history_transitions_collapse_repeats():
    history = StateHistory()
    for tick, state in ((0, "idle"), (1, "idle"), (2, "running"), (3, "running")):
        history.record("u1", state, tick)
    assert history.transitions("u1") == ["idle", "running"]


def test_state_history_changed_between_detects_a_transition():
    history = StateHistory()
    history.record("u1", "idle", 0)
    history.record("u1", "running", 3)
    assert history.changed_between("u1", 0, 3) is True
    assert history.changed_between("u1", 0, 1) is False


def test_state_history_reports_units_and_length():
    history = StateHistory()
    history.record("u1", "idle", 0)
    history.record("u2", "idle", 0)
    history.record("u2", "running", 1)
    assert history.units() == ["u1", "u2"]
    assert history.length("u2") == 2


def test_batch_open_rejects_duplicate_identifier(tmp_path):
    registry = BatchRegistry(Store(tmp_path / "batch"))
    registry.open("b1", "u1", "open", 0)
    with pytest.raises(DuplicateBatchError):
        registry.open("b1", "u1", "open", 0)


def test_batch_advance_updates_stage(tmp_path):
    registry = BatchRegistry(Store(tmp_path / "batch"))
    registry.open("b1", "u1", "open", 0)
    advanced = registry.advance("b1", "closed")
    assert advanced.stage == "closed"
    assert registry.get("b1").stage == "closed"


def test_batch_registry_by_unit_filters_batches(tmp_path):
    registry = BatchRegistry(Store(tmp_path / "batch"))
    registry.open("b1", "u1", "open", 0)
    registry.open("b2", "u2", "open", 1)
    assert [batch.batch_id for batch in registry.by_unit("u1")] == ["b1"]
    assert registry.count() == 2


def test_batch_get_unknown_identifier_raises_not_found(tmp_path):
    registry = BatchRegistry(Store(tmp_path / "batch"))
    with pytest.raises(NotFoundError):
        registry.get("missing")


def make_journal(tmp_path) -> RecordStore:
    ticks = iter(range(1, 64))
    return RecordStore(Store(tmp_path / "records"), clock=lambda: next(ticks))


def test_record_query_filters_by_kind(tmp_path):
    journal = make_journal(tmp_path)
    journal.append_and_commit("head", "u1", {"value": 60.0})
    journal.append_and_commit("guide", "u1", {"open": True})
    selected = RecordQuery(kinds=("guide",)).apply(journal.log.visible())
    assert [record.kind for record in selected] == ["guide"]


def test_record_query_filters_by_entity(tmp_path):
    journal = make_journal(tmp_path)
    journal.append_and_commit("head", "u1", {"value": 60.0})
    journal.append_and_commit("head", "u2", {"value": 61.0})
    selected = RecordQuery(entities=("u2",)).apply(journal.log.visible())
    assert [record.entity for record in selected] == ["u2"]


def test_record_query_filters_by_tick_window(tmp_path):
    journal = make_journal(tmp_path)
    for value in (1.0, 2.0, 3.0):
        journal.append_and_commit("head", "u1", {"value": value})
    selected = RecordQuery(tick_from=2, tick_to=2).apply(journal.log.visible())
    assert [record.payload["value"] for record in selected] == [2.0]


def test_record_query_limit_and_newest_first(tmp_path):
    journal = make_journal(tmp_path)
    for value in (1.0, 2.0, 3.0, 4.0):
        journal.append_and_commit("head", "u1", {"value": value})
    selected = RecordQuery(limit=2, newest_first=True).apply(journal.log.visible())
    assert [record.payload["value"] for record in selected] == [4.0, 3.0]


def test_record_query_excludes_tombstoned_records(tmp_path):
    journal = make_journal(tmp_path)
    record = journal.append_and_commit("head", "u1", {"value": 60.0})
    journal.rollback(record.seq, "cancelled")
    journal.commit()
    selected = RecordQuery().apply(journal.log.all_records())
    assert [row.is_tombstone for row in selected] == [False]
    assert len(selected) == 1
    assert RecordQuery(exclude_tombstones=False).apply(journal.log.all_records())[-1].is_tombstone


def test_record_query_over_visible_records_drops_rolled_back_rows(tmp_path):
    journal = make_journal(tmp_path)
    record = journal.append_and_commit("head", "u1", {"value": 60.0})
    journal.rollback(record.seq, "cancelled")
    journal.commit()
    assert RecordQuery().apply(journal.log.visible()) == []


def test_record_query_describe_reports_active_filters(tmp_path):
    query = RecordQuery(kinds=("guide",), tick_from=3, limit=10, newest_first=True)
    described = query.describe()
    assert described["kinds"] == ["guide"]
    assert described["tick_from"] == 3
    assert described["limit"] == 10
    assert described["newest_first"] is True


def test_audit_query_filters_records_by_event(seeded):
    seeded.audit.record("guide-open", "u2", "second unit", seeded.tick())
    records = seeded.audit.query(RecordQuery(kinds=("guide-open",)))
    assert [record.event for record in records] == ["guide-open"]
    assert records[0].unit_id == "u2"
