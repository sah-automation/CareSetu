"""MOD-005: canonical symptom-intake + AI pre-summary event payloads and builders.

Event names follow the registry dot-notation in ``internal-modules.md`` §4.2
(ADR-0008, ticket #349); payloads are typed Pydantic models (coding-standards
§3) and carry only orchestration/audit facts - ids, the task kind, the retry
attempt, the failure reason - never PHI. The intake transcript, structured
clinical fields and any patient content live in the ``intake`` schema and are
read by the consuming facade; only identifiers and lifecycle facts travel on
the bus (security-phii-standards no-PHI). The ``ai_job.*`` events also carry
the operational METERING facts MOD-013's telemetry aggregates from the event
alone (provider, model, tokens, cost, duration - and the derived
``low_confidence`` flag, never the raw confidence score), so a consumer never
crosses into the ``intake`` schema (B4 #702). The same holds for the
``intake.doctor_assigned`` care-attribution event (B4d #720): it carries the
intake/patient/doctor references so attribution never needs a cross-schema join
(ADR-0003). And ``intake.composer_opened`` (B4e #721) is the funnel's real
entry step - it fires before any capture, carries the session key the product
ledger groups steps by, and writes no clinical content at all. Every builder
answers an
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
    EVENT_AI_JOB_QUEUED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_DOCTOR_ASSIGNED,
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
    (structuring), and MOD-011 records it on the audit trail. Carries the
    intake id plus the funnel facts (patient id, mode, duration) so
    telemetry consumers have the fields they need without a schema lookup.
    The captured text/transcript stays in the intake schema.
    """

    intake_id: int
    patient_id: int
    mode: IntakeMode
    duration_s: float | None


class IntakeRetryRequestedPayload(BaseModel):
    """Subject of ``intake.retry_requested``: a voice intake was asked to re-record.

    Fired by the auto-retry flow (NFR-PERF-002) when ASR input is unusable;
    MOD-005 consumes it to drive the re-record flow and MOD-011 logs it.
    ``record_attempt`` names the retry round (<= 3 per NFR-PERF-003);
    ``reason`` is a short, PHI-free descriptor (e.g. "unusable_audio").
    """

    intake_id: int
    record_attempt: int
    reason: str


class PreSummaryReadyPayload(BaseModel):
    """Subject of ``pre_summary.ready``: an AI pre-summary was finalized.

    MOD-006 attaches the summary to the case and MOD-010 sends the in-app
    notification. ``pre_summary_id`` names the finalized row; the structured
    clinical fields themselves stay in the intake schema. ``patient_id``
    carries the owning patient identity so MOD-006 can birth the care case
    without an extra cross-schema lookup (PHASE-8 T2, #428).
    """

    intake_id: int
    pre_summary_id: int
    patient_id: int


class PreSummaryLowConfidencePayload(BaseModel):
    """Subject of ``pre_summary.low_confidence``: the pre-summary needs review.

    Fired when structuring confidence falls below the AMB-006 threshold;
    MOD-006 forces doctor review before the handshake, MOD-011 logs it. Only
    ids travel - the summary and confidence score stay in the intake schema.
    """

    intake_id: int
    pre_summary_id: int


class AiJobQueuedPayload(BaseModel):
    """Subject of ``ai_job.queued``: an AI job just ENTERED the pipeline (B5 #729).

    Fired in the SAME transaction as the ``intake_ai_jobs`` row, at the moment
    that row is created and before the provider call - which is what makes it the
    enqueue side of the queue: ``ai_job.completed`` / ``ai_job.failed`` say what
    became of the work, and with no enqueue event a queue has nothing to subtract
    those two from.

    MOD-013 consumes it to derive queue depth and the age of the oldest still-open
    job, WITHOUT reading this module's tables (ADR-0003). That is the whole reason
    this event exists, so the payload carries only what a consumer cannot work out
    for itself: the job reference (the row's identity), the queue the work sits in
    (``task_type`` - one queue per pipeline leg, the producer's own closed
    vocabulary), the patient the work is about, and the trace id.

    **No ``doctor_id`` here, unlike the completed and failed payloads.** At the
    moment work is enqueued no leg knows the doctor: the drafting doctor lives in
    the care schema, which this module cannot read (ADR-0003), and per-doctor
    attribution rides the ``intake.doctor_assigned`` edge instead (#720). So the
    field would be null at every producer and read by nobody - a doctor's identity
    reference carried for no reason is exactly what no-PHI rules ask us not to do.

    The ENQUEUE INSTANT IS NOT a payload field: it is the envelope's
    ``occurred_at``, which the outbox writer stamps on the same row, so the age
    figure is read from the same clock the delivery carries rather than from a
    second, separately-supplied one. Identity references only, never clinical
    content (security-phii-standards no-PHI).
    """

    ai_job_id: int
    intake_id: int
    task_type: AiTaskType
    patient_id: int
    trace_id: str | None


