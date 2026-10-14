"""B4a #702: MOD-013 consumer registration + exactly-once accumulation (no DB).

Covers the composition-root seam: the ``ai_job.completed`` / ``ai_job.failed``
consumers register handler seats at the worker without ever owning (or
stealing) the ``ai_job.*`` registry payload models - MOD-005 owns those, and
MOD-013 merely re-validates the dispatched intake payload into its local mirror
(the MOD-011 consumer shape). The replay test drives the registered handler
through the same short-lived engine + ledger seam as the live dispatcher: a
replayed ``event_id`` is a no-op (ledger dedupe), so the aggregate upsert
effect runs exactly once per distinct event.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import EVENT_AI_JOB_COMPLETED, EVENT_AI_JOB_FAILED
from bus.registry import HandlerRegistry
from modules.intake.adapters import register_handlers as register_intake_handlers
from modules.intake.domain.events import (
    AiJobCompletedPayload,
    AiJobFailedPayload,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
)
from modules.observability.adapters import register_handlers as register_obs_handlers
from modules.observability.domain.consumer import (
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
)


def test_register_handlers_registers_both_consumers_without_owning_the_models() -> None:
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)

    # MOD-013 has exactly one consumer seat per ai_job.* event type.
    assert len(registry.handlers_for(EVENT_AI_JOB_COMPLETED)) == 1
    assert len(registry.handlers_for(EVENT_AI_JOB_FAILED)) == 1

    # MOD-005 still owns the registry payload models; MOD-013 never registered a
    # duplicate (which the registry's one-model-per-type guard would reject).
    assert registry.payload_model_for(EVENT_AI_JOB_COMPLETED) is AiJobCompletedPayload
    assert registry.payload_model_for(EVENT_AI_JOB_FAILED) is AiJobFailedPayload


def test_intake_completed_payload_revalidates_into_the_observability_mirror() -> None:
    envelope = ai_job_completed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="structure",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=900,
        output_tokens=150,
        cost_paise=24,
        duration_ms=1200,
        low_confidence=True,
        patient_id=7,
        doctor_id=8,
        trace_id="e" * 32,
    )
    mirror = AiJobCompletedUsagePayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, AiJobCompletedUsagePayload)
    assert mirror.provider == "openai"
    assert mirror.model == "gpt-4o-mini"
    assert mirror.input_tokens == 900
    assert mirror.output_tokens == 150
    assert mirror.cost_paise == 24
    assert mirror.duration_ms == 1200
    assert mirror.low_confidence is True
    # B4c (#719): the widened identity references revalidate into the mirror.
    assert mirror.patient_id == 7
    assert mirror.doctor_id == 8
    assert mirror.trace_id == "e" * 32


def test_intake_failed_payload_revalidates_into_the_observability_mirror() -> None:
    envelope = ai_job_failed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="transcribe",
        reason="Ext002CallError",
        provider="openai",
        model="whisper-1",
        timeout=True,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )
    mirror = AiJobFailedUsagePayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, AiJobFailedUsagePayload)
    assert mirror.provider == "openai"
    assert mirror.model == "whisper-1"
    assert mirror.reason == "Ext002CallError"
    assert mirror.timeout is True
    # B4c (#719): the transcription leg has no doctor; the reference stays null.
    assert mirror.patient_id == 7
    assert mirror.doctor_id is None
    assert mirror.trace_id is None


@pytest.mark.asyncio
async def test_completed_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op that never touches the aggregate."""
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AI_JOB_COMPLETED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_ai_usage", accumulate)

    first = ai_job_completed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="structure",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=900,
        output_tokens=150,
        cost_paise=24,
        duration_ms=1200,
        low_confidence=True,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )
    second = ai_job_completed_envelope(
        ai_job_id=10,
        intake_id=42,
        task_type="structure",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=600,
        output_tokens=90,
        cost_paise=14,
        duration_ms=800,
        low_confidence=False,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )

    await handler(first)
    assert accumulate.await_count == 1
    assert isinstance(accumulate.await_args.args[2], AiJobCompletedUsagePayload)
    assert accumulate.await_args.args[2].low_confidence is True

    await handler(first)
    assert accumulate.await_count == 1

    await handler(second)
    assert accumulate.await_count == 2
    assert accumulate.await_args.args[2].low_confidence is False


@pytest.mark.asyncio
async def test_failed_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AI_JOB_FAILED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_ai_usage", accumulate)

    timeout = ai_job_failed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="structure",
        reason="Ext002CallError",
        provider="openai",
        model="gpt-4o-mini",
        timeout=True,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )
    malformed = ai_job_failed_envelope(
        ai_job_id=10,
        intake_id=42,
        task_type="structure",
        reason="ValidationError",
        provider="openai",
        model="gpt-4o-mini",
        timeout=False,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )

    await handler(timeout)
    assert accumulate.await_count == 1
    assert accumulate.await_args.args[2].timeout is True

    await handler(timeout)
    assert accumulate.await_count == 1

    await handler(malformed)
    assert accumulate.await_count == 2
    assert accumulate.await_args.args[2].timeout is False
