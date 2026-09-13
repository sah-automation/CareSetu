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

#: Hard cap on typed text intake length (spec #344 "text hard-capped at
#: 2000 characters"). Pinned by the spec decision, so it rides as a named
#: domain constant beside ``MAX_RECORD_ATTEMPTS`` (coding-standards S9.2
#: pinned-constant exception).
MAX_TEXT_LENGTH: int = 2000

#: Minimum audio duration in milliseconds (3 seconds). Clips shorter than
#: this are unusable by the AI pipeline and waste budget on a doomed call.
MIN_AUDIO_DURATION_MS: int = 3000

#: Maximum audio duration in milliseconds (180 seconds = 3 minutes). Clips
#: longer than this exceed the AI pipeline's context window and waste budget.
MAX_AUDIO_DURATION_MS: int = 180_000

#: Transcript usability heuristic thresholds (B3 fallback ladder).
#: Below ``PARTIAL_MIN_CHARS`` is unusable; ``[PARTIAL_MIN_CHARS, USABLE_MIN_CHARS)``
#: is partial (degraded but structurable); at or above ``USABLE_MIN_CHARS`` is usable.
PARTIAL_MIN_CHARS: int = 5
USABLE_MIN_CHARS: int = 21


class TranscriptUsability(StrEnum):
    """Transcript quality classification for the B3 fallback ladder."""

    UNUSABLE = "unusable"
    PARTIAL = "partial"
    USABLE = "usable"


def classify_transcript_usability(transcript: str) -> TranscriptUsability:
    """Deterministic heuristic classifying a transcript's usability.

    Empty / whitespace-only / fewer than 5 characters = ``"unusable"``;
    5-20 characters = ``"partial"``; 21+ characters = ``"usable"``.
    """
    length = len(transcript.strip())
    if length < PARTIAL_MIN_CHARS:
        return TranscriptUsability.UNUSABLE
    if length < USABLE_MIN_CHARS:
        return TranscriptUsability.PARTIAL
    return TranscriptUsability.USABLE


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
