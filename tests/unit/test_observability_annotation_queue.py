"""T3.5 #752: the annotation queue fed by doctor review outcomes.

The queue's two halves, both without a database: the pure classification a
review outcome becomes (a ``source = 'human'`` score row), and the seat the
registry generates to deliver it - driven through the same short-lived-engine +
consumed-event-ledger seam the live dispatcher uses, with the REAL care
producer payload models handed over, so the mirror round trip is proven here
and not only against Postgres.

The integration round trip
(``test_observability_consumer_round_trip.py``) proves the same contract
against a real database; these are the fast ones that name a column.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.dialects import postgresql

from bus.envelope import Envelope
from bus.events import EVENT_PRESCRIPTION_APPROVED, EVENT_PRESCRIPTION_REJECTED
from bus.registry import HandlerRegistry
from modules.care.domain.events import (
    prescription_approved_envelope,
    prescription_rejected_envelope,
)
from modules.observability.adapters import _seats
from modules.observability.adapters import (
    register_handlers as register_obs_handlers,
)
from modules.observability.domain.annotation import (
    ANNOTATION_EVALUATOR_ACCEPTED_EDITED,
    ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED,
    ANNOTATION_EVALUATOR_REJECTED,
    ANNOTATION_EVALUATORS,
    annotation_trace_id,
    review_annotation,
)
from modules.observability.domain.consumer import (
    ANNOTATION_EVENT_MIRRORS,
    CaseConsultCompleteTelemetryPayload,
    PrescriptionApprovedTelemetryPayload,
    PrescriptionRejectedTelemetryPayload,
)
from modules.observability.domain.evaluation import (
    DATA_TYPE_BOOLEAN,
    EVALUATOR_NAMES,
    OBSERVATION_KIND_PRESCRIPTION,
    SOURCE_HUMAN,
)
from modules.observability.facade import record_annotation
from observability.logging import reset_trace_id, set_trace_id

_NOW = datetime(2026, 10, 13, 8, 15, 0, tzinfo=UTC)
_EVENT_ID = UUID("11111111-2222-3333-4444-555555555555")
_PATIENT_REF = 3
_DOCTOR_REF = 9
_PRESCRIPTION_REF = 41
_TRACE_ID = "a" * 32


def _patch_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)


def _fake_ledger(monkeypatch: pytest.MonkeyPatch, delivered: set[str]) -> None:
    async def ledger(
        conn: object, schema: object, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", ledger)


def _at(envelope: Envelope[BaseModel]) -> Envelope[BaseModel]:
    """The producer's envelope pinned to this test's instant (the builder mints now)."""
    return envelope.model_copy(update={"occurred_at": _NOW})


def _approved(*, edited_yn: bool, event_id: UUID = _EVENT_ID) -> Envelope[BaseModel]:
    return _at(
        prescription_approved_envelope(
            case_id=7,
            prescription_id=_PRESCRIPTION_REF,
            patient_id=_PATIENT_REF,
            doctor_id=_DOCTOR_REF,
            edited_yn=edited_yn,
        )
    ).model_copy(update={"event_id": event_id})


def _rejected(*, event_id: UUID = _EVENT_ID) -> Envelope[BaseModel]:
    return _at(
        prescription_rejected_envelope(
            case_id=7,
            prescription_id=_PRESCRIPTION_REF,
            patient_id=_PATIENT_REF,
            doctor_id=_DOCTOR_REF,
            reason="dose looks wrong for this patient",
        )
    ).model_copy(update={"event_id": event_id})


def _approved_mirror(*, edited_yn: bool) -> PrescriptionApprovedTelemetryPayload:
    """The mirror ``run_handler`` re-validates the producer's payload into.

    Built through that same re-validation rather than hand-constructed, so the
    producer -> mirror round trip the handler relies on is proven here too.
    """
    return PrescriptionApprovedTelemetryPayload.model_validate(
        _approved(edited_yn=edited_yn).payload.model_dump()
    )


def _rejected_mirror() -> PrescriptionRejectedTelemetryPayload:
    return PrescriptionRejectedTelemetryPayload.model_validate(_rejected().payload.model_dump())


def _bound_trace(trace_id: str | None) -> str | None:
    token = set_trace_id(trace_id)
    try:
        return annotation_trace_id()
    finally:
        reset_trace_id(token)


# ------------------------------------------------------------------- the seats


def test_the_two_review_outcomes_are_the_only_annotation_events() -> None:
    """The queue is fed by terminal outcomes: approved and rejected, nothing else."""
    assert set(ANNOTATION_EVENT_MIRRORS) == {
        EVENT_PRESCRIPTION_APPROVED,
        EVENT_PRESCRIPTION_REJECTED,
    }


def test_the_rejected_mirror_declares_the_references_and_never_the_rationale() -> None:
    """The handoff rule, enforced at the payload shape the builder ever sees."""
    assert set(PrescriptionRejectedTelemetryPayload.model_fields) == {
        "case_id",
        "prescription_id",
        "patient_id",
        "doctor_id",
    }


def test_the_approved_seat_carries_the_funnel_step_and_the_annotation_together() -> None:
    """``prescription.approved`` already had a seat, so the outcome RIDES it.

    A second seat would find the first one's ledger row, be told it is a replay,
    and write nothing - invisibly, forever.
    """
    seats = {seat.event_type: seat for seat in _seats()}

    approved = seats[EVENT_PRESCRIPTION_APPROVED]
    assert approved.annotation is True
    assert approved.product_step is not None
    name = approved.handler_name
    assert "annotation" in name
    assert "product_event" in name

    rejected = seats[EVENT_PRESCRIPTION_REJECTED]
    assert rejected.annotation is True
    assert rejected.product_step is None
    assert rejected.business_metric is None
    assert rejected.handler_name == "record_annotation"


def test_every_consumed_event_type_gets_exactly_one_seat() -> None:
    """One seat per event type, because the consumed-event ledger is keyed by it alone."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)

    for event_type in set(ANNOTATION_EVENT_MIRRORS):
        assert len(registry.handlers_for(event_type)) == 1, event_type


