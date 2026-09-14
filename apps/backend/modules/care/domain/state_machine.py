"""MOD-006: the pure care-case lifecycle state machine (PHASE-8 T02, ticket #418).

Stage and action vocabulary come from CONTEXT.md's ``case stage`` / ``consult
complete milestone`` / ``close-without-prescription`` glossary terms; stage
enum values cover the three dwell stages in ``care_cases.stage``
(pre_summary, prescription_pending, closed). ``consult_complete`` is an
audited milestone on the ``PreSummary -> PrescriptionPending`` transition, not
a dwell stage, so it has no enum member here.

Case lifecycle
--------------

    [Pre-summary] --MARK_CONSULT_COMPLETE (finalized gate)--> [Prescription Pending]
         |                                                          |
         +--CLOSE_WITHOUT_RX (reason)--> [Closed] <--CLOSE_WITHOUT_RX--+

The case is born in ``PreSummary`` when its pre-summary is finalized.
``MARK_CONSULT_COMPLETE`` is the one-action handshake that closes the
off-platform consult on-platform: it is the audited ``consult complete
milestone`` on the ``PreSummary -> PrescriptionPending`` transition (never a
dwell state) and is gated on a finalized pre-summary - a prescription-stage
case can never arise from an unreviewed summary. ``CLOSE_WITHOUT_RX`` is the
doctor's deliberate terminal close-without-prescription; it requires a
non-empty close reason and is available while the case is open (PreSummary or
PrescriptionPending). ``Closed`` is terminal: once closed, no action moves the
case. A rejected draft never changes the case stage (that decision belongs to
the prescription machine, not this one).

Pure decision logic only: no schema, facade or adapter imports - the
persistence layer applies what this module decides (coding-standards §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modules.care.domain.exceptions import IllegalCareTransitionError


class CaseStage(StrEnum):
    """Case lifecycle dwell stage (mirrors ``care_cases.stage``).

    ``ConsultComplete`` is deliberately absent: it is the audited milestone
    on the ``PreSummary -> PrescriptionPending`` transition, never a stage.
    """

    PRE_SUMMARY = "pre_summary"
    PRESCRIPTION_PENDING = "prescription_pending"
    CLOSED = "closed"


class CaseAction(StrEnum):
    """Lifecycle actions a care case can be asked to take."""

    # One-action handshake: Pre-summary -> Prescription Pending (requires a
    # finalized pre-summary; records the consult-complete milestone).
    MARK_CONSULT_COMPLETE = "mark_consult_complete"
    # Doctor's deliberate terminal close-without-prescription (requires a
    # close reason); Pre-summary/Prescription Pending -> Closed.
    CLOSE_WITHOUT_RX = "close_without_rx"


@dataclass(frozen=True)
class CaseState:
    """One immutable snapshot of a care case's lifecycle.

    ``close_reason`` is carried on the snapshot so a ``CLOSE_WITHOUT_RX``
    transition is observable: the machine only yields a ``Closed`` stage when
    a close reason was supplied.
    """

    stage: CaseStage
    close_reason: str | None = None


#: Initial state for a care case just born from its finalized pre-summary.
PRE_SUMMARY: CaseState = CaseState(stage=CaseStage.PRE_SUMMARY)


def transition(
    state: CaseState,
    action: CaseAction,
    *,
    pre_summary_finalized: bool = False,
    close_reason: str | None = None,
) -> CaseState:
    """Apply ``action`` to ``state``, answering the next immutable state.

    ``MARK_CONSULT_COMPLETE`` is the finalized-pre-summary gate: it raises
    unless ``pre_summary_finalized`` is True, so a prescription-stage case
    can never arise from an unreviewed summary (FEAT-008 edge case). It also
    enforces the milestone-not-state contract by yielding Prescription Pending
    from Pre-Summary only - the milestone recording is the facade's audited
    write, never a dwell stage here.

    ``CLOSE_WITHOUT_RX`` is the doctor's deliberate terminal action: it
    requires a non-empty ``close_reason`` and moves any open stage to
    ``Closed``, answering a snapshot that carries the reason. ``Closed`` is
    terminal for every action.

    Raises :class:`IllegalCareTransitionError` for every edge outside the
    bound transitions and for missing transition prerequisites.
    """
    if action is CaseAction.MARK_CONSULT_COMPLETE:
        if state.stage is not CaseStage.PRE_SUMMARY:
            raise IllegalCareTransitionError(
                f"{action.value} is illegal while the case is {state.stage.value}"
            )
        if not pre_summary_finalized:
            raise IllegalCareTransitionError(f"{action.value} requires a finalized pre-summary")
        return CaseState(stage=CaseStage.PRESCRIPTION_PENDING, close_reason=None)

    if action is CaseAction.CLOSE_WITHOUT_RX:
        if state.stage is CaseStage.CLOSED:
            raise IllegalCareTransitionError(
                f"{action.value} is illegal while the case is {state.stage.value}"
            )
        if not close_reason:
            raise IllegalCareTransitionError(f"{action.value} requires a close reason")
        return CaseState(stage=CaseStage.CLOSED, close_reason=close_reason)

    raise IllegalCareTransitionError(f"{action.value} is an unknown action")
