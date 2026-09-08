"""MOD-005: the pure pre-summary review state machine (PHASE-7 T02, ticket #346).

Three explicit lifecycle states, never a fourth (ADR-0001):

    [Draft] -> [Reviewed] -> [Final]
                [Draft] -> [Final]  (high-confidence only, single review action)

``low_confidence`` is a *derived property*, not a state: it is computed from
``structuring_confidence`` and flagged when that value is strictly below 0.70
(or missing/None). When flagged, the pre-summary **structurally forces doctor
review** before it can reach ``Final``: a low-confidence pre-summary is unusable
as ``rx_draft``/``consult`` input until a timestamped, attributed doctor review
is recorded.

High-confidence clean path: ``Finalize`` from ``Draft`` with a single attributed
review action (user story 23, the fast path). Low-confidence path:
``Review`` from ``Draft`` (the hard gate), then ``Finalize`` from ``Reviewed``.

Pure decision logic only: no schema, facade or adapter imports - the
persistence layer applies what this module decides (coding-standards §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from modules.intake.domain.exceptions import IllegalPreSummaryTransitionError


class PreSummaryStatus(StrEnum):
    """Pre-summary review lifecycle (mirrors ``intake_pre_summaries.review_state``)."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    FINAL = "final"


class PreSummaryAction(StrEnum):
    """Lifecycle actions a pre-summary can be asked to take."""

    # Doctor reviews and edits/signs off; Draft -> Reviewed.
    REVIEW = "review"
    # Doctor finalises; Reviewed -> Final always, Draft -> Final only high-conf.
    FINALIZE = "finalize"


#: Structuring confidence threshold: at-or-above = clean, strictly-below = flagged.
LOW_CONFIDENCE_THRESHOLD: Decimal = Decimal("0.70")


def is_low_confidence(structuring_confidence: Decimal | float | None) -> bool:
    """Return True when the pre-summary is flagged low confidence.

    The flag is set when ``structuring_confidence`` is strictly below 0.70
    or missing (None), per AMB-006 / ADR-0001. At or above 0.70 is clean.
    """
    if structuring_confidence is None:
        return True
    return Decimal(str(structuring_confidence)) < LOW_CONFIDENCE_THRESHOLD


@dataclass(frozen=True)
class PreSummaryState:
    """One immutable snapshot of a pre-summary's review lifecycle.

    ``structuring_confidence`` is the LLM provider self-reported confidence
    score (0.0 - 1.0, None if missing). It is used to derive ``low_confidence``
    but is **not mutated** by transitions.
    """

    status: PreSummaryStatus
    structuring_confidence: Decimal | float | None


DRAFT: PreSummaryState = PreSummaryState(status=PreSummaryStatus.DRAFT, structuring_confidence=None)

#: ``(status, action) ->`` the target status for a fixed (non-conditional) edge.
#: ``Finalize`` from Draft is conditional on confidence, handled in ``transition``.
_LEGAL_TRANSITIONS: dict[tuple[PreSummaryStatus, PreSummaryAction], PreSummaryStatus] = {
    # Doctor reviews; Draft -> Reviewed.
    (PreSummaryStatus.DRAFT, PreSummaryAction.REVIEW): PreSummaryStatus.REVIEWED,
    # Doctor finalises after review; Reviewed -> Final (always legal).
    (PreSummaryStatus.REVIEWED, PreSummaryAction.FINALIZE): PreSummaryStatus.FINAL,
}


def transition(state: PreSummaryState, action: PreSummaryAction) -> PreSummaryState:
    """Apply ``action`` to ``state``, answering the next immutable state.

    High-confidence clean path: ``Finalize`` from ``Draft`` moves directly
    to ``Final`` (single attributed review action, user story 23).
    Low-confidence: ``Finalize`` from ``Draft`` is illegal; ``Review`` is
    the mandatory hard gate before ``Final`` can be reached.

    Raises :class:`IllegalPreSummaryTransitionError` for every edge outside
    the binding three-state machine.
    """
    if action is PreSummaryAction.FINALIZE and state.status is PreSummaryStatus.DRAFT:
        if is_low_confidence(state.structuring_confidence):
            raise IllegalPreSummaryTransitionError(
                "finalize is illegal on a low_confidence pre-summary in Draft; "
                "review is required before final (forced doctor review gate)"
            )
        return PreSummaryState(
            status=PreSummaryStatus.FINAL,
            structuring_confidence=state.structuring_confidence,
        )

    target = _LEGAL_TRANSITIONS.get((state.status, action))
    if target is None:
        raise IllegalPreSummaryTransitionError(
            f"{action.value} is illegal while the pre-summary is {state.status.value}"
        )
    return PreSummaryState(status=target, structuring_confidence=state.structuring_confidence)
