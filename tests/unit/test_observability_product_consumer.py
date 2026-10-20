"""B4e #739: the product event ledger consumer - one row per delivery, replay-safe.

The SQL the writer builds and the handler seats the registry generates, both without
a database: the statement's bound values are read off the compiled statement, and the
seats are driven through the same short-lived-engine + consumed-event-ledger seam the
live dispatcher uses, so a replayed ``event_id`` is a ledger no-op that never reaches
the write.

The integration round trip (``test_observability_consumer_round_trip.py``) proves the
same contract against real Postgres; these are the fast ones that name a column.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast, get_args
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.dialects import postgresql

from bus.envelope import Envelope
from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
)
from bus.registry import HandlerRegistry
from modules.observability.adapters import (
    _mirror_for,
)
from modules.observability.adapters import (
    register_handlers as register_obs_handlers,
)
from modules.observability.domain.consumer import (
    ANNOTATION_EVENT_MIRRORS,
    BUSINESS_EVENT_METRICS,
    PRODUCT_EVENT_MIRRORS,
    CaseClosedTelemetryPayload,
    CaseConsultCompleteTelemetryPayload,
    IntakeCapturedTelemetryPayload,
    IntakeComposerOpenedTelemetryPayload,
    IntakeRetryRequestedTelemetryPayload,
)
from modules.observability.domain.exceptions import ProductOutcomeNotAllowed
from modules.observability.domain.product import (
    PRODUCT_OUTCOME_COMPLETED,
    PRODUCT_OUTCOME_RE_RECORDED,
    ProductOutcome,
    derived_step_key,
    product_step_for_event,
    product_steps,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.facade import record_product_event

_NOW = datetime(2026, 10, 13, 8, 15, 0, tzinfo=UTC)
_EVENT_ID = UUID("11111111-2222-3333-4444-555555555555")
_PATIENT_REF = 3
_DOCTOR_REF = 9


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


def _entry_envelope(
    *,
    event_id: UUID = _EVENT_ID,
    patient_id: int = _PATIENT_REF,
    trace_id: str = "a" * 32,
) -> Envelope[IntakeComposerOpenedTelemetryPayload]:
    return Envelope[IntakeComposerOpenedTelemetryPayload](
        event_id=event_id,
        event_type=EVENT_INTAKE_COMPOSER_OPENED,
        producer="intake",
        occurred_at=_NOW,
        payload=IntakeComposerOpenedTelemetryPayload(
            patient_id=patient_id,
            # #721's own convention: the session scope IS the request's trace.
            session_key=trace_id,
            trace_id=trace_id,
        ),
    )


# --------------------------------------------------------------- the handler seats


def test_every_registered_step_has_a_handler_seat_and_the_mirror_covers_them() -> None:
    """The registry generates the seats; no step is consumed by hand-written code."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)

    for step in product_steps():
        assert registry.handlers_for(step.event_type), step.event_type
    assert set(PRODUCT_EVENT_MIRRORS) == {step.event_type for step in product_steps()}


def test_every_consumed_event_type_gets_exactly_one_seat() -> None:
    """One seat per event type, because the consumed-event ledger is keyed by it alone.

    A second handler delivered the same envelope would find the first one's ledger
    row, be told it is a replay, and skip its own effect forever - invisibly.
    The annotation queue (#752) is in the sweep: ``prescription.approved`` is both a
    funnel step and a review outcome, and a second seat for it would never write
    its annotation.
    """
    registry = HandlerRegistry()
    register_obs_handlers(registry)

    consumed = {step.event_type for step in product_steps()} | set(BUSINESS_EVENT_METRICS)
    for event_type in consumed | set(ANNOTATION_EVENT_MIRRORS):
        assert len(registry.handlers_for(event_type)) == 1, event_type


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", [EVENT_CASE_CONSULT_COMPLETE, EVENT_CASE_CLOSED])
async def test_an_event_that_is_both_a_business_event_and_a_step_runs_both_effects(
    monkeypatch: pytest.MonkeyPatch, event_type: str
) -> None:
    """``case.*`` counts as business AND records a funnel step: one seat, both effects.

    Sharing the seat is what makes both actually land. Two seats would let whichever
    ran first consume the delivery and quietly starve the other.
    """
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    assert len(registry.handlers_for(event_type)) == 1

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    count = AsyncMock()
    record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.accumulate_business_count", count)
    monkeypatch.setattr("modules.observability.adapters.record_product_event", record)

    step = product_step_for_event(event_type)
    assert step is not None
    envelope = Envelope[BaseModel](
        event_id=uuid4(),
        event_type=event_type,
        producer="care",
        occurred_at=_NOW,
        payload=_sample_payload(_mirror_for(event_type, {event_type: step})),
    )

    await registry.handlers_for(event_type)[0](envelope)
    assert count.await_count == 1
    assert count.await_args.args[2] == event_type
    assert record.await_count == 1
    assert record.await_args.args[2] is step