# ------------------------------------------------------- the classification


@pytest.mark.parametrize(
    ("edited_yn", "evaluator"),
    [
        (False, ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED),
        (True, ANNOTATION_EVALUATOR_ACCEPTED_EDITED),
    ],
)
def test_the_accepted_classes_split_on_the_producers_edited_flag(
    edited_yn: bool, evaluator: str
) -> None:
    """The producer derived the flag against its own immutable draft snapshot;
    the queue records which class that produced, never the snapshot itself."""
    score = review_annotation(
        _approved_mirror(edited_yn=edited_yn), trace_id=_TRACE_ID, occurred_at=_NOW
    )

    assert score is not None
    assert score.evaluator == evaluator
    assert score.value == 1.0
    assert score.data_type == DATA_TYPE_BOOLEAN


def test_a_rejection_records_its_class_even_when_the_payload_carried_a_rationale() -> None:
    """The producer DOES ship a free-text reason; the mirror drops it before the
    builder runs, so the queue can never store a doctor's prose."""
    care_payload = _rejected().payload
    assert "reason" in type(care_payload).model_fields
    payload = _rejected_mirror()
    assert "reason" not in type(payload).model_fields
    assert "reason" not in payload.model_dump()

    score = review_annotation(payload, trace_id=None, occurred_at=_NOW)

    assert score is not None
    assert score.evaluator == ANNOTATION_EVALUATOR_REJECTED


def test_the_queue_row_is_the_human_boolean_presence_of_its_class() -> None:
    """Every column of the #752 join shape, named at once."""
    score = review_annotation(
        _approved_mirror(edited_yn=False), trace_id=_TRACE_ID, occurred_at=_NOW
    )

    assert score is not None
    assert score.source == SOURCE_HUMAN
    assert score.observation_kind == OBSERVATION_KIND_PRESCRIPTION
    assert score.observation_ref == str(_PRESCRIPTION_REF)
    assert score.score_date == _NOW.astimezone(UTC).date()
    assert score.trace_id == _TRACE_ID
    assert score.observation_id is None


def test_a_payload_no_registry_maps_to_writes_nothing() -> None:
    """A registry disagreement must not fail a delivery the ledger already holds."""
    envelope = Envelope[CaseConsultCompleteTelemetryPayload](
        event_id=uuid4(),
        event_type="case.consult_complete",
        producer="care",
        occurred_at=_NOW,
        payload=CaseConsultCompleteTelemetryPayload(
            case_id=7, patient_id=_PATIENT_REF, doctor_id=_DOCTOR_REF
        ),
    )

    assert review_annotation(envelope.payload, trace_id=None, occurred_at=_NOW) is None


def test_the_evaluator_vocabulary_is_human_and_disjoint_from_the_code_ones() -> None:
    """The two vocabularies are asserted separately so neither can grow silently
    into the other's column filter."""
    assert {
        ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED,
        ANNOTATION_EVALUATOR_ACCEPTED_EDITED,
        ANNOTATION_EVALUATOR_REJECTED,
    } == ANNOTATION_EVALUATORS
    assert ANNOTATION_EVALUATORS.isdisjoint(EVALUATOR_NAMES)
    assert all(len(name) <= 64 for name in ANNOTATION_EVALUATORS)


