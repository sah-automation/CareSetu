"""B4b #703: MOD-013 business-count + guardrail-alert consumer (no DB).

Covers the second half of MOD-013's subscriptions: the registry-driven business
counts (``case.*`` / ``partner.*`` / ``consent.*`` / ``record.accessed`` /
``audit.event``) that roll into ``observability_business_daily`` and the two
guardrail signals (``audit.tamper_detected``, ``ai_egress.recorded``) that write
PHI-free ``observability_alert_events`` rows. The tests drive the registered
handlers through the same short-lived engine + ledger seam as the live
dispatcher, so a replayed ``event_id`` is a ledger no-op that never reaches the
effect. The alert builders are asserted PHI-free (ids and facts only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.dialects import postgresql

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AUDIT_EVENT,
    EVENT_AUDIT_TAMPER_DETECTED,
    EVENT_CONSENT_GRANTED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_RECORD_ACCESSED,
)
from bus.registry import HandlerRegistry
from modules.audit.adapters import register_handlers as register_audit_handlers
from modules.audit.domain.consumer import AuditEventPayload
from modules.care.adapters import register_handlers as register_care_handlers
from modules.consent.adapters import register_handlers as register_consent_handlers
from modules.consent.domain.events import ConsentGrantedPayload
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.iam.domain.consumer import PartnerActivatedPayload
from modules.intake.adapters import register_handlers as register_intake_handlers
from modules.intake.domain.events import AiEgressRecordedPayload
from modules.observability.adapters import (
    _BUSINESS_EVENT_MIRRORS,
)
from modules.observability.adapters import (
    register_handlers as register_obs_handlers,
)
from modules.observability.domain.consumer import (
    BUSINESS_EVENT_METRICS,
    AiEgressRecordedTelemetryPayload,
    ConsentLifecycleTelemetryPayload,
    PartnerSelectedTelemetryPayload,
    PartnerVerificationStartedTelemetryPayload,
    RecordAccessTelemetryPayload,
    TamperDetectedTelemetryPayload,
    build_ai_egress_alert,
    build_tamper_alert,
)
from modules.observability.facade import accumulate_business_count

_NOW = datetime(2026, 10, 13, 8, 15, 0, tzinfo=UTC)


def _composition_registry() -> HandlerRegistry:
    """Every producing module plus MOD-013, in the worker's register order."""
    registry = HandlerRegistry()
    for register in (
        register_iam_handlers,
        register_consent_handlers,
        register_intake_handlers,
        register_care_handlers,
        register_audit_handlers,
        register_obs_handlers,
    ):
        register(registry)
    return registry


def _patch_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)


def _fake_ledger(monkeypatch: pytest.MonkeyPatch, delivered: set[str]) -> None:
    async def ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", ledger)


def test_business_events_register_one_handler_and_only_claim_unowned_models() -> None:
    """Every business family has one seat; MOD-013 claims only unowned models."""
    registry = _composition_registry()

    for event_type in BUSINESS_EVENT_METRICS:
        assert registry.handlers_for(event_type), event_type

    # MOD-013 owns the two models no other module claimed.
    assert (
        registry.payload_model_for(EVENT_PARTNER_VERIFICATION_STARTED)
        is PartnerVerificationStartedTelemetryPayload
    )
    assert registry.payload_model_for(EVENT_PARTNER_SELECTED) is PartnerSelectedTelemetryPayload

    # Owned models stay owned by their producer - MOD-013 registered no duplicate
    # (which ``register_payload_model`` would have raised on).
    assert registry.payload_model_for(EVENT_PARTNER_ACTIVATED) is PartnerActivatedPayload
    assert registry.payload_model_for(EVENT_CONSENT_GRANTED) is ConsentGrantedPayload
    assert registry.payload_model_for(EVENT_AUDIT_EVENT) is AuditEventPayload
    assert registry.payload_model_for(EVENT_AI_EGRESS_RECORDED) is AiEgressRecordedPayload


def test_business_mirror_registry_matches_the_metric_registry() -> None:
    """The handler-mirror registry and the metric-key registry share one key set."""
    assert set(_BUSINESS_EVENT_MIRRORS) == set(BUSINESS_EVENT_METRICS)


