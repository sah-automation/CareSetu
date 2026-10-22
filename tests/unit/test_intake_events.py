"""PHASE-7 T04: intake + AI pre-summary event payloads/builders + wiring (ticket #349).

Pins the code-side mirror of the §4.2 registry names the intake module
publishes: every event names the orchestration/audit facts (ids, the task
kind, retry attempt, failure reason) and never carries PHI (transcript,
structured clinical fields, confidence scores, egressed bytes stay in the
``intake`` schema - security-phii-standards no-PHI). ``intake.started``
(PHASE-7 T05 #369) carries the funnel facts - patient id, mode, language -
and has no intake id yet because it precedes capture. The ``ai_job.*`` events
also carry the operational metering facts MOD-013 accumulates (B4a #702) -
provider/model, tokens, priced cost, duration and the *derived*
``low_confidence`` flag (the raw confidence score still never travels).
``intake.composer_opened`` (B4e #721) is the funnel's real ENTRY step: it fires
when a patient opens the composer, before any capture, and carries the patient,
the session key and the trace id - never an intake id, because no intake exists
yet. Covers the frozen event shapes, the ``register_handlers`` registration seam
(payload models + the ``intake.started`` telemetry and ``intake.captured`` self-
subscriptions), and an emitted-envelope round-trip through the registry
validator - all without a database.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, get_args
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import CheckConstraint

from bus.dispatcher import OutboxRow, envelope_from_row
from bus.envelope import Envelope, is_valid_event_type
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AI_JOB_QUEUED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_DOCTOR_ASSIGNED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_INTAKE_STARTED,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
)
from bus.registry import HandlerRegistry
from modules.intake.adapters import intake_started_count, register_handlers
from modules.intake.domain.events import (
    PRODUCER_MODULE,
    AiTaskType,
    IntakeComposerOpenedPayload,
    IntakeStartedPayload,
    ai_egress_recorded_envelope,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
    intake_captured_envelope,
    intake_composer_opened_envelope,
    intake_doctor_assigned_envelope,
    intake_retry_requested_envelope,
    intake_started_envelope,
    pre_summary_low_confidence_envelope,
    pre_summary_ready_envelope,
)
from modules.intake.schema.models import intake_ai_jobs

_ALL_EVENT_TYPES = (
    EVENT_INTAKE_STARTED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AI_JOB_QUEUED,
    EVENT_AI_EGRESS_RECORDED,
    EVENT_INTAKE_DOCTOR_ASSIGNED,
)


def test_producer_names_the_intake_module() -> None:
    assert PRODUCER_MODULE == "intake"


def test_event_types_match_registry_dot_notation_and_never_snake_case() -> None:
    for event_type in _ALL_EVENT_TYPES:
        assert is_valid_event_type(event_type), event_type
        assert "." in event_type, event_type
        # registry grammar is lowercase 'domain.action'; no snake_case segment.
        assert event_type == event_type.lower()


def test_every_intake_event_type_is_registered_in_bus_events() -> None:
    # The four-part names (pre_summary.*, ai_job.*, ai_egress.*) are not in the
    # legacy snake_case gated domains, but each must resolve to a canonical
    # dot-notation constant, not an ad hoc string.
    assert EVENT_INTAKE_STARTED == "intake.started"
    assert EVENT_INTAKE_CAPTURED == "intake.captured"
    assert EVENT_INTAKE_RETRY_REQUESTED == "intake.retry_requested"
    assert EVENT_PRE_SUMMARY_READY == "pre_summary.ready"
    assert EVENT_PRE_SUMMARY_LOW_CONFIDENCE == "pre_summary.low_confidence"
    assert EVENT_AI_JOB_COMPLETED == "ai_job.completed"
    assert EVENT_AI_JOB_FAILED == "ai_job.failed"
    assert EVENT_AI_JOB_QUEUED == "ai_job.queued"
    assert EVENT_AI_EGRESS_RECORDED == "ai_egress.recorded"
    assert EVENT_INTAKE_DOCTOR_ASSIGNED == "intake.doctor_assigned"
    assert EVENT_INTAKE_COMPOSER_OPENED == "intake.composer_opened"


def test_the_declared_task_type_vocabulary_is_exactly_the_schema_constraint() -> None:
    """#722 meters the drafting leg with the ALREADY-DECLARED ``draft`` type.

    Metering the prescription-drafting leg must not widen the vocabulary: the
    payload's ``AiTaskType`` and the ``ai_jobs`` check constraint stay the same
    four names, in the same order, so ``draft`` became a PRODUCED type rather
    than a new one being invented, and ``summarize`` stays declared-only.
    """
    declared = get_args(AiTaskType)
    assert declared == ("transcribe", "structure", "draft", "summarize")

    check = next(
        constraint
        for constraint in intake_ai_jobs.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_intake_ai_jobs_task_type"
    )
    assert set(re.findall(r"'(\w+)'", str(check.sqltext))) == set(declared)


def _capture_from_all_event_types() -> list[Envelope[BaseModel]]:
    return [
        intake_started_envelope(patient_id=7, mode="voice", language="hi"),
        intake_captured_envelope(intake_id=1, patient_id=7, mode="voice", duration_s=12.5),
        intake_retry_requested_envelope(intake_id=1, record_attempt=2, reason="unusable_audio"),
        pre_summary_ready_envelope(intake_id=1, pre_summary_id=5, patient_id=7),
        pre_summary_low_confidence_envelope(intake_id=1, pre_summary_id=5),
        ai_job_completed_envelope(
            ai_job_id=9,
            intake_id=1,
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
            trace_id="a" * 32,
        ),
        ai_job_failed_envelope(
            ai_job_id=9,
            intake_id=1,
            task_type="transcribe",
            reason="Ext002CallError",
            provider="openai",
            model="whisper-1",
            timeout=True,
            patient_id=7,
            doctor_id=None,
            trace_id=None,
        ),
        ai_egress_recorded_envelope(intake_id=1, ai_job_id=9, reason="structure"),
        intake_doctor_assigned_envelope(intake_id=1, patient_id=7, doctor_id=909),
        intake_composer_opened_envelope(
            patient_id=7,
            session_key="e" * 32,
            trace_id="e" * 32,
        ),
    ]


def test_intake_started_carries_patient_mode_and_language() -> None:
    envelope = intake_started_envelope(patient_id=7, mode="voice", language="hi")

    assert envelope.event_type == EVENT_INTAKE_STARTED
    assert envelope.producer == PRODUCER_MODULE
    assert envelope.payload.patient_id == 7
    assert envelope.payload.mode == "voice"
    assert envelope.payload.language == "hi"


def test_captured_carries_intake_id_patient_id_mode_and_duration() -> None:
    envelope = intake_captured_envelope(intake_id=42, patient_id=7, mode="voice", duration_s=12.5)

    assert envelope.event_type == EVENT_INTAKE_CAPTURED
    assert envelope.producer == PRODUCER_MODULE
    assert envelope.payload.intake_id == 42
    assert envelope.payload.patient_id == 7
    assert envelope.payload.mode == "voice"
    assert envelope.payload.duration_s == 12.5


def test_captured_text_mode_carries_none_duration() -> None:
    envelope = intake_captured_envelope(intake_id=42, patient_id=7, mode="text", duration_s=None)

    assert envelope.payload.mode == "text"
    assert envelope.payload.duration_s is None


def test_retry_requested_carries_the_record_attempt_and_reason() -> None:
    envelope = intake_retry_requested_envelope(
        intake_id=42, record_attempt=3, reason="unusable_audio"
    )

    assert envelope.event_type == EVENT_INTAKE_RETRY_REQUESTED
    assert envelope.payload.intake_id == 42
    assert envelope.payload.record_attempt == 3
    assert envelope.payload.reason == "unusable_audio"


def test_pre_summary_ready_names_the_summary_and_patient() -> None:
    envelope = pre_summary_ready_envelope(intake_id=42, pre_summary_id=7, patient_id=7)

    assert envelope.event_type == EVENT_PRE_SUMMARY_READY
    assert envelope.payload.intake_id == 42
    assert envelope.payload.pre_summary_id == 7
    assert envelope.payload.patient_id == 7


def test_pre_summary_low_confidence_names_the_summary() -> None:
    envelope = pre_summary_low_confidence_envelope(intake_id=42, pre_summary_id=7)

    assert envelope.event_type == EVENT_PRE_SUMMARY_LOW_CONFIDENCE
    assert envelope.payload.intake_id == 42
    assert envelope.payload.pre_summary_id == 7


def test_ai_job_completed_names_the_job_and_carries_the_metering_facts() -> None:
    envelope = ai_job_completed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="draft",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=800,
        output_tokens=120,
        cost_paise=21,
        duration_ms=950,
        low_confidence=True,
        patient_id=7,
        doctor_id=8,
        trace_id="c" * 32,
    )

    assert envelope.event_type == EVENT_AI_JOB_COMPLETED
    assert envelope.payload.ai_job_id == 9
    assert envelope.payload.intake_id == 42
    assert envelope.payload.task_type == "draft"
    # B4a (#702): the telemetry facts MOD-013 accumulates from the event alone.
    assert envelope.payload.provider == "openai"
    assert envelope.payload.model == "gpt-4o-mini"
    assert envelope.payload.input_tokens == 800
    assert envelope.payload.output_tokens == 120
    assert envelope.payload.cost_paise == 21
    assert envelope.payload.duration_ms == 950
    assert envelope.payload.low_confidence is True
    # B4c (#719): the identity references attribution reads - identity only, no PHI.
    assert envelope.payload.patient_id == 7
    assert envelope.payload.doctor_id == 8
    assert envelope.payload.trace_id == "c" * 32


def test_ai_job_failed_carries_the_operational_reason_and_timeout_class() -> None:
    envelope = ai_job_failed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="summarize",
        reason="Ext002CallError",
        provider="openai",
        model="gpt-4o-mini",
        timeout=True,
        patient_id=7,
        doctor_id=None,
        trace_id="d" * 32,
    )

    assert envelope.event_type == EVENT_AI_JOB_FAILED
    assert envelope.payload.ai_job_id == 9
    assert envelope.payload.intake_id == 42
    assert envelope.payload.task_type == "summarize"
    assert envelope.payload.reason == "Ext002CallError"
    # B4a (#702): serving scope for the aggregate + the timeout bucket.
    assert envelope.payload.provider == "openai"
    assert envelope.payload.model == "gpt-4o-mini"
    assert envelope.payload.timeout is True
    # B4c (#719): these failure legs involve no doctor, so the reference is null.
    assert envelope.payload.patient_id == 7
    assert envelope.payload.doctor_id is None
    assert envelope.payload.trace_id == "d" * 32


def test_ai_egress_recorded_names_the_job_and_reason() -> None:
    envelope = ai_egress_recorded_envelope(intake_id=42, ai_job_id=9, reason="transcribe")

    assert envelope.event_type == EVENT_AI_EGRESS_RECORDED
    assert envelope.payload.intake_id == 42
    assert envelope.payload.ai_job_id == 9
    assert envelope.payload.reason == "transcribe"


def test_doctor_assigned_names_the_intake_the_patient_and_the_doctor() -> None:
    """The care-attribution edge rides the event: all three references, nothing else.

    This is the ONLY legal path for doctor attribution (#717 decision 3): a
    consumer learns which doctor an intake belongs to from this payload, never by
    joining to the care or partner schema (ADR-0003). It deliberately carries no
    clinical content - the references only.
    """
    envelope = intake_doctor_assigned_envelope(intake_id=42, patient_id=7, doctor_id=909)

    assert envelope.event_type == EVENT_INTAKE_DOCTOR_ASSIGNED
    assert envelope.producer == PRODUCER_MODULE
    assert envelope.payload.intake_id == 42
    assert envelope.payload.patient_id == 7
    assert envelope.payload.doctor_id == 909
    assert set(envelope.payload.model_dump(mode="json")) == {
        "intake_id",
        "patient_id",
        "doctor_id",
    }


def test_composer_opened_carries_the_patient_session_key_and_trace_and_nothing_else() -> None:
    """The funnel's entry step: an arrival fact, carrying no clinical content.

    ``intake.composer_opened`` fires when a patient OPENS the composer, before
    any capture (#717 decision 4), so the funnel has an entry that an abandon
    also reaches - which ``intake.started`` cannot be, because it rides the
    capture transaction. It carries the patient, the session key and the trace
    id and nothing else: no intake id (none exists yet), no audio reference, no
    transcript, no free text (security-phii-standards no-PHI).
    """
    envelope = intake_composer_opened_envelope(
        patient_id=7,
        session_key="e" * 32,
        trace_id="e" * 32,
    )

    assert envelope.event_type == EVENT_INTAKE_COMPOSER_OPENED
    assert envelope.producer == PRODUCER_MODULE
    assert set(envelope.payload.model_dump(mode="json")) == {
        "patient_id",
        "session_key",
        "trace_id",
    }
    assert envelope.payload.patient_id == 7
    assert envelope.payload.session_key == "e" * 32
    assert envelope.payload.trace_id == "e" * 32


def test_composer_opened_and_intake_started_are_independently_routable() -> None:
    """An abandon must be distinguishable from a submit.

    The acceptance hinges on the two being SEPARATE events on SEPARATE
    transactions, not one event with two states: composer-opened has no intake
    id because no intake exists yet, and intake.started carries the mode and
    language that only a submission knows. A patient who opens the composer and
    walks away produces the first and never the second, which is exactly what
    makes the drop-off countable.

    Asserted through the registry a consumer routes on, not through constant
    inequality: collapsing the two into one entry, or letting composer-opened
    inherit ``intake.started``'s submission-only fields, breaks separability.
    """
    registry = HandlerRegistry()
    register_handlers(registry)

    composer_opened = intake_composer_opened_envelope(
        patient_id=7, session_key="e" * 32, trace_id="e" * 32
    )
    started = intake_started_envelope(patient_id=7, mode="voice", language="hi")

    assert composer_opened.event_type != started.event_type
    assert registry.payload_model_for(composer_opened.event_type) is IntakeComposerOpenedPayload
    assert registry.payload_model_for(started.event_type) is IntakeStartedPayload

    # composer-opened carries no submission-only field, and vice versa.
    assert "intake_id" not in composer_opened.payload.model_dump(mode="json")
    assert set(started.payload.model_dump(mode="json")) & {
        "patient_id",
        "mode",
        "language",
    } == {"patient_id", "mode", "language"}


def test_no_payload_carries_phi() -> None:
    # security-phii-standards: transcripts, clinical fields, confidence scores
    # and egressed bytes never travel - only ids and operational facts (and, for
    # ``intake.started``, the funnel facts that precede any captured content).
    for envelope in _capture_from_all_event_types():
        dumped = envelope.payload.model_dump(mode="json")
        assert "intake_id" in dumped or "ai_job_id" in dumped or "patient_id" in dumped
    transcript_keys = {
        key
        for envelope in _capture_from_all_event_types()
        for key in envelope.payload.model_dump(mode="json")
    }
    for banned in ("transcript", "structured_fields", "confidence", "media", "text"):
        assert banned not in transcript_keys


def test_every_builder_produces_distinct_event_ids() -> None:
    ids = {envelope.event_id for envelope in _capture_from_all_event_types()}
    assert len(ids) == len(_capture_from_all_event_types())


def test_register_handlers_registers_payload_models_without_duplicates() -> None:
    registry = HandlerRegistry()

    register_handlers(registry)

    for event_type in _ALL_EVENT_TYPES:
        assert registry.payload_model_for(event_type) is not None


def test_register_handlers_registers_the_self_subscriptions() -> None:
    registry = HandlerRegistry()

    register_handlers(registry)

    # The §4.2 self-subscriptions: MOD-005 -> MOD-005 - ``intake.started`` (the
    # telemetry-only funnel log + count, T05 #369), ``intake.captured`` (async
    # AI pipeline) and ``intake.retry_requested`` (re-record flow) - each has a
    # handler seat at the composition root.
    assert registry.handlers_for(EVENT_INTAKE_STARTED)
    assert registry.handlers_for(EVENT_INTAKE_CAPTURED)
    assert registry.handlers_for(EVENT_INTAKE_RETRY_REQUESTED)
    # No other intake event has a handler seat yet (pipeline bodies land in
    # T08/T10/T11). ``intake.doctor_assigned`` deliberately has none here either:
    # its only subscriber is MOD-013's care-attribution edge (B4d #724), which
    # registers its own payload mirror and handler - MOD-005 publishes it and
    # never consumes it back. ``intake.composer_opened`` is the same shape: its
    # only subscriber is MOD-013's product event ledger (B4e #739), so MOD-005
    # publishes the payload model for fan-out and consumes nothing.
    for event_type in (
        EVENT_PRE_SUMMARY_READY,
        EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
        EVENT_AI_JOB_COMPLETED,
        EVENT_AI_JOB_FAILED,
        EVENT_AI_EGRESS_RECORDED,
        EVENT_INTAKE_DOCTOR_ASSIGNED,
        EVENT_INTAKE_COMPOSER_OPENED,
    ):
        assert registry.handlers_for(event_type) == ()


def test_register_handlers_twice_on_one_registry_raises_duplicate() -> None:
    # Composition is one-shot per registry; re-registering the same seam on the
    # SAME registry must trip the duplicate-registration guard (registry.py),
    # proving the seam never double-registers under a single composition.
    registry = HandlerRegistry()

    register_handlers(registry)

    with pytest.raises(ValueError):
        register_handlers(registry)


@pytest.mark.asyncio
async def test_intake_started_telemetry_handler_logs_and_counts_distinct_events(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The telemetry handler counts once per distinct event_id (ledger-deduped).

    Drives the registered ``intake.started`` handler through the same short-lived
    engine + ledger seam as the live dispatcher: a replayed ``event_id`` is a
    no-op (at-least-once delivery skips), so ``intake_started_count`` tracks
    distinct starts even when the outbox redelivers a row.
    """
    registry = HandlerRegistry()
    register_handlers(registry)
    handler = registry.handlers_for(EVENT_INTAKE_STARTED)[0]

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
    caplog.set_level(logging.INFO, logger="modules.intake.adapters")

    before = intake_started_count()
    first = intake_started_envelope(patient_id=7, mode="text", language="en")
    second = intake_started_envelope(patient_id=7, mode="voice", language="hi")

    await handler(first)
    assert intake_started_count() == before + 1

    await handler(first)
    assert intake_started_count() == before + 1

    await handler(second)
    assert intake_started_count() == before + 2

    assert "intake.started telemetry" in caplog.text
    assert "mode=text language=en" in caplog.text
    assert "mode=voice language=hi" in caplog.text


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


def test_emitted_envelope_round_trips_through_the_registry_validator() -> None:
    registry = HandlerRegistry()
    register_handlers(registry)

    for envelope in _capture_from_all_event_types():
        row = _row_for(envelope)
        payload_model = registry.payload_model_for(envelope.event_type)
        assert payload_model is not None

        reconstructed = envelope_from_row(row, "intake", payload_model)

        assert reconstructed.event_type == envelope.event_type
        assert reconstructed.event_id == envelope.event_id
        assert reconstructed.producer == "intake"
        assert isinstance(reconstructed.payload, payload_model)
        assert reconstructed.payload.model_dump(mode="json") == row.payload
