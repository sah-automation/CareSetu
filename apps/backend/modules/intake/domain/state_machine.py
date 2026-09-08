"""MOD-005: the pure intake lifecycle state machine (PHASE-7 T02, ticket #346).

The companion pre-summary review machine lives in ``presummary_machine.py``.

Intake lifecycle
----------------

Enumerated statuses mirror ``intake_intakes.status`` (captured, structuring,
ready_for_review, re_record, failed). The binding machine:

    [Captured] -> [Structuring] -> [Ready for Review] (pre-summary, clean)
                                  | [Re-record]        (audio unusable, attempts remain)
                                  | [Ready for Review] (forced text / raw-text fallback)
                                  | [Failed]           (terminal failure)

Re-record paths: ``record_attempts`` counts voice recording attempts (1-based);
total voice attempts hard-capped at 3 (``MAX_RECORD_ATTEMPTS``). When audio is
unusable and attempts remain, the machine moves to Re-record; when attempts are
exhausted, ``RECORD_UNUSABLE`` yields Ready-for-Review with ``forced_text=True``
(the patient switches to typing). ``FORCE_TEXT`` is a direct abandonment path
from Re-record (patient or protocol decides to type instead). ``RAW_TEXT`` is
the degradation path: AI unavailable, the doctor reviews raw transcript; it
moves Structuring -> Ready-for-Review without touching ``forced_text``.

``STRUCTURING_SUCCESS`` moves Structuring -> Ready-for-Review when a
pre-summary is produced (clean or dirty). ``FAIL`` is a terminal failure state
available from Structuring and Re-record.

Pure decision logic only: no schema, facade or adapter imports - the
persistence layer applies what this module decides (coding-standards §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modules.intake.domain.exceptions import IllegalIntakeTransitionError


class IntakeStatus(StrEnum):
    """Intake lifecycle status (mirrors ``intake_intakes.status``)."""

    CAPTURED = "captured"
    STRUCTURING = "structuring"
    READY_FOR_REVIEW = "ready_for_review"
    RE_RECORD = "re_record"
    FAILED = "failed"


class IntakeAction(StrEnum):
    """Lifecycle actions the intake can be asked to take."""

    # Accepted, AI job spawned; Captured -> Structuring.
    START_STRUCTURING = "start_structuring"
    # Pre-summary produced (clean or dirty); Structuring -> Ready for Review.
    STRUCTURING_SUCCESS = "structuring_success"
    # Raw-text fallback when AI unavailable; Structuring -> Ready for Review.
    RAW_TEXT = "raw_text"
    # Audio unusable, decision depends on attempt cap; Structuring -> Re-record
    # or forced text outcome (see ``transition`` cap branch).
    RECORD_UNUSABLE = "record_unusable"
    # Re-record accepted, attempt +1; Re-record -> Structuring.
    RETRY_ACCEPTED = "retry_accepted"
    # Explicit abandonment of voice; Re-record -> Ready for Review forced.
    FORCE_TEXT = "force_text"
    # Terminal failure; Structuring/Re-record -> Failed.
    FAIL = "fail"


#: Hard cap on voice recording attempts (B3 fallback ladder).
MAX_RECORD_ATTEMPTS: int = 3


@dataclass(frozen=True)
class IntakeState:
    """One immutable snapshot of an intake's lifecycle.

    ``record_attempts`` counts voice recording attempts so far (1-based,
    incremented on each accepted retry). ``forced_text`` is True when the
    intake finishes as text after voice failure.
    """

    status: IntakeStatus
    record_attempts: int
    forced_text: bool


#: Initial state for a captured intake (attempt 1, not forced text).
CAPTURED: IntakeState = IntakeState(
    status=IntakeStatus.CAPTURED, record_attempts=1, forced_text=False
)

#: ``(status, action) -> (target status, forced_text_override | None)``.
#: The forced_text_override is True when the transition forces text,
#: None when forced_text is unchanged (carried from current state).
_LEGAL_TRANSITIONS: dict[tuple[IntakeStatus, IntakeAction], tuple[IntakeStatus, bool | None]] = {
    # Captured -> Structuring: accepted, AI job spawned.
    (IntakeStatus.CAPTURED, IntakeAction.START_STRUCTURING): (
        IntakeStatus.STRUCTURING,
        None,
    ),
    # Structuring -> Ready for Review: pre-summary produced (clean or dirty).
    (IntakeStatus.STRUCTURING, IntakeAction.STRUCTURING_SUCCESS): (
        IntakeStatus.READY_FOR_REVIEW,
        None,
    ),
    # Structuring -> Ready for Review: raw-text fallback (AI unavailable).
    (IntakeStatus.STRUCTURING, IntakeAction.RAW_TEXT): (
        IntakeStatus.READY_FOR_REVIEW,
        None,
    ),
    # Re-record -> Structuring: retry accepted, attempt +1.
    (IntakeStatus.RE_RECORD, IntakeAction.RETRY_ACCEPTED): (
        IntakeStatus.STRUCTURING,
        None,
    ),
    # Re-record -> Ready for Review: explicit forced text (abandonment).
    (IntakeStatus.RE_RECORD, IntakeAction.FORCE_TEXT): (
        IntakeStatus.READY_FOR_REVIEW,
        True,
    ),
    # Structuring -> Failed: terminal failure.
    (IntakeStatus.STRUCTURING, IntakeAction.FAIL): (
        IntakeStatus.FAILED,
        None,
    ),
    # Re-record -> Failed: terminal failure.
    (IntakeStatus.RE_RECORD, IntakeAction.FAIL): (
        IntakeStatus.FAILED,
        None,
    ),
}


def transition(state: IntakeState, action: IntakeAction) -> IntakeState:
    """Apply ``action`` to ``state``, answering the next immutable state.

    ``RECORD_UNUSABLE`` is the attempt-cap-dependent edge: when audio is
    unusable and ``record_attempts < MAX_RECORD_ATTEMPTS`` the intake moves
    to ``RE_RECORD``; when exhausted it yields ``READY_FOR_REVIEW`` with
    ``forced_text=True``. This is exactly how the re-record cap and
    forced-text paths are structurally enforced.

    Raises :class:`IllegalIntakeTransitionError` for every edge outside the
    binding transition table.
    """
    if action is IntakeAction.RECORD_UNUSABLE:
        if state.status is not IntakeStatus.STRUCTURING:
            raise IllegalIntakeTransitionError(
                f"record_unusable is illegal while the intake is {state.status.value}"
            )
        if state.record_attempts < MAX_RECORD_ATTEMPTS:
            return IntakeState(
                status=IntakeStatus.RE_RECORD,
                record_attempts=state.record_attempts,
                forced_text=state.forced_text,
            )
        return IntakeState(
            status=IntakeStatus.READY_FOR_REVIEW,
            record_attempts=state.record_attempts,
            forced_text=True,
        )

    edge = _LEGAL_TRANSITIONS.get((state.status, action))
    if edge is None:
        raise IllegalIntakeTransitionError(
            f"{action.value} is illegal while the intake is {state.status.value}"
        )
    next_status, forced_text_override = edge
    record_attempts = state.record_attempts
    if action is IntakeAction.RETRY_ACCEPTED:
        record_attempts = state.record_attempts + 1
    forced_text = forced_text_override if forced_text_override is not None else state.forced_text
    return IntakeState(status=next_status, record_attempts=record_attempts, forced_text=forced_text)