@pytest.mark.asyncio
async def test_a_replayed_event_runs_neither_effect_of_a_shared_seat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ledger row gates BOTH effects, so a replay cannot double the funnel."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_CASE_CLOSED)[0]

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    count = AsyncMock()
    record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.accumulate_business_count", count)
    monkeypatch.setattr("modules.observability.adapters.record_product_event", record)

    envelope = Envelope[BaseModel](
        event_id=_EVENT_ID,
        event_type=EVENT_CASE_CLOSED,
        producer="care",
        occurred_at=_NOW,
        payload=_sample_payload(CaseClosedTelemetryPayload),
    )

    await handler(envelope)
    await handler(envelope)
    assert count.await_count == 1
    assert record.await_count == 1


@pytest.mark.asyncio
async def test_the_entry_step_handler_writes_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redelivered ``event_id`` is a ledger no-op that never reaches the writer."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_INTAKE_COMPOSER_OPENED)[0]

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_product_event", record)

    envelope = _entry_envelope()

    await handler(envelope)
    assert record.await_count == 1
    step = record.await_args.args[2]
    assert step.funnel == "intake"
    assert step.step == "composer_opened"

    await handler(envelope)
    assert record.await_count == 1


# ------------------------------------------------------------------ the statement


def _compiled_values(
    connection: AsyncMock,
) -> dict[str, object]:
    statement = connection.execute.await_args.args[0]
    return statement.compile(dialect=postgresql.dialect()).params


@pytest.mark.asyncio
async def test_the_entry_step_row_carries_the_published_trace_and_a_hashed_actor() -> None:
    """The composer's entry step lands with everything the ledger row declares."""
    step = product_step_for_event(EVENT_INTAKE_COMPOSER_OPENED)
    assert step is not None
    connection = AsyncMock()

    await record_product_event(connection, _entry_envelope(), step, _entry_envelope().payload)

    values = _compiled_values(connection)
    assert values["event_id"] == _EVENT_ID
    assert values["occurred_at"] == _NOW
    assert values["actor_kind"] == ACTOR_KIND_PATIENT
    assert values["actor_key"] == actor_key(ACTOR_KIND_PATIENT, _PATIENT_REF)
    assert values["trace_id"] == "a" * 32
    assert values["session_key"] == "a" * 32
    assert values["funnel"] == step.funnel
    assert values["step"] == "composer_opened"
    assert values["outcome"] == PRODUCT_OUTCOME_COMPLETED
    # The composer opening is an instant, not a span, so it records no duration at
    # all rather than a zero that would read as "took no time".
    assert values["duration_ms"] is None


@pytest.mark.asyncio
async def test_the_ledger_write_is_insert_do_nothing_on_the_event_id() -> None:
    """AC5: replaying the same identifiers changes nothing, belt and braces."""
    step = product_step_for_event(EVENT_INTAKE_COMPOSER_OPENED)
    assert step is not None
    connection = AsyncMock()

    await record_product_event(connection, _entry_envelope(), step, _entry_envelope().payload)

    statement = connection.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (event_id) DO NOTHING" in sql
    assert "observability_product_events" in sql


@pytest.mark.asyncio
async def test_the_writer_refuses_an_outcome_its_step_does_not_declare() -> None:
    """Decision 24 is enforced at the write, not only declared in the registry.

    The registration guard proves the REGISTRY is coherent; this proves the writer is
    reading that entry. A writer that invented or defaulted an outcome would slip past
    a perfectly coherent registry and quietly record ``errored`` steps as drop-offs.
    """
    step = product_step_for_event(EVENT_INTAKE_CAPTURED)
    assert step is not None
    smuggled = replace(step, outcome=cast("ProductOutcome", "abandoned"))
    connection = AsyncMock()

    with pytest.raises(ProductOutcomeNotAllowed) as caught:
        envelope = _entry_envelope()
        await record_product_event(connection, envelope, smuggled, envelope.payload)

    assert caught.value.step == smuggled.step
    assert connection.execute.await_count == 0


@pytest.mark.asyncio
async def test_a_step_without_a_published_trace_records_the_derived_key() -> None:
    """The column is NOT NULL, so a producer with no trace gets a stable stand-in."""
    step = product_step_for_event(EVENT_INTAKE_CAPTURED)
    assert step is not None
    envelope = Envelope[IntakeCapturedTelemetryPayload](
        event_id=_EVENT_ID,
        event_type=EVENT_INTAKE_CAPTURED,
        producer="intake",
        occurred_at=_NOW,
        payload=IntakeCapturedTelemetryPayload(
            intake_id=17,
            patient_id=_PATIENT_REF,
            duration_s=12.5,
        ),
    )
    connection = AsyncMock()

    await record_product_event(connection, envelope, step, envelope.payload)

    values = _compiled_values(connection)
    assert values["trace_id"] == derived_step_key(_EVENT_ID)
    assert values["session_key"] == derived_step_key(_EVENT_ID)
    assert values["step"] == "intake_captured"
    assert values["duration_ms"] == 12500


