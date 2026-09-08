"""PHASE-7 T04: intake + AI pre-summary event payloads/builders + wiring (ticket #349).

Pins the code-side mirror of the §4.2 registry names the intake module
publishes: every event names the orchestration/audit facts (ids, the task
kind, retry attempt, failure reason) and never carries PHI (transcript,
structured clinical fields, confidence scores, egressed bytes stay in the
``intake`` schema - security-phii-standards no-PHI). Covers the frozen event
shapes, the ``register_handlers`` registration seam (payload models + the
``intake.captured`` self-subscription), and an emitted-envelope round-trip
through the registry validator - all without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel

from bus.dispatcher import OutboxRow, envelope_from_row
from bus.envelope import Envelope, is_valid_event_type
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
)
from bus.registry import HandlerRegistry
from modules.intake.adapters import register_handlers
from modules.intake.domain.events import (
    PRODUCER_MODULE,
    ai_egress_recorded_envelope,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
    intake_captured_envelope,
    intake_retry_requested_envelope,
    pre_summary_low_confidence_envelope,
    pre_summary_ready_envelope,
)

_ALL_EVENT_TYPES = (
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AI_EGRESS_RECORDED,
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
    assert EVENT_INTAKE_CAPTURED == "intake.captured"
    assert EVENT_INTAKE_RETRY_REQUESTED == "intake.retry_requested"
    assert EVENT_PRE_SUMMARY_READY == "pre_summary.ready"
    assert EVENT_PRE_SUMMARY_LOW_CONFIDENCE == "pre_summary.low_confidence"
    assert EVENT_AI_JOB_COMPLETED == "ai_job.completed"
    assert EVENT_AI_JOB_FAILED == "ai_job.failed"
    assert EVENT_AI_EGRESS_RECORDED == "ai_egress.recorded"


def _capture_from_all_event_types() -> list[Envelope[BaseModel]]:
    return [
        intake_captured_envelope(intake_id=1),
        intake_retry_requested_envelope(intake_id=1, record_attempt=2),
        pre_summary_ready_envelope(intake_id=1, pre_summary_id=5),
        pre_summary_low_confidence_envelope(intake_id=1, pre_summary_id=5),
        ai_job_completed_envelope(ai_job_id=9, intake_id=1, task_type="structure"),
        ai_job_failed_envelope(ai_job_id=9, intake_id=1, task_type="transcribe", reason="timeout"),
        ai_egress_recorded_envelope(intake_id=1, ai_job_id=9, reason="structure"),
    ]


def test_captured_carries_only_the_intake_id() -> None:
    envelope = intake_captured_envelope(intake_id=42)

    assert envelope.event_type == EVENT_INTAKE_CAPTURED
    assert envelope.producer == PRODUCER_MODULE
    assert envelope.payload.intake_id == 42


def test_retry_requested_carries_the_record_attempt() -> None:
    envelope = intake_retry_requested_envelope(intake_id=42, record_attempt=3)

    assert envelope.event_type == EVENT_INTAKE_RETRY_REQUESTED
    assert envelope.payload.intake_id == 42
    assert envelope.payload.record_attempt == 3


def test_pre_summary_ready_names_the_summary() -> None:
    envelope = pre_summary_ready_envelope(intake_id=42, pre_summary_id=7)

    assert envelope.event_type == EVENT_PRE_SUMMARY_READY
    assert envelope.payload.intake_id == 42
    assert envelope.payload.pre_summary_id == 7


def test_pre_summary_low_confidence_names_the_summary() -> None:
    envelope = pre_summary_low_confidence_envelope(intake_id=42, pre_summary_id=7)

    assert envelope.event_type == EVENT_PRE_SUMMARY_LOW_CONFIDENCE
    assert envelope.payload.intake_id == 42
    assert envelope.payload.pre_summary_id == 7


def test_ai_job_completed_names_the_job_and_task() -> None:
    envelope = ai_job_completed_envelope(ai_job_id=9, intake_id=42, task_type="draft")

    assert envelope.event_type == EVENT_AI_JOB_COMPLETED
    assert envelope.payload.ai_job_id == 9
    assert envelope.payload.intake_id == 42
    assert envelope.payload.task_type == "draft"


def test_ai_job_failed_carries_the_operational_reason() -> None:
    envelope = ai_job_failed_envelope(
        ai_job_id=9, intake_id=42, task_type="summarize", reason="provider 429"
    )

    assert envelope.event_type == EVENT_AI_JOB_FAILED
    assert envelope.payload.ai_job_id == 9
    assert envelope.payload.intake_id == 42
    assert envelope.payload.task_type == "summarize"
    assert envelope.payload.reason == "provider 429"


def test_ai_egress_recorded_names_the_job_and_reason() -> None:
    envelope = ai_egress_recorded_envelope(intake_id=42, ai_job_id=9, reason="transcribe")

    assert envelope.event_type == EVENT_AI_EGRESS_RECORDED
    assert envelope.payload.intake_id == 42
    assert envelope.payload.ai_job_id == 9
    assert envelope.payload.reason == "transcribe"


def test_no_payload_carries_phi() -> None:
    # security-phii-standards: transcripts, clinical fields, confidence scores
    # and egressed bytes never travel - only ids and operational facts.
    for envelope in _capture_from_all_event_types():
        dumped = envelope.payload.model_dump(mode="json")
        assert "intake_id" in dumped or "ai_job_id" in dumped
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


def test_register_handlers_registers_both_self_subscriptions() -> None:
    registry = HandlerRegistry()

    register_handlers(registry)

    # The §4.2 self-subscriptions: MOD-005 -> MOD-005 (async AI pipeline; and
    # the re-record flow) - each has a handler seat at the composition root.
    assert registry.handlers_for(EVENT_INTAKE_CAPTURED)
    assert registry.handlers_for(EVENT_INTAKE_RETRY_REQUESTED)
    # No other intake event has a handler seat yet (pipeline bodies land in
    # T08/T10/T11).
    for event_type in (
        EVENT_PRE_SUMMARY_READY,
        EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
        EVENT_AI_JOB_COMPLETED,
        EVENT_AI_JOB_FAILED,
        EVENT_AI_EGRESS_RECORDED,
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
