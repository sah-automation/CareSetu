"""MOD-013: the annotation queue fed by doctor review outcomes (T3.5, #752).

Spec #717 decision 40's human half, and the reason #751 declared ``source =
'human'`` on a table it could have left single-valued: a doctor's verdict on a
reviewed prescription and the code's nightly verdict sit in the SAME table under
the same shape, so the human signal is collected in the structure the technical
evaluators already use. Note what that does NOT buy yet: ``trace_id`` here is the
DOCTOR REVIEW request's, while the code evaluators' rows carry the AI job
request's, so "did the machine agree with the human" is still two queries. The
calibration join needs the draft's provenance (see the caveat below) and is
deferred.

**The queue is not a table.** It is every ``source = 'human'`` row of
``observability.observability_evaluation_scores``, one row per review outcome
class:
``observation_kind = 'prescription'``, ``observation_ref`` the prescription's
local id, ``evaluator`` the outcome CLASS, ``data_type = 'BOOLEAN'`` and
``value = 1``. A BOOLEAN row is presence-in-its-class, so decision 40's
aggregation is a COUNT of rows per class - which is what a closed, enumerated
``evaluator`` vocabulary is for; this module never scores a magnitude.

**Fed by events, never by a read of MOD-006's tables** (ADR-0003): the outcome
arrives as ``prescription.approved`` / ``prescription.rejected`` through the
shared bus, exactly like every other subscription here. The two event types are
declared in :data:`modules.observability.domain.consumer.ANNOTATION_EVENT_MIRRORS`,
and the mirrors are where the ticket's handoff rule is enforced - the outcome
classification travels, the doctor's free-text ``reason`` does not, because the
rejected mirror does not declare it.

**Outcome classes, not prose.** ``doctor_review_accepted_unchanged`` /
``doctor_review_accepted_edited`` (split by the producer's ``edited_yn``, which
it derives against its own immutable draft snapshot) and
``doctor_review_rejected``. The vocabulary is deliberately separate from
:data:`modules.observability.domain.evaluation.EVALUATOR_NAMES`: those are the
CODE evaluators, these are a human's, and the unit suite asserts each set
against its own producer rather than merging them.

**The trace id is the request's, or it is NULL.** :func:`annotation_trace_id`
reads the context the dispatcher bound from the delivery's stored
``traceparent`` - the originating API request's id (PHASE-14A A2, #695). A
delivery the platform never traced binds the dispatcher's event-id fallback
there, which is not a tracing-backend identifier; storing it would name a trace
nobody can open, so the column stays NULL instead. The handoff note's rule, and
the reason this queue's ``trace_id`` is nullable.

Caveat worth a ticket of its own when it starts to matter: the review payloads
carry no draft PROVENANCE, so the queue records the verdict on the draft of
record rather than specifically on an AI-drafted one. Narrowing that needs a
producer-side field on MOD-006's review events, which is MOD-006's contract to
change.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from modules.observability.domain.consumer import (
    PrescriptionApprovedTelemetryPayload,
    PrescriptionRejectedTelemetryPayload,
)
from modules.observability.domain.evaluation import (
    DATA_TYPE_BOOLEAN,
    OBSERVATION_KIND_PRESCRIPTION,
    SOURCE_HUMAN,
    EvaluationScore,
)
from observability.logging import get_trace_id, is_valid_trace_id

#: The three outcome classes the queue records - a closed vocabulary, so a
#: fourth kind of review outcome is an edit here (plus its test) rather than an
#: unenumerable label in a column a person is meant to filter on.
ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED = "doctor_review_accepted_unchanged"
ANNOTATION_EVALUATOR_ACCEPTED_EDITED = "doctor_review_accepted_edited"
ANNOTATION_EVALUATOR_REJECTED = "doctor_review_rejected"

#: The evaluator vocabulary this module produces. Separate from
#: ``EVALUATOR_NAMES`` on purpose - see the module docstring.
ANNOTATION_EVALUATORS: frozenset[str] = frozenset(
    {
        ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED,
        ANNOTATION_EVALUATOR_ACCEPTED_EDITED,
        ANNOTATION_EVALUATOR_REJECTED,
    }
)


def annotation_trace_id() -> str | None:
    """The originating request's trace id as this queue may store it, or ``None``.

    The dispatcher binds the trace id it parsed from the delivery's stored
    ``traceparent`` for the duration of the handler, falling back to the event's
    own id when the row carries none. Only the former is a tracing-backend
    identifier, and the two are told apart by the platform's own rule for one
    (32 lowercase hex, never all-zero) rather than by anything this module
    invents: a delivery nobody traced yields ``None``, and an honest NULL beats a
    synthetic id that joins to no trace (the handoff note).
    """
    trace_id = get_trace_id()
    if trace_id is None or not is_valid_trace_id(trace_id):
        return None
    return trace_id


def review_annotation(
    payload: BaseModel, *, trace_id: str | None, occurred_at: datetime
) -> EvaluationScore | None:
    """The one annotation-queue entry a review-outcome delivery carries, or ``None``.

    ``payload`` is the mirror ``run_handler`` already re-validated (the closed
    set in :data:`~modules.observability.domain.consumer.ANNOTATION_EVENT_MIRRORS`);
    anything else answers ``None`` rather than raising, because an unknown
    payload reaching this builder means the registries disagree and the honest
    response is to write nothing rather than to fail a delivery the ledger has
    already marked delivered.

    ``occurred_at`` - the envelope's own timestamp, normalized to UTC by its
    validator - is the score date, so an outcome delivered late still lands on
    the day the doctor decided. ``trace_id`` is the caller's, taken from
    :func:`annotation_trace_id` at the handler, so the pure builder stays free of
    context reads and the test can hand it any id.
    """
    if isinstance(payload, PrescriptionApprovedTelemetryPayload):
        prescription_id = payload.prescription_id
        evaluator = (
            ANNOTATION_EVALUATOR_ACCEPTED_EDITED
            if payload.edited_yn
            else ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED
        )
    elif isinstance(payload, PrescriptionRejectedTelemetryPayload):
        prescription_id = payload.prescription_id
        evaluator = ANNOTATION_EVALUATOR_REJECTED
    else:
        return None
    return EvaluationScore(
        score_date=occurred_at.astimezone(UTC).date(),
        observation_kind=OBSERVATION_KIND_PRESCRIPTION,
        observation_ref=str(prescription_id),
        evaluator=evaluator,
        data_type=DATA_TYPE_BOOLEAN,
        value=1.0,
        source=SOURCE_HUMAN,
        trace_id=trace_id,
    )


__all__ = [
    "ANNOTATION_EVALUATORS",
    "ANNOTATION_EVALUATOR_ACCEPTED_EDITED",
    "ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED",
    "ANNOTATION_EVALUATOR_REJECTED",
    "annotation_trace_id",
    "review_annotation",
]
