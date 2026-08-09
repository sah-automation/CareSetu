"""Phase 0 harness — AMB-006 forced-review gate tests (issue #5).

Verifies the fallback semantics FEAT-007 / MOD-005 pin down: a
``low_confidence`` pre-summary is unusable as drafting or consult input until
an explicit, timestamped, attributed doctor review clears it. Pure state
machine — no providers, no network.
"""

import pytest

from phase0.harness.gate import (
    HARNESS_REVIEWER,
    PURPOSE_CONSULT,
    PURPOSE_RX_DRAFT,
    LowConfidenceNotCleared,
    PreSummaryRecord,
    PreSummaryStatus,
    assert_usable,
    mark_reviewed,
    usable,
    validate_gate_semantics,
)


def _record(confidence: float | None = 0.95) -> PreSummaryRecord:
    return PreSummaryRecord(clip_id="sample_0001", confidence=confidence, structured={})


def test_unflagged_pre_summary_is_usable_from_draft() -> None:
    record = _record(confidence=0.95)
    assert record.low_confidence is False
    assert usable(record, PURPOSE_RX_DRAFT) is True
    assert usable(record, PURPOSE_CONSULT) is True


def test_flagged_pre_summary_is_unusable_until_review() -> None:
    record = _record(confidence=0.50)
    assert record.low_confidence is True
    assert usable(record, PURPOSE_RX_DRAFT) is False
    assert usable(record, PURPOSE_CONSULT) is False
    with pytest.raises(LowConfidenceNotCleared, match="doctor review"):
        assert_usable(record, PURPOSE_RX_DRAFT)


def test_mark_reviewed_records_attribution_and_unlocks() -> None:
    record = _record(confidence=0.50)
    reviewed = mark_reviewed(record, doctor="dr-sharma", reviewed_at="2026-08-09T12:00:00Z")
    assert reviewed.status == PreSummaryStatus.REVIEWED
    assert reviewed.reviewed_by == "dr-sharma"
    assert reviewed.reviewed_at == "2026-08-09T12:00:00Z"
    assert reviewed.low_confidence is True  # flag stays visible
    assert usable(reviewed, PURPOSE_RX_DRAFT) is True
    assert usable(reviewed, PURPOSE_CONSULT) is True


def test_mark_reviewed_requires_attribution_and_timestamp() -> None:
    record = _record(confidence=0.50)
    with pytest.raises(ValueError, match="doctor attribution"):
        mark_reviewed(record, doctor="  ", reviewed_at="2026-08-09T12:00:00Z")
    with pytest.raises(ValueError, match="review timestamp"):
        mark_reviewed(record, doctor="dr-sharma", reviewed_at="")


def test_final_pre_summary_cannot_be_reviewed() -> None:
    from dataclasses import replace

    record = replace(_record(confidence=0.50), status=PreSummaryStatus.FINAL)
    with pytest.raises(ValueError, match="final"):
        mark_reviewed(record, doctor="dr-sharma", reviewed_at="2026-08-09T12:00:00Z")


def test_unknown_confidence_is_flagged_and_gated() -> None:
    record = _record(confidence=None)
    assert record.low_confidence is True
    assert usable(record, PURPOSE_RX_DRAFT) is False


def test_unknown_purpose_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown purpose"):
        assert_usable(_record(confidence=0.95), "billing")


def test_validate_gate_semantics_holds_on_mixed_sample() -> None:
    records = [
        _record(confidence=0.95),  # unflagged
        _record(confidence=0.72),  # unflagged (>= 0.70)
        _record(confidence=0.50),  # flagged
        _record(confidence=0.00),  # flagged
        _record(confidence=None),  # unknown -> flagged
    ]
    assert validate_gate_semantics(records) is True


def test_validate_gate_semantics_records_an_explicit_synthetic_review() -> None:
    assert HARNESS_REVIEWER == "harness-reviewer"
    records = [_record(confidence=0.40)]
    assert (
        validate_gate_semantics(
            records,
            reviewed_by=HARNESS_REVIEWER,
            reviewed_at="2026-08-09T12:00:00Z",
        )
        is True
    )