@pytest.mark.asyncio
async def test_a_clinical_step_is_attributed_to_the_doctor_who_did_it() -> None:
    """Active actors are people-shaped, so the consult step counts the clinician."""
    step = product_step_for_event(EVENT_CASE_CONSULT_COMPLETE)
    assert step is not None
    envelope = Envelope[CaseConsultCompleteTelemetryPayload](
        event_id=_EVENT_ID,
        event_type=EVENT_CASE_CONSULT_COMPLETE,
        producer="care",
        occurred_at=_NOW,
        payload=CaseConsultCompleteTelemetryPayload(
            case_id=4,
            patient_id=_PATIENT_REF,
            doctor_id=_DOCTOR_REF,
        ),
    )
    connection = AsyncMock()

    await record_product_event(connection, envelope, step, envelope.payload)

    values = _compiled_values(connection)
    assert values["actor_kind"] == ACTOR_KIND_DOCTOR
    assert values["actor_key"] == actor_key(ACTOR_KIND_DOCTOR, _DOCTOR_REF)


@pytest.mark.asyncio
async def test_a_machine_step_records_no_actor_rather_than_a_placeholder() -> None:
    """``intake.retry_requested`` names no identity, so both actor columns stay NULL."""
    step = product_step_for_event(EVENT_INTAKE_RETRY_REQUESTED)
    assert step is not None
    envelope = Envelope[IntakeRetryRequestedTelemetryPayload](
        event_id=_EVENT_ID,
        event_type=EVENT_INTAKE_RETRY_REQUESTED,
        producer="intake",
        occurred_at=_NOW,
        payload=IntakeRetryRequestedTelemetryPayload(intake_id=17, record_attempt=2),
    )
    connection = AsyncMock()

    await record_product_event(connection, envelope, step, envelope.payload)

    values = _compiled_values(connection)
    assert values["actor_kind"] is None
    assert values["actor_key"] is None
    assert values["outcome"] == PRODUCT_OUTCOME_RE_RECORDED


def _sample_value(annotation: object) -> object:
    """One plausible value for a required field's annotation.

    Optionals are unwrapped, because a mirror field declared ``float | None`` still
    stores that union as its annotation rather than as the number.
    """
    args = get_args(annotation)
    if args:
        annotation = args[0]
    if annotation is int:
        return _PATIENT_REF
    if annotation is float:
        return 1.5
    if annotation is bool:
        return True
    return "sample"


def _sample_payload(mirror: type[BaseModel]) -> BaseModel:
    """A minimal VALID instance of ``mirror``: one sample per required field.

    Built from the model rather than hand-written per event so a mirror that grows a
    required field cannot quietly make this parametrized sweep stop covering it.
    """
    return mirror.model_validate(
        {
            name: _sample_value(field.annotation)
            for name, field in mirror.model_fields.items()
            if field.is_required()
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        EVENT_INTAKE_COMPOSER_OPENED,
        EVENT_INTAKE_CAPTURED,
        EVENT_INTAKE_RETRY_REQUESTED,
        EVENT_PRE_SUMMARY_READY,
        EVENT_CASE_CONSULT_COMPLETE,
        EVENT_CASE_CLOSED,
        EVENT_PRESCRIPTION_DRAFT_CREATED,
        EVENT_PRESCRIPTION_APPROVED,
    ],
)
async def test_every_consumed_event_type_writes_exactly_one_ledger_row(
    monkeypatch: pytest.MonkeyPatch, event_type: str
) -> None:
    """The registry-generated seat writes the row, for each step, with no special case.

    EVERY seat for the type is driven, not just one, so a funnel step that shares an
    event type with a business count is proven to write its own row rather than to
    disappear behind the seat registered first. The annotation effect (#752) of the
    one step that carries it is stubbed here and proven in its own suite.
    """
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handlers = registry.handlers_for(event_type)
    step = product_step_for_event(event_type)
    assert step is not None

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    record = AsyncMock()
    annotation = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_product_event", record)
    monkeypatch.setattr("modules.observability.adapters.record_annotation", annotation)

    mirror = PRODUCT_EVENT_MIRRORS[event_type]
    envelope = Envelope[BaseModel](
        event_id=uuid4(),
        event_type=event_type,
        producer="intake",
        occurred_at=_NOW,
        payload=_sample_payload(mirror),
    )

    for handler in handlers:
        await handler(envelope)
    assert record.await_count == 1
    assert record.await_args.args[2] is step