class AiJobCompletedPayload(BaseModel):
    """Subject of ``ai_job.completed``: an AI pipeline job finished.

    MOD-005 self-subscribes to chain the pipeline (e.g. structure -> publish a
    pre-summary) and MOD-011 logs the completion. Since B4 (#702) the payload
    ALSO carries the operational metering facts MOD-013 accumulates from the
    event alone - the serving provider/model, the provider-reported token use
    priced into ``cost_paise``, the call duration, and the derived
    ``low_confidence`` flag. The flag is computed upstream (always ``False`` for
    transcribe) and never the raw confidence score, which stays in the intake
    schema (security-phii-standards no-PHI). ``task_type`` names the job kind.

    B4c (#719) widens the payload with the identity references the per-patient
    and per-doctor cost attribution needs: ``patient_id``, a nullable
    ``doctor_id`` (null on the transcription and structuring legs, which involve
    no doctor) and the ``trace_id`` that joins the event to the platform's
    tracing backend (the shared join key, #717 decision 41). All are resolved
    producer-locally - no module reads another module's tables - and only
    identity references travel, never clinical content (security-phii-standards
    no-PHI).
    """

    ai_job_id: int
    intake_id: int
    task_type: AiTaskType
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_paise: int
    duration_ms: int
    low_confidence: bool
    patient_id: int
    doctor_id: int | None
    trace_id: str | None


class AiJobFailedPayload(BaseModel):
    """Subject of ``ai_job.failed``: an AI pipeline job failed.

    MOD-011 logs the degrade path; ``reason`` carries the operational failure
    only (never PHI) so the audit/telemetry consumer can categorise the
    failure without reading the AI gateway internals. The serving provider/model
    ride along for the MOD-013 usage aggregate (B4 #702), and ``timeout`` -
    derived by the pipeline from the raised exception's cause chain - lets the
    aggregate bucket timeouts separately from other failures.

    B4c (#719) carries the same identity references the completed payload does -
    ``patient_id``, a nullable ``doctor_id`` (null on the transcription and
    structuring legs) and the ``trace_id`` join key - resolved producer-locally,
    identity only, no clinical content (security-phii-standards no-PHI).
    """

    ai_job_id: int
    intake_id: int
    task_type: AiTaskType
    reason: str
    provider: str
    model: str
    timeout: bool
    patient_id: int
    doctor_id: int | None
    trace_id: str | None


class AiEgressRecordedPayload(BaseModel):
    """Subject of ``ai_egress.recorded``: a PHI-minimized egress was logged.

    Fired after content leaves for EXT-002 (the LLM); MOD-004 writes the
    consent log and MOD-011 the audit trail. ``ai_job_id`` names the egressing
    job; only ids and the egress reason travel - never the egressed bytes.
    """

    intake_id: int
    ai_job_id: int
    reason: str


class IntakeDoctorAssignedPayload(BaseModel):
    """Subject of ``intake.doctor_assigned``: a patient picked their doctor.

    The care-attribution edge (B4d, #720; #717 decision 3). Doctor attribution
    rides THIS EVENT rather than a join: without it the only way for another
    module to learn which doctor an intake belongs to would be to read the
    partner/care tables across the schema boundary, which ADR-0003 forbids. So
    the three references travel at the moment of the pick and nothing else is
    needed downstream - only identity references, never clinical content
    (security-phii-standards no-PHI).

    ``doctor_id`` is honestly named: it is the ``MOD-002`` partner-directory
    record id of the doctor - the same value written to
    ``intake_intakes.assigned_partner_id`` and the same reference this pick
    addresses as its ``doctor`` consent counterparty. The pick path declares that
    counterparty type; it does not itself verify the partner's directory type, so
    downstream code must not read more into the reference than "the record the
    patient picked, as this intake's doctor". A consumer that keys spend per
    doctor hashes this reference into a pseudonymous key in its own schema rather
    than storing the raw reference.

    MOD-013 is the declared subscriber (#724): it records the edge keyed on this
    event's ``event_id``, so a redelivery changes nothing downstream.
    """

    intake_id: int
    patient_id: int
    doctor_id: int


