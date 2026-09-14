"""PHASE-8 T08: care event wiring - payload models, subscriptions, telemetry
(#424, FEAT-008/FEAT-009).

Pins the code-side mirror of the ``MOD-006`` rows of the §4.2 registry: care
publishes ``case.consult_complete``, ``case.closed``,
``prescription.draft_created``, ``prescription.reviewed``,
``prescription.approved``, ``prescription.rejected`` and
``prescription.issued`` (all typed, no-PHI: ids and lifecycle facts only), and
subscribes to ``pre_summary.ready``, ``pre_summary.low_confidence`` and
``report.filed`` as ledgered telemetry seams. care owns every producer payload
model it registers, incl. ``prescription.issued`` (producer owns its contract);
health consumes ``prescription.issued`` through its own tolerant mirror and
registers no model for it, so the composition registers each event type exactly
once. Covers the frozen event shapes, the ``register_handlers`` registration
seam, the ledger-deduped telemetry handlers, and an emitted-envelope
round-trip through the registry validator - all without a database.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from bus.dispatcher import OutboxRow, envelope_from_row
from bus.envelope import Envelope, is_valid_event_type
from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
    EVENT_REPORT_FILED,
)
from bus.registry import HandlerRegistry
from modules.care.adapters import (
    pre_summary_low_confidence_count,
    pre_summary_ready_count,
    register_handlers,
    report_filed_count,
)
from modules.care.domain.events import (
    PrescriptionIssuedPayload,
    case_closed_envelope,
    case_consult_complete_envelope,
    prescription_approved_envelope,
    prescription_draft_created_envelope,
    prescription_issued_envelope,
    prescription_rejected_envelope,
    prescription_reviewed_envelope,
)
from modules.health.adapters import register_handlers as health_register_handlers
from modules.health.domain.events import (
    PrescriptionIssuedPayload as HealthPrescriptionIssuedPayload,
)
from modules.intake.domain.events import (
    pre_summary_low_confidence_envelope,
    pre_summary_ready_envelope,
)

_OCCURRED_AT = "2026-09-15T10:00:00+00:00"

_ALL_PRODUCED_EVENT_TYPES = (
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_CASE_CLOSED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_REVIEWED,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_ISSUED,
)

_ALL_SUBSCRIBED_EVENT_TYPES = (
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_REPORT_FILED,
)


class _DiagnosticsReportFiledPayload(BaseModel):
    """Producer-shaped ``report.filed`` payload (extra fields care ignores)."""

    order_id: int
    patient_id: int
    filename: str
    occurred_at: str


def test_event_types_match_registry_dot_notation_and_never_snake_case() -> None:
    for event_type in (*_ALL_PRODUCED_EVENT_TYPES, *_ALL_SUBSCRIBED_EVENT_TYPES):
        assert is_valid_event_type(event_type), event_type
        assert "." in event_type, event_type
        assert event_type == event_type.lower()


def test_every_care_event_type_is_registered_in_bus_events() -> None:
    assert EVENT_CASE_CONSULT_COMPLETE == "case.consult_complete"
    assert EVENT_CASE_CLOSED == "case.closed"
    assert EVENT_PRESCRIPTION_DRAFT_CREATED == "prescription.draft_created"
    assert EVENT_PRESCRIPTION_REVIEWED == "prescription.reviewed"
    assert EVENT_PRESCRIPTION_APPROVED == "prescription.approved"
    assert EVENT_PRESCRIPTION_REJECTED == "prescription.rejected"
    assert EVENT_PRESCRIPTION_ISSUED == "prescription.issued"
    assert EVENT_PRE_SUMMARY_READY == "pre_summary.ready"
    assert EVENT_PRE_SUMMARY_LOW_CONFIDENCE == "pre_summary.low_confidence"
    assert EVENT_REPORT_FILED == "report.filed"


def test_produced_payloads_carry_no_phi_and_only_orchestration_facts() -> None:
    assert set(
        case_consult_complete_envelope(
            case_id=1, patient_id=7, doctor_id=2, pre_summary_id=5
        ).payload.model_dump()
    ) == {"case_id", "patient_id", "doctor_id", "pre_summary_id"}
    assert set(
        case_closed_envelope(
            case_id=1, patient_id=7, doctor_id=2, close_reason="patient_no_show"
        ).payload.model_dump()
    ) == {"case_id", "patient_id", "doctor_id", "close_reason"}
    assert set(
        prescription_draft_created_envelope(
            case_id=1,
            prescription_id=9,
            patient_id=7,
            doctor_id=2,
            source="ai_draft",
            attempt_no=1,
        ).payload.model_dump()
    ) == {
        "case_id",
        "prescription_id",
        "patient_id",
        "doctor_id",
        "source",
        "attempt_no",
    }
    assert set(
        prescription_reviewed_envelope(
            case_id=1, prescription_id=9, patient_id=7, doctor_id=2
        ).payload.model_dump()
    ) == {"case_id", "prescription_id", "patient_id", "doctor_id"}
    assert set(
        prescription_approved_envelope(
            case_id=1, prescription_id=9, patient_id=7, doctor_id=2, edited_yn=True
        ).payload.model_dump()
    ) == {
        "case_id",
        "prescription_id",
        "patient_id",
        "doctor_id",
        "edited_yn",
    }
    assert set(
        prescription_rejected_envelope(
            case_id=1, prescription_id=9, patient_id=7, doctor_id=2, reason="wrong_dosage"
        ).payload.model_dump()
    ) == {"case_id", "prescription_id", "patient_id", "doctor_id", "reason"}
    assert set(
        prescription_issued_envelope(
            case_id=1,
            prescription_id=9,
            patient_id=7,
            doctor_id=2,
            occurred_at=_OCCURRED_AT,
        ).payload.model_dump()
    ) == {"case_id", "prescription_id", "patient_id", "doctor_id", "occurred_at"}


def _capture_produced_envelopes() -> list[Envelope[BaseModel]]:
    return [
        case_consult_complete_envelope(case_id=1, patient_id=7, doctor_id=2, pre_summary_id=5),
        case_closed_envelope(case_id=1, patient_id=7, doctor_id=2, close_reason="patient_no_show"),
        prescription_draft_created_envelope(
            case_id=1,
            prescription_id=9,
            patient_id=7,
            doctor_id=2,
            source="ai_draft",
            attempt_no=1,
        ),
        prescription_reviewed_envelope(case_id=1, prescription_id=9, patient_id=7, doctor_id=2),
        prescription_approved_envelope(
            case_id=1, prescription_id=9, patient_id=7, doctor_id=2, edited_yn=True
        ),
        prescription_rejected_envelope(
            case_id=1, prescription_id=9, patient_id=7, doctor_id=2, reason="wrong_dosage"
        ),
        prescription_issued_envelope(
            case_id=1,
            prescription_id=9,
            patient_id=7,
            doctor_id=2,
            occurred_at=_OCCURRED_AT,
        ),
    ]


def test_register_handlers_registers_payload_models_without_duplicates() -> None:
    registry = HandlerRegistry()

    register_handlers(registry)

    for event_type in _ALL_PRODUCED_EVENT_TYPES:
        assert registry.payload_model_for(event_type) is not None
    # care is the producer of prescription.issued, so it owns the registry
    # contract - a consumer (health) never does.
    assert registry.payload_model_for(EVENT_PRESCRIPTION_ISSUED) is PrescriptionIssuedPayload


def test_health_then_care_composition_registers_issued_exactly_once() -> None:
    # health consumes prescription.issued but must NOT register its model (care
    # does): health-first / care-second is the real worker composition order,
    # so a health registration would trip care's duplicate guard and crash boot.
    registry = HandlerRegistry()
    health_register_handlers(registry)
    register_handlers(registry)

    assert registry.payload_model_for(EVENT_PRESCRIPTION_ISSUED) is PrescriptionIssuedPayload


def test_health_consumer_mirror_accepts_cares_produced_payload() -> None:
    produced = prescription_issued_envelope(
        case_id=1,
        prescription_id=9,
        patient_id=7,
        doctor_id=2,
        occurred_at=_OCCURRED_AT,
    )
    raw = produced.payload.model_dump(mode="json")
    # The consumer mirror requires prescription_id, patient_id, occurred_at and
    # drops producer-only case_id/doctor_id on validate - the dispatch-time
    # re-validation that previously failed every real issuance (missing
    # occurred_at) now passes against the care-produced payload.
    view = HealthPrescriptionIssuedPayload.model_validate(raw)
    assert view.prescription_id == 9
    assert view.patient_id == 7
    assert view.occurred_at == _OCCURRED_AT


def test_register_handlers_registers_the_inbound_subscriptions() -> None:
    registry = HandlerRegistry()

    register_handlers(registry)

    for event_type in _ALL_SUBSCRIBED_EVENT_TYPES:
        assert registry.handlers_for(event_type)
    # care does not self-subscribe to its own produced events (MOD-006 -> MOD-006
    # consumers land in later phases) - no handler seat for any published event.
    for event_type in _ALL_PRODUCED_EVENT_TYPES:
        assert registry.handlers_for(event_type) == ()


def test_register_handlers_twice_on_one_registry_raises_duplicate() -> None:
    registry = HandlerRegistry()

    register_handlers(registry)

    with pytest.raises(ValueError):
        register_handlers(registry)


def test_emitted_envelope_round_trips_through_the_registry_validator() -> None:
    registry = HandlerRegistry()
    register_handlers(registry)

    for envelope in _capture_produced_envelopes():
        row = _row_for(envelope)
        payload_model = registry.payload_model_for(envelope.event_type)
        assert payload_model is not None

        reconstructed = envelope_from_row(row, "care", payload_model)

        assert reconstructed.event_type == envelope.event_type
        assert reconstructed.event_id == envelope.event_id
        assert reconstructed.producer == "care"
        assert isinstance(reconstructed.payload, payload_model)
        assert reconstructed.payload.model_dump(mode="json") == row.payload


def _wire_delivery_mocks(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> set[str]:
    """Stub the run_handler engine + ledger so deliveries dedupe in-memory."""
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()

    async def fake_ledger(
        connection: Any, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del connection, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    caplog.set_level(logging.INFO, logger="modules.care.adapters")
    return delivered


@pytest.mark.asyncio
async def test_pre_summary_ready_telemetry_logs_and_counts_distinct_events(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    registry = HandlerRegistry()
    register_handlers(registry)
    handler = registry.handlers_for(EVENT_PRE_SUMMARY_READY)[0]

    _wire_delivery_mocks(monkeypatch, caplog)

    before = pre_summary_ready_count()
    first = pre_summary_ready_envelope(intake_id=1, pre_summary_id=5)
    second = pre_summary_ready_envelope(intake_id=2, pre_summary_id=8)

    await handler(first)
    assert pre_summary_ready_count() == before + 1

    await handler(first)
    assert pre_summary_ready_count() == before + 1

    await handler(second)
    assert pre_summary_ready_count() == before + 2

    assert "pre_summary.ready telemetry" in caplog.text
    assert "intake_id=1 pre_summary_id=5" in caplog.text
    # The outbox event_id is the async correlation key (error-handling-observability §3).
    assert str(first.event_id) in caplog.text


@pytest.mark.asyncio
async def test_pre_summary_low_confidence_telemetry_logs_and_counts_distinct_events(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    registry = HandlerRegistry()
    register_handlers(registry)
    handler = registry.handlers_for(EVENT_PRE_SUMMARY_LOW_CONFIDENCE)[0]

    _wire_delivery_mocks(monkeypatch, caplog)

    before = pre_summary_low_confidence_count()
    first = pre_summary_low_confidence_envelope(intake_id=1, pre_summary_id=5)
    second = pre_summary_low_confidence_envelope(intake_id=2, pre_summary_id=8)

    await handler(first)
    assert pre_summary_low_confidence_count() == before + 1

    await handler(first)
    assert pre_summary_low_confidence_count() == before + 1

    await handler(second)
    assert pre_summary_low_confidence_count() == before + 2

    assert "pre_summary.low_confidence telemetry" in caplog.text
    assert "intake_id=2 pre_summary_id=8" in caplog.text
    assert str(first.event_id) in caplog.text


@pytest.mark.asyncio
async def test_report_filed_telemetry_logs_and_counts_ignoring_producer_extra_fields(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    registry = HandlerRegistry()
    register_handlers(registry)
    handler = registry.handlers_for(EVENT_REPORT_FILED)[0]

    _wire_delivery_mocks(monkeypatch, caplog)

    before = report_filed_count()
    first = _report_filed_envelope(order_id=31, patient_id=7, filename="report_31.pdf")
    second = _report_filed_envelope(order_id=32, patient_id=7, filename="report_32.pdf")

    await handler(first)
    assert report_filed_count() == before + 1

    await handler(first)
    assert report_filed_count() == before + 1

    await handler(second)
    assert report_filed_count() == before + 2

    assert "report.filed telemetry" in caplog.text
    assert "order_id=31" in caplog.text
    assert str(first.event_id) in caplog.text
    # The consumer mirror drops producer-only fields - never the filename or a
    # patient id in the care log.
    assert "report_31.pdf" not in caplog.text


def _report_filed_envelope(*, order_id: int, patient_id: int, filename: str) -> Envelope[BaseModel]:
    return Envelope(
        event_id=uuid4(),
        event_type=EVENT_REPORT_FILED,
        producer="diagnostics",
        payload=_DiagnosticsReportFiledPayload(
            order_id=order_id,
            patient_id=patient_id,
            filename=filename,
            occurred_at=_OCCURRED_AT,
        ),
    )


def _row_for(envelope: Envelope[BaseModel]) -> OutboxRow:
    return OutboxRow(
        id=uuid4(),
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        payload=envelope.payload.model_dump(mode="json"),
        occurred_at=datetime.now(UTC),
        next_attempt_at=datetime.now(UTC),
        attempts=0,
    )
