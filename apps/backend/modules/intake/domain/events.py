"""MOD-005: canonical symptom-intake + AI pre-summary event payloads and builders.

Event names follow the registry dot-notation in ``internal-modules.md`` §4.2
(ADR-0008, ticket #349); payloads are typed Pydantic models (coding-standards
§3) and carry only orchestration/audit facts - ids, the task kind, the retry
attempt, the failure reason - never PHI. The intake transcript, structured
clinical fields and any patient content live in the ``intake`` schema and are
read by the consuming facade; only identifiers and lifecycle facts travel on
the bus (security-phii-standards no-PHI). Every builder answers an
:class:`~bus.envelope.Envelope` the intake facade writes into
``intake.intake_outbox`` in the SAME transaction as the state change
(ADR-0002 §1).
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_INTAKE_STARTED,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
)

PRODUCER_MODULE = "intake"

AiTaskType = Literal["transcribe", "structure", "draft", "summarize"]

IntakeMode = Literal["voice", "text"]
IntakeLanguage = Literal["hi", "en"]


class IntakeStartedPayload(BaseModel):
    """Subject of ``intake.started``: a patient began a symptom intake.

    Funnel-telemetry entry (PRD §4.3.1, PHASE-7 T05 #369) ride-along in the
    same outbox transaction as ``intake.captured``; MOD-005 self-subscribes
    to log + count it (KPI-001 pipeline counters). Carries only the funnel
    facts - patient id, the mode (voice|text) and language - no clinical
    content. Deliberately NOT a regulated act: it precedes capture, so no
    intake row exists yet.
    """

    patient_id: int
    mode: IntakeMode
    language: IntakeLanguage


class IntakeCapturedPayload(BaseModel):
    """Subject of ``intake.captured``: a symptom intake was just captured.

    MOD-005 self-subscribes to this event to trigger the async AI pipeline
    (structuring), and MOD-011 records it on the audit trail; only the intake
    id travels - the captured text/transcript stays in the intake schema.
    """

    intake_id: int


class IntakeRetryRequestedPayload(BaseModel):
    """Subject of ``intake.retry_requested``: a voice intake was asked to re-record.

    Fired by the auto-retry flow (NFR-PERF-002) when ASR input is unusable;
    MOD-005 consumes it to drive the re-record flow and MOD-011 logs it.
    ``record_attempt`` names the retry round (≤ 3 per NFR-PERF-003).
    """

    intake_id: int
    record_attempt: int


class PreSummaryReadyPayload(BaseModel):
    """Subject of ``pre_summary.ready``: an AI pre-summary was finalized.

    MOD-006 attaches the summary to the case and MOD-010 sends the in-app
    notification. ``pre_summary_id`` names the finalized row; the structured
    clinical fields themselves stay in the intake schema.
    """

    intake_id: int
    pre_summary_id: int


class PreSummaryLowConfidencePayload(BaseModel):
    """Subject of ``pre_summary.low_confidence``: the pre-summary needs review.

    Fired when structuring confidence falls below the AMB-006 threshold;
    MOD-006 forces doctor review before the handshake, MOD-011 logs it. Only
    ids travel - the summary and confidence score stay in the intake schema.
    """

    intake_id: int
    pre_summary_id: int


class AiJobCompletedPayload(BaseModel):
    """Subject of ``ai_job.completed``: an AI pipeline job finished.

    MOD-005 self-subscribes to chain the pipeline (e.g. structure -> publish a
    pre-summary) and MOD-011 logs the completion. ``task_type`` names the job
    kind; token/cost metering stays in the ``intake_ai_jobs`` row.
    """

    ai_job_id: int
    intake_id: int
    task_type: AiTaskType


class AiJobFailedPayload(BaseModel):
    """Subject of ``ai_job.failed``: an AI pipeline job failed.

    MOD-011 logs the degrade path; ``reason`` carries the operational failure
    only (never PHI) so the audit/telemetry consumer can categorise the
    failure without reading the AI gateway internals.
    """

    ai_job_id: int
    intake_id: int
    task_type: AiTaskType
    reason: str


class AiEgressRecordedPayload(BaseModel):
    """Subject of ``ai_egress.recorded``: a PHI-minimized egress was logged.

    Fired after content leaves for EXT-002 (the LLM); MOD-004 writes the
    consent log and MOD-011 the audit trail. ``ai_job_id`` names the egressing
    job; only ids and the egress reason travel - never the egressed bytes.
    """

    intake_id: int
    ai_job_id: int
    reason: str


def intake_started_envelope(
    *, patient_id: int, mode: IntakeMode, language: IntakeLanguage
) -> Envelope[IntakeStartedPayload]:
    """Build the ``intake.started`` funnel-telemetry envelope for the intake outbox."""
    return Envelope[IntakeStartedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_STARTED,
        producer=PRODUCER_MODULE,
        payload=IntakeStartedPayload(patient_id=patient_id, mode=mode, language=language),
    )


def intake_captured_envelope(*, intake_id: int) -> Envelope[IntakeCapturedPayload]:
    """Build the ``intake.captured`` envelope for the intake outbox."""
    return Envelope[IntakeCapturedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_CAPTURED,
        producer=PRODUCER_MODULE,
        payload=IntakeCapturedPayload(intake_id=intake_id),
    )


def intake_retry_requested_envelope(
    *, intake_id: int, record_attempt: int
) -> Envelope[IntakeRetryRequestedPayload]:
    """Build the ``intake.retry_requested`` envelope for the intake outbox."""
    return Envelope[IntakeRetryRequestedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_RETRY_REQUESTED,
        producer=PRODUCER_MODULE,
        payload=IntakeRetryRequestedPayload(intake_id=intake_id, record_attempt=record_attempt),
    )


def pre_summary_ready_envelope(
    *, intake_id: int, pre_summary_id: int
) -> Envelope[PreSummaryReadyPayload]:
    """Build the ``pre_summary.ready`` envelope for the intake outbox."""
    return Envelope[PreSummaryReadyPayload](
        event_id=uuid4(),
        event_type=EVENT_PRE_SUMMARY_READY,
        producer=PRODUCER_MODULE,
        payload=PreSummaryReadyPayload(intake_id=intake_id, pre_summary_id=pre_summary_id),
    )


def pre_summary_low_confidence_envelope(
    *, intake_id: int, pre_summary_id: int
) -> Envelope[PreSummaryLowConfidencePayload]:
    """Build the ``pre_summary.low_confidence`` envelope for the intake outbox."""
    return Envelope[PreSummaryLowConfidencePayload](
        event_id=uuid4(),
        event_type=EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
        producer=PRODUCER_MODULE,
        payload=PreSummaryLowConfidencePayload(intake_id=intake_id, pre_summary_id=pre_summary_id),
    )


def ai_job_completed_envelope(
    *, ai_job_id: int, intake_id: int, task_type: AiTaskType
) -> Envelope[AiJobCompletedPayload]:
    """Build the ``ai_job.completed`` envelope for the intake outbox."""
    return Envelope[AiJobCompletedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_COMPLETED,
        producer=PRODUCER_MODULE,
        payload=AiJobCompletedPayload(
            ai_job_id=ai_job_id, intake_id=intake_id, task_type=task_type
        ),
    )


def ai_job_failed_envelope(
    *, ai_job_id: int, intake_id: int, task_type: AiTaskType, reason: str
) -> Envelope[AiJobFailedPayload]:
    """Build the ``ai_job.failed`` envelope for the intake outbox."""
    return Envelope[AiJobFailedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_FAILED,
        producer=PRODUCER_MODULE,
        payload=AiJobFailedPayload(
            ai_job_id=ai_job_id, intake_id=intake_id, task_type=task_type, reason=reason
        ),
    )


def ai_egress_recorded_envelope(
    *, intake_id: int, ai_job_id: int, reason: str
) -> Envelope[AiEgressRecordedPayload]:
    """Build the ``ai_egress.recorded`` envelope for the intake outbox."""
    return Envelope[AiEgressRecordedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_EGRESS_RECORDED,
        producer=PRODUCER_MODULE,
        payload=AiEgressRecordedPayload(intake_id=intake_id, ai_job_id=ai_job_id, reason=reason),
    )