class IntakeComposerOpenedPayload(BaseModel):
    """Subject of ``intake.composer_opened``: a patient opened the composer.

    The intake funnel's real ENTRY step (B4e, #721; #717 decision 4).
    ``intake.started`` rides the capture transaction, so before this event a
    patient who opened the recorder and walked away produced no trace at all and
    the funnel had no head to drop off from. This event fires the moment the
    composer opens, in its own transaction, BEFORE any capture - so it is
    reached by a submit AND by an abandon alike, and the absence of the later
    step is what distinguishes them. Two separate events on two separate
    transactions is the whole mechanism: one event with two states could not
    tell an abandon from a submit.

    **No ``intake_id`` here, deliberately.** No intake row exists when a patient
    opens the composer; asserting one would be asserting a fiction. Nor any
    clinical content - no audio reference, no transcript, no typed symptoms, no
    free text (security-phii-standards no-PHI). This records that a person
    arrived, and nothing about what they said.

    ``patient_id`` is the authenticated patient the entry belongs to. A consumer
    that keys activity per actor hashes it into a pseudonymous key in its own
    schema rather than storing the raw reference (#717 decision 7).

    **Session key: the platform's trace-context session scope.** The frontend
    holds no stable session identity - every persisted session field
    (``identity_id``, ``jti``, ``scope``, ``phone``) is user-scoped, and the one
    per-mutation id it mints is deliberately non-durable - so there is no client
    session to key on, and minting one here would be building state no consumer
    asked for. The key is therefore the platform's own session scope, which today
    is the request: the trace context ``TraceMiddleware`` establishes and
    ``resolve_trace_id`` reads. ``session_key`` and ``trace_id`` so coincide, and
    stay separate fields because they answer separate questions on MOD-013's
    ledger - which steps belong to one session versus which request to jump to in
    the tracing backend. When a stable session identity arrives, only THIS
    derivation changes; the field names, payload shape and registry entry stay
    put. Until then a step-to-step gap must be measured from the ledger's own
    timestamps, not assumed from this key (#739).

    Both are bare ``str``, not a validated type, because ``TraceMiddleware``
    already bounded them: a client ``X-Request-Id`` is honoured only when it is
    printable, non-space and at most ``MAX_TRACE_ID_LENGTH`` (64) characters per
    the shared rule in :mod:`observability.trace_ids`, else a uuid4 hex is
    minted. So neither field can carry unbounded client text into the ledger. The
    trade is that a client CAN choose its own key; since this payload has no field
    another patient's key could collide with beyond ``patient_id`` itself, the
    worst that buys is scattered rows in the caller's OWN funnel - never read or
    corrupt access to another's (#739 keys the ledger on a pseudonymous actor
    hash, which is a consumer-side column, not a field of this event).

    MOD-013 is the declared subscriber (#739): it records this as the funnel's
    first step keyed on this event's ``event_id``, so a redelivery changes
    nothing downstream.
    """

    patient_id: int
    session_key: str
    trace_id: str


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


def intake_captured_envelope(
    *,
    intake_id: int,
    patient_id: int,
    mode: IntakeMode,
    duration_s: float | None,
) -> Envelope[IntakeCapturedPayload]:
    """Build the ``intake.captured`` envelope for the intake outbox."""
    return Envelope[IntakeCapturedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_CAPTURED,
        producer=PRODUCER_MODULE,
        payload=IntakeCapturedPayload(
            intake_id=intake_id,
            patient_id=patient_id,
            mode=mode,
            duration_s=duration_s,
        ),
    )


