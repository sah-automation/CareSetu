"""Phase 0 harness — AMB-006 forced-review usage gate (issue #5).

The fallback semantics FEAT-007 / MOD-005 pin down: a ``low_confidence``
pre-summary is unusable as drafting or consult input until an explicit,
timestamped, attributed doctor review clears it. The lifecycle is
``[Draft] -> [Reviewed] -> [Final]`` with the flag as a quality gate, not a
fourth state — it is cleared only by that recorded review.

This module is the throwaway, pure-state version of the gate the spike must
validate; the hard interlocks live at ``request_rx_draft`` and
``mark_consult_complete`` in PHASE-7. Not production code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from phase0.harness.metrics import low_confidence
from phase0.harness.models import PreSummaryData

PURPOSE_RX_DRAFT = "rx_draft"
PURPOSE_CONSULT = "consult"
_USABLE_PURPOSES = (PURPOSE_RX_DRAFT, PURPOSE_CONSULT)

# The harness has no real doctor; the recorded review that clears a flagged
# pre-summary during gate validation is attributed to this synthetic actor.
# A production deployment records the actual reviewing doctor instead.
HARNESS_REVIEWER = "harness-reviewer"


class PreSummaryStatus(StrEnum):
    """Pre-summary lifecycle: Draft -> Reviewed -> Final (FEAT-007)."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    FINAL = "final"


class LowConfidenceNotCleared(RuntimeError):
    """Raised when a low-confidence pre-summary is used before recorded review."""


@dataclass(frozen=True)
class PreSummaryRecord:
    """One pre-summary with its confidence, flag, and review state."""

    clip_id: str
    confidence: float | None
    structured: PreSummaryData
    status: PreSummaryStatus = PreSummaryStatus.DRAFT
    reviewed_by: str | None = None
    reviewed_at: str | None = None

    @property
    def low_confidence(self) -> bool:
        """The AMB-006 flag, derived from structuring confidence vs. 0.70."""
        return low_confidence(self.confidence)


def mark_reviewed(record: PreSummaryRecord, doctor: str, reviewed_at: str) -> PreSummaryRecord:
    """Clear the low-confidence gate with a recorded, attributed doctor review.

    The flag itself is not reset (the extraction is still flagged "low
    confidence — verify"); the recorded review is what unlocks it. A Final
    pre-summary is terminal and cannot be re-reviewed.
    """
    if record.status == PreSummaryStatus.FINAL:
        raise ValueError(f"{record.clip_id}: final pre-summaries cannot be re-reviewed")
    if not doctor.strip():
        raise ValueError(f"{record.clip_id}: doctor attribution is required")
    if not reviewed_at.strip():
        raise ValueError(f"{record.clip_id}: review timestamp is required")
    return replace(
        record,
        status=PreSummaryStatus.REVIEWED,
        reviewed_by=doctor,
        reviewed_at=reviewed_at,
    )


def assert_usable(record: PreSummaryRecord, purpose: str) -> None:
    """Hard usage gate: a flagged pre-summary needs a recorded review first.

    Unflagged pre-summaries are usable from Draft; flagged ones are unusable
    for the clinical purposes (rx drafting / consult close-out) until the
    doctor review is recorded.
    """
    if purpose not in _USABLE_PURPOSES:
        raise ValueError(f"{record.clip_id}: unknown purpose {purpose!r}")
    if record.low_confidence and record.status != PreSummaryStatus.REVIEWED:
        raise LowConfidenceNotCleared(
            f"{record.clip_id}: low-confidence pre-summary is not usable for "
            f"{purpose} until a recorded doctor review clears it"
        )


def usable(record: PreSummaryRecord, purpose: str) -> bool:
    try:
        assert_usable(record, purpose)
    except LowConfidenceNotCleared:
        return False
    return True


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def validate_gate_semantics(
    records: Sequence[PreSummaryRecord],
    reviewed_by: str = HARNESS_REVIEWER,
    reviewed_at: str | None = None,
) -> bool:
    """Prove the forced-review fallback on the sample's structured clips.

    For every record: an unflagged pre-summary is usable from Draft for both
    clinical purposes; a flagged one is not usable until ``mark_reviewed``
    records a doctor + timestamp, after which both purposes open. The review
    is attributed to the given reviewer (default the synthetic
    ``HARNESS_REVIEWER``) and stamped with ``reviewed_at`` (default now), so
    the recorded clear is explicit and per-run, not a hard-coded value.
    Returns False on the first violation.
    """
    stamp = reviewed_at if reviewed_at is not None else _utc_now_iso()
    for record in records:
        if not record.low_confidence:
            if not usable(record, PURPOSE_RX_DRAFT) or not usable(record, PURPOSE_CONSULT):
                return False
            continue
        if usable(record, PURPOSE_RX_DRAFT) or usable(record, PURPOSE_CONSULT):
            return False
        reviewed = mark_reviewed(record, doctor=reviewed_by, reviewed_at=stamp)
        if reviewed.status != PreSummaryStatus.REVIEWED:
            return False
        if reviewed.reviewed_by is None or reviewed.reviewed_at is None:
            return False
        if not usable(reviewed, PURPOSE_RX_DRAFT) or not usable(reviewed, PURPOSE_CONSULT):
            return False
    return True
