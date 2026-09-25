"""Contract B: generation bound artifacts that expire and must be refused."""

from __future__ import annotations

import pytest

from hydro.domain.errors import (
    ExpiredArtifactError,
    StaleGenerationError,
    SyncNotConfirmedError,
)
from hydro.runtime.context import RuntimeContext
from hydro.versioning.artifacts import ArtifactLedger
from hydro.versioning.generations import (
    SCOPES,
    SCOPE_BASELINE,
    SCOPE_CONFIRM,
    SCOPE_OIL,
    GenerationBook,
)


def make_ledger(tmp_path) -> tuple[ArtifactLedger, GenerationBook]:
    context = RuntimeContext.build(tmp_path / "versioning")
    return context.artifacts, context.generations


def test_generation_starts_at_zero(tmp_path):
    ledger, book = make_ledger(tmp_path)
    assert book.current(SCOPE_CONFIRM, "u1") == 0


def test_generation_bump_increases_counter(tmp_path):
    ledger, book = make_ledger(tmp_path)
    assert book.bump(SCOPE_CONFIRM, "u1") == 1
    assert book.bump(SCOPE_CONFIRM, "u1") == 2
    assert book.current(SCOPE_CONFIRM, "u1") == 2


def test_generation_persists_across_reopen(tmp_path):
    ledger, book = make_ledger(tmp_path)
    book.bump(SCOPE_OIL, "u1")
    reopened = GenerationBook(RuntimeContext.build(tmp_path / "versioning").store)
    assert reopened.current(SCOPE_OIL, "u1") == 1


def test_generation_snapshot_lists_every_scope(tmp_path):
    ledger, book = make_ledger(tmp_path)
    book.bump(SCOPE_BASELINE, "u1")
    snapshot = book.snapshot("u1")
    assert set(snapshot) == set(SCOPES)
    assert snapshot[SCOPE_BASELINE] == 1


def test_generation_set_rejects_negative_value(tmp_path):
    ledger, book = make_ledger(tmp_path)
    with pytest.raises(ValueError):
        book.set(SCOPE_CONFIRM, "u1", -1)


def test_confirmation_is_valid_within_ttl(tmp_path):
    ledger, book = make_ledger(tmp_path)
    confirmation = ledger.issue_confirmation("u1", SCOPE_CONFIRM, 10, 0)
    assert confirmation.expires_at == 10
    assert confirmation.is_expired(10) is False
    ledger.validate_confirmation(confirmation, 10)


def test_confirmation_expires_after_ttl(tmp_path):
    ledger, book = make_ledger(tmp_path)
    confirmation = ledger.issue_confirmation("u1", SCOPE_CONFIRM, 10, 0)
    with pytest.raises(ExpiredArtifactError):
        ledger.validate_confirmation(confirmation, 11)


def test_confirmation_is_stale_after_generation_bump(tmp_path):
    ledger, book = make_ledger(tmp_path)
    confirmation = ledger.issue_confirmation("u1", SCOPE_CONFIRM, 100, 0)
    book.bump(SCOPE_CONFIRM, "u1")
    with pytest.raises(StaleGenerationError):
        ledger.validate_confirmation(confirmation, 1)


def test_confirmation_ttl_must_be_positive(tmp_path):
    ledger, book = make_ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.issue_confirmation("u1", SCOPE_CONFIRM, 0, 0)


def test_baseline_expires_after_ttl(tmp_path):
    ledger, book = make_ledger(tmp_path)
    baseline = ledger.publish_baseline("u1", SCOPE_BASELINE, 60.0, 10, 0)
    baseline.validate(book, 10)
    with pytest.raises(ExpiredArtifactError):
        baseline.validate(book, 11)


def test_baseline_is_stale_after_republish(tmp_path):
    ledger, book = make_ledger(tmp_path)
    first = ledger.publish_baseline("u1", SCOPE_BASELINE, 60.0, 100, 0)
    ledger.publish_baseline("u1", SCOPE_BASELINE, 61.0, 100, 1)
    with pytest.raises(StaleGenerationError):
        first.validate(book, 1)


def test_baseline_ttl_must_be_positive(tmp_path):
    ledger, book = make_ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.publish_baseline("u1", SCOPE_BASELINE, 60.0, 0, 0)


def test_snapshot_is_valid_at_current_generation(tmp_path):
    ledger, book = make_ledger(tmp_path)
    snapshot = ledger.take_snapshot("u1", SCOPE_OIL, {"gain": 2.0}, 0)
    assert snapshot.is_stale(book) is False
    assert ledger.latest_snapshot("u1", SCOPE_OIL).payload["gain"] == 2.0


def test_snapshot_is_stale_after_generation_bump(tmp_path):
    ledger, book = make_ledger(tmp_path)
    snapshot = ledger.take_snapshot("u1", SCOPE_OIL, {"gain": 2.0}, 0)
    book.bump(SCOPE_OIL, "u1")
    assert snapshot.is_stale(book) is True
    with pytest.raises(StaleGenerationError):
        snapshot.validate(book)


def test_expired_confirmation_is_rejected_by_excitation(seeded):
    seeded.gov.sync_confirm("u1", 0, 5)
    assert seeded.exc.apply("u1", 5) is True
    seeded.exc.reset("u1")
    with pytest.raises(SyncNotConfirmedError):
        seeded.exc.apply("u1", 6)


def test_expired_head_baseline_is_rejected_by_output_limit(controller):
    controller.units.register("u1", "unit-1", 0)
    controller.intake.set_baseline("u1", 60.0, 0, 10)
    assert controller.gov.limit("u1", 10) == pytest.approx(192.0)
    with pytest.raises(ExpiredArtifactError):
        controller.gov.limit("u1", 11)


def test_stale_sync_confirmation_is_rejected_after_reconfirmation(seeded):
    seeded.gov.sync_confirm("u1", 0, 100)
    first = seeded.gov.sync_confirmation("u1")
    seeded.gov.sync_confirm("u1", 1, 100)
    with pytest.raises(StaleGenerationError):
        seeded.context.artifacts.validate_confirmation(first, 1)
    assert seeded.exc.apply("u1", 1) is True


def test_sync_state_reports_expired_after_ttl(seeded):
    seeded.gov.sync_confirm("u1", 0, 3)
    assert seeded.gov.sync_state("u1", 3) == "confirmed"
    assert seeded.gov.sync_state("u1", 4) == "expired"


def test_vib_snapshot_becomes_stale_after_limit_change(seeded):
    first = seeded.vib.snapshot("u1")
    seeded.vib.set_limit("u1", 4.0, seeded.tick())
    assert first.is_stale(seeded.context.generations) is True
    with pytest.raises(StaleGenerationError):
        first.validate(seeded.context.generations)


def test_oil_baseline_expiry_is_visible_to_validator(seeded):
    seeded.gov.recalibrate_oil("u1", 80.0, 0, 5)
    assert seeded.gov.validate_oil("u1", 5) == pytest.approx(2.0)
    with pytest.raises(ExpiredArtifactError):
        seeded.gov.validate_oil("u1", 6)
