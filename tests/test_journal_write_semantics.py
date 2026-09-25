"""Contract A: append only stream, commit watermark, replay, tombstones."""

from __future__ import annotations

import pytest

from hydro.domain.errors import DuplicateRecordError, NotFoundError, WatermarkError
from hydro.journal.log import RecordLog
from hydro.journal.store import RecordStore
from hydro.store.kv import Store


def make_log(tmp_path, tick: int = 1) -> tuple[RecordLog, Store]:
    store = Store(tmp_path / "journal-root")
    return RecordLog(store, clock=lambda: tick), store


def test_append_then_commit_makes_record_visible(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    assert log.visible() == []
    log.commit()
    assert [record.payload["value"] for record in log.visible()] == [60.0]


def test_uncommitted_record_is_invisible_to_reader(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    assert log.latest("head", "u1") is None
    assert log.committed() == []
    assert len(log.pending()) == 1


def test_uncommitted_record_is_invisible_after_restart(tmp_path):
    log, store = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    reopened = RecordLog(store)
    assert reopened.latest("head", "u1") is None
    assert reopened.watermark == 0


def test_commit_watermark_advances_monotonically(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 1.0})
    log.append("head", "u2", {"value": 2.0})
    assert log.commit_upto(1) == 1
    assert log.commit_upto(2) == 2
    assert log.watermark == 2


def test_watermark_cannot_move_backwards(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 1.0})
    log.commit_upto(1)
    with pytest.raises(WatermarkError):
        log.commit_upto(0)


def test_watermark_cannot_exceed_last_sequence(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 1.0})
    with pytest.raises(WatermarkError):
        log.commit_upto(9)


def test_rollback_tombstone_hides_record_after_commit(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    log.commit()
    log.rollback(1, "operator cancelled the measurement")
    log.commit()
    assert log.visible() == []
    assert len(log.all_records()) == 2


def test_rollback_before_commit_does_not_hide_record(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    log.commit()
    log.rollback(1, "not committed yet")
    assert len(log.visible()) == 1


def test_tombstoned_dedup_key_can_be_reused(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("stage", "u1", {"stage": "head-persist"}, dedup_key="head-persist")
    log.commit()
    log.rollback(1, "redo the stage")
    log.commit()
    log.append("stage", "u1", {"stage": "head-persist"}, dedup_key="head-persist")
    log.commit()
    assert len(log.visible()) == 1


def test_duplicate_dedup_key_is_rejected(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("stage", "u1", {"stage": "head-persist"}, dedup_key="head-persist")
    log.commit()
    with pytest.raises(DuplicateRecordError):
        log.append("stage", "u1", {"stage": "head-persist"}, dedup_key="head-persist")


def test_duplicate_pending_append_is_rejected(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("stage", "u1", {"stage": "head-persist"}, dedup_key="head-persist")
    with pytest.raises(DuplicateRecordError):
        log.append("stage", "u1", {"stage": "head-persist"}, dedup_key="head-persist")


def test_restart_replays_only_committed_records(tmp_path):
    log, store = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    log.commit()
    log.append("head", "u1", {"value": 99.0})
    reopened = RecordLog(store)
    assert [record.payload["value"] for record in reopened.visible()] == [60.0]


def test_replay_rebuilds_latest_value(tmp_path):
    log, store = make_log(tmp_path)
    log.append("head", "u1", {"value": 60.0})
    log.commit()
    log.append("head", "u1", {"value": 61.0})
    log.commit()
    reopened = RecordLog(store).replay()
    assert reopened.latest("head", "u1").payload["value"] == 61.0


def test_all_records_keep_append_order(tmp_path):
    log, _ = make_log(tmp_path)
    for value in (1.0, 2.0, 3.0):
        log.append("head", "u1", {"value": value})
    assert [record.seq for record in log.all_records()] == [1, 2, 3]


def test_rollback_unknown_sequence_is_rejected(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 1.0})
    with pytest.raises(NotFoundError):
        log.rollback(99, "no such sequence")


def test_rollback_of_tombstone_is_rejected(tmp_path):
    log, _ = make_log(tmp_path)
    log.append("head", "u1", {"value": 1.0})
    log.commit()
    log.rollback(1, "first")
    log.commit()
    with pytest.raises(WatermarkError):
        log.rollback(2, "second")


def test_watermark_is_persisted_across_reopen(tmp_path):
    log, store = make_log(tmp_path)
    log.append("head", "u1", {"value": 1.0})
    log.append("head", "u2", {"value": 2.0})
    log.commit()
    assert RecordLog(store).watermark == 2


def test_record_store_append_and_commit_roundtrip(tmp_path):
    store = Store(tmp_path / "facade")
    journal = RecordStore(store, clock=lambda: 3)
    journal.append_and_commit("head", "u1", {"value": 60.0})
    assert journal.latest("head", "u1") == {
        "value": 60.0,
    }
    assert journal.watermark == 1


def test_record_store_replay_is_idempotent(tmp_path):
    store = Store(tmp_path / "facade")
    journal = RecordStore(store)
    journal.append_and_commit("head", "u1", {"value": 60.0})
    journal.append_and_commit("head", "u1", {"value": 61.0})
    before = journal.latest("head", "u1")
    journal.replay()
    assert journal.latest("head", "u1") == before


def test_record_store_rollback_hides_latest(tmp_path):
    store = Store(tmp_path / "facade")
    journal = RecordStore(store)
    record = journal.append_and_commit("head", "u1", {"value": 60.0})
    journal.rollback(record.seq, "cancelled")
    journal.commit()
    assert journal.latest("head", "u1") is None