def intake_retry_requested_envelope(
    *, intake_id: int, record_attempt: int, reason: str
) -> Envelope[IntakeRetryRequestedPayload]:
    """Build the ``intake.retry_requested`` envelope for the intake outbox."""
    return Envelope[IntakeRetryRequestedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_RETRY_REQUESTED,
        producer=PRODUCER_MODULE,
        payload=IntakeRetryRequestedPayload(
            intake_id=intake_id, record_attempt=record_attempt, reason=reason
        ),
    )


def pre_summary_ready_envelope(
    *, intake_id: int, pre_summary_id: int, patient_id: int
) -> Envelope[PreSummaryReadyPayload]:
    """Build the ``pre_summary.ready`` envelope for the intake outbox."""
    return Envelope[PreSummaryReadyPayload](
        event_id=uuid4(),
        event_type=EVENT_PRE_SUMMARY_READY,
        producer=PRODUCER_MODULE,
        payload=PreSummaryReadyPayload(
            intake_id=intake_id, pre_summary_id=pre_summary_id, patient_id=patient_id
        ),
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


def ai_job_queued_envelope(
    *,
    ai_job_id: int,
    intake_id: int,
    task_type: AiTaskType,
    patient_id: int,
    trace_id: str | None,
) -> Envelope[AiJobQueuedPayload]:
    """Build the ``ai_job.queued`` envelope for the intake outbox (B5 #729)."""
    return Envelope[AiJobQueuedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_QUEUED,
        producer=PRODUCER_MODULE,
        payload=AiJobQueuedPayload(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type=task_type,
            patient_id=patient_id,
            trace_id=trace_id,
        ),
    )


def ai_job_completed_envelope(
    *,
    ai_job_id: int,
    intake_id: int,
    task_type: AiTaskType,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_paise: int,
    duration_ms: int,
    low_confidence: bool,
    patient_id: int,
    doctor_id: int | None,
    trace_id: str | None,
) -> Envelope[AiJobCompletedPayload]:
    """Build the ``ai_job.completed`` envelope for the intake outbox."""
    return Envelope[AiJobCompletedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_COMPLETED,
        producer=PRODUCER_MODULE,
        payload=AiJobCompletedPayload(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type=task_type,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_paise=cost_paise,
            duration_ms=duration_ms,
            low_confidence=low_confidence,
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=trace_id,
        ),
    )


def ai_job_failed_envelope(
    *,
    ai_job_id: int,
    intake_id: int,
    task_type: AiTaskType,
    reason: str,
    provider: str,
    model: str,
    timeout: bool,
    patient_id: int,
    doctor_id: int | None,
    trace_id: str | None,
) -> Envelope[AiJobFailedPayload]:
    """Build the ``ai_job.failed`` envelope for the intake outbox."""
    return Envelope[AiJobFailedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_FAILED,
        producer=PRODUCER_MODULE,
        payload=AiJobFailedPayload(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type=task_type,
            reason=reason,
            provider=provider,
            model=model,
            timeout=timeout,
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=trace_id,
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


def intake_doctor_assigned_envelope(
    *, intake_id: int, patient_id: int, doctor_id: int
) -> Envelope[IntakeDoctorAssignedPayload]:
    """Build the ``intake.doctor_assigned`` care-attribution envelope."""
    return Envelope[IntakeDoctorAssignedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_DOCTOR_ASSIGNED,
        producer=PRODUCER_MODULE,
        payload=IntakeDoctorAssignedPayload(
            intake_id=intake_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
        ),
    )


def intake_composer_opened_envelope(
    *, patient_id: int, session_key: str, trace_id: str
) -> Envelope[IntakeComposerOpenedPayload]:
    """Build the ``intake.composer_opened`` funnel-entry envelope.

    ``session_key`` is the platform's trace-context session scope and
    ``trace_id`` is the request-scoped trace id; on this event they coincide,
    for the reason set out on :class:`IntakeComposerOpenedPayload`. Both are
    taken as arguments rather than read from the ambient context here so the
    facade resolves the session scope ONCE, in the one place that owns that
    decision.
    """
    return Envelope[IntakeComposerOpenedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_COMPOSER_OPENED,
        producer=PRODUCER_MODULE,
        payload=IntakeComposerOpenedPayload(
            patient_id=patient_id,
            session_key=session_key,
            trace_id=trace_id,
        ),
    )