def test_observability_registers_exactly_one_seat_per_business_event() -> None:
    """MOD-013's own registry has exactly one seat per business subscription."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)

    for event_type in BUSINESS_EVENT_METRICS:
        assert len(registry.handlers_for(event_type)) == 1, event_type


@pytest.mark.asyncio
async def test_business_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op that never touches the aggregate."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_CONSENT_GRANTED)[0]

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    accumulate = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.accumulate_business_count", accumulate)

    envelope = Envelope[ConsentLifecycleTelemetryPayload](
        event_id=uuid4(),
        event_type=EVENT_CONSENT_GRANTED,
        producer="consent",
        occurred_at=_NOW,
        payload=ConsentLifecycleTelemetryPayload(
            consent_id=7,
            lineage_ref="lineage-7",
            patient_id=3,
            counterparty_type="doctor",
            counterparty_id="42",
            record_scope="consultations",
            version=2,
        ),
    )

    await handler(envelope)
    assert accumulate.await_count == 1
    assert accumulate.await_args.args[2] == EVENT_CONSENT_GRANTED

    await handler(envelope)
    assert accumulate.await_count == 1


@pytest.mark.asyncio
async def test_tamper_handler_writes_one_phi_free_alert_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``audit.tamper_detected`` -> one critical alert row, PHI-free, replay-safe."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AUDIT_TAMPER_DETECTED)[0]

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_alert_event", record)

    envelope = Envelope[TamperDetectedTelemetryPayload](
        event_id=uuid4(),
        event_type=EVENT_AUDIT_TAMPER_DETECTED,
        producer="audit",
        occurred_at=_NOW,
        payload=TamperDetectedTelemetryPayload(
            attempted_operation="UPDATE",
            target_event_id="11111111-1111-1111-1111-111111111111",
            attempted_at=_NOW,
        ),
    )

    await handler(envelope)
    assert record.await_count == 1
    alert = record.await_args.args[1]
    assert alert.severity == "critical"
    assert alert.kind == "audit_tamper"
    assert alert.title
    assert set(alert.payload) == {
        "source",
        "attempted_operation",
        "target_event_id",
        "attempted_at",
    }

    await handler(envelope)
    assert record.await_count == 1


@pytest.mark.asyncio
async def test_ai_egress_handler_surfaces_the_guardrail_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ai_egress.recorded`` -> one informational alert row, ids + reason only."""
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AI_EGRESS_RECORDED)[0]

    _patch_delivery(monkeypatch)
    _fake_ledger(monkeypatch, set())
    record = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.record_alert_event", record)

    envelope = Envelope[AiEgressRecordedTelemetryPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_EGRESS_RECORDED,
        producer="intake",
        occurred_at=_NOW,
        payload=AiEgressRecordedTelemetryPayload(
            intake_id=5,
            ai_job_id=9,
            reason="structure egress of intake context to EXT-002",
        ),
    )

    await handler(envelope)
    assert record.await_count == 1
    alert = record.await_args.args[1]
    assert alert.kind == "ai_egress"
    assert alert.payload == {
        "source": "intake",
        "intake_id": 5,
        "ai_job_id": 9,
        "reason": "structure egress of intake context to EXT-002",
    }


def test_tamper_alert_drops_the_producer_details_blob() -> None:
    """The producer's row-data ``details`` never reaches the alert payload."""
    alert = build_tamper_alert(
        TamperDetectedTelemetryPayload(
            attempted_operation="DELETE",
            target_event_id=None,
            attempted_at=_NOW,
        ),
        "audit",
    )
    assert "details" not in alert.payload
    assert "old_data" not in alert.payload
    assert "new_data" not in alert.payload
    assert alert.payload["attempted_at"] == _NOW.isoformat()


def test_egress_alert_carries_no_egressed_bytes() -> None:
    """The egress alert payload is bounded to pseudonymous ids and the reason."""
    alert = build_ai_egress_alert(
        AiEgressRecordedTelemetryPayload(intake_id=1, ai_job_id=2, reason="transcribe egress"),
        "intake",
    )
    assert set(alert.payload) == {"source", "intake_id", "ai_job_id", "reason"}


@pytest.mark.asyncio
async def test_accumulate_business_count_upserts_keyed_by_metric_and_date() -> None:
    """The facade statement is keyed by ``metric_key`` + envelope occurrence date."""
    connection = AsyncMock()
    envelope = Envelope[RecordAccessTelemetryPayload](
        event_id=uuid4(),
        event_type=EVENT_RECORD_ACCESSED,
        producer="health",
        occurred_at=_NOW,
        payload=RecordAccessTelemetryPayload(
            record_id=1,
            actor_id=2,
            actor_type="patient",
            scope="full_record",
            accessed_at=_NOW,
        ),
    )

    await accumulate_business_count(connection, envelope, EVENT_RECORD_ACCESSED)

    statement = connection.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["metric_key"] == EVENT_RECORD_ACCESSED
    assert compiled.params["metric_date"] == _NOW.date()