# -------------------------------------------------------------------- the trace


def test_the_stored_trace_is_the_requests_or_an_honest_null() -> None:
    """The dispatcher binds the outbox row's parsed trace, falling back to the
    event's own id - and the event id is NOT a tracing-backend identifier, so a
    delivery nobody traced leaves the column NULL rather than naming a trace
    nobody can open."""
    assert _bound_trace(_TRACE_ID) == _TRACE_ID
    assert _bound_trace(None) is None
    assert _bound_trace(str(_EVENT_ID)) is None
    assert _bound_trace("0" * 32) is None


# --------------------------------------------------------- the write, end to end


@pytest.mark.asyncio
async def test_the_approved_delivery_writes_the_funnel_row_and_one_annotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One seat, both effects, in the one ledger-gated transaction."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    step_record = AsyncMock()
    annotation_record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_product_event", step_record)
    monkeypatch.setattr("modules.observability.adapters.record_annotation", annotation_record)

    token = set_trace_id(_TRACE_ID)
    try:
        await registry.handlers_for(EVENT_PRESCRIPTION_APPROVED)[0](_approved(edited_yn=True))
    finally:
        reset_trace_id(token)

    assert step_record.await_count == 1
    assert annotation_record.await_count == 1
    handed = annotation_record.await_args.args[1]
    assert isinstance(handed, PrescriptionApprovedTelemetryPayload)
    assert handed.edited_yn is True
    assert annotation_record.await_args.kwargs["trace_id"] == _TRACE_ID
    assert annotation_record.await_args.kwargs["occurred_at"] == _NOW


@pytest.mark.asyncio
async def test_the_rejected_delivery_hands_the_mirror_that_lost_the_rationale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the queue is given is the classification, and the seat never sees
    the prose the producer shipped alongside it."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    annotation_record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_annotation", annotation_record)

    await registry.handlers_for(EVENT_PRESCRIPTION_REJECTED)[0](_rejected())

    assert annotation_record.await_count == 1
    handed = annotation_record.await_args.args[1]
    assert isinstance(handed, PrescriptionRejectedTelemetryPayload)
    assert handed.prescription_id == _PRESCRIPTION_REF


@pytest.mark.asyncio
async def test_a_replayed_review_outcome_writes_neither_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ledger row gates BOTH effects, so a redelivery cannot double the queue."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_PRESCRIPTION_APPROVED)[0]
    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    step_record = AsyncMock()
    annotation_record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_product_event", step_record)
    monkeypatch.setattr("modules.observability.adapters.record_annotation", annotation_record)

    envelope = _approved(edited_yn=False)
    await handler(envelope)
    await handler(envelope)

    assert step_record.await_count == 1
    assert annotation_record.await_count == 1


@pytest.mark.asyncio
async def test_the_writer_upserts_the_human_row_through_the_score_seam() -> None:
    """The queue has no table of its own: it is the score upsert, once, with
    ``source = 'human'``."""
    connection = AsyncMock()

    await record_annotation(connection, _rejected_mirror(), trace_id=_TRACE_ID, occurred_at=_NOW)

    statement = connection.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    # The insert's bound row, with sqlalchemy's per-row suffix trimmed: the whole
    # row, not a pick of its columns, because the queue's contract IS its shape.
    row = {
        key.removesuffix("_m0"): value
        for key, value in compiled.params.items()
        if key.endswith("_m0")
    }
    assert row == {
        "score_date": _NOW.astimezone(UTC).date(),
        "source": SOURCE_HUMAN,
        "observation_kind": OBSERVATION_KIND_PRESCRIPTION,
        "observation_ref": str(_PRESCRIPTION_REF),
        "trace_id": _TRACE_ID,
        "evaluator": ANNOTATION_EVALUATOR_REJECTED,
        "data_type": DATA_TYPE_BOOLEAN,
        "value": Decimal("1.0"),
    }


@pytest.mark.asyncio
async def test_an_unmapped_payload_writes_nothing_at_all() -> None:
    """The ledger row already exists by the time the writer runs; a vocabulary
    disagreement between registries writes no half-row and raises nothing."""
    connection = AsyncMock()
    payload = CaseConsultCompleteTelemetryPayload(
        case_id=7, patient_id=_PATIENT_REF, doctor_id=_DOCTOR_REF
    )

    await record_annotation(connection, payload, trace_id=None, occurred_at=_NOW)

    assert connection.execute.await_count == 0
