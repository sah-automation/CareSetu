"""MOD-013: consumer-side payload mirrors for telemetry accumulation (B4 #702).

The ``observability`` module consumes the ``ai_job.completed`` /
``ai_job.failed`` events MOD-005 publishes. The consumer OWNS these mirror
models (cf. MOD-011's mirrors in ``modules/audit/domain/consumer.py``):
MOD-005 registers the canonical payload models on the registry, so MOD-013
never registers a duplicate - ``run_handler`` re-validates the dispatched
intake payload into the local mirror before the aggregate effect runs. The
mirrors carry only operational METERING facts - no PHI (the transcript,
clinical fields and raw confidence score never travel, security-phii-
standards): provider/model, token use, priced cost, duration and the derived
``low_confidence`` flag on completion; the failure reason, serving
provider/model and the derived ``timeout`` classification on failure.

B9 (#728) keeps the failure REASON rather than only its ``timeout``/``failure``
split, so the provider board can name a degraded provider's failure instead of
inferring it. The producer emits a closed token, which is what keeps PHI out;
:func:`sanitize_failure_reason` runs at consume time, BEFORE the write, and
bounds what is stored to one line.

B7 (#724) adds the ``intake.doctor_assigned`` mirror: the care-attribution
edge's three references - intake, patient, doctor - and nothing else. It is the
mirror that makes "which doctor does this intake belong to" answerable inside
this schema without any module reading another's tables (ADR-0003).

T3.5 (#752) adds the two review-outcome mirrors and the
:data:`ANNOTATION_EVENT_MIRRORS` registry that feeds the annotation queue: the
queue is fed by doctor review EVENTS (never by reading MOD-006's tables), and
the mirrors are where "outcome class only, never the free-text rationale" is
enforced - the rejected mirror does not declare the producer's ``reason``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from bus.events import (
    EVENT_AUDIT_EVENT,
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REQUESTED,
    EVENT_CONSENT_REVOKED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_RECORD_ACCESSED,
)
from modules.observability.domain.product import ProductStepPayload

#: The two outcomes ``observability_ai_job_spend.status`` can hold - a closed
#: vocabulary the migration's CHECK constraint enforces, so a third state is a
#: migration rather than a silent value. Declared here rather than in the facade
#: because the attribution rollup's pure core reads the same column and a schema's
#: vocabulary must have exactly one definition.
AI_JOB_SPEND_STATUS_COMPLETED = "completed"
AI_JOB_SPEND_STATUS_FAILED = "failed"
#: The same closed vocabulary as a TYPE, so a caller cannot pass a third state the
#: CHECK constraint would reject. Spelled as literals rather than built from the
#: constants above, matching how ``domain.pseudonym`` types ``ActorKind``.
AiJobSpendStatus = Literal["completed", "failed"]

#: The longest failure reason written to ``observability_ai_job_spend.failure_reason``
#: (#728). Generous enough for any operational token or class name a producer might
#: reasonably emit, and short enough that a column an operator reads in a table
#: cannot become a wall of text. A longer reason is cut, not rejected: refusing to
#: record why a provider failed would defeat the column's only purpose.
MAX_FAILURE_REASON_CHARS = 200

#: Appended to a reason cut at :data:`MAX_FAILURE_REASON_CHARS`, so a reader can
#: see that what they are looking at is not the whole reason rather than assuming
#: the provider stopped talking mid-sentence.
_FAILURE_REASON_ELLIPSIS = "..."

#: Control characters, which a reason has no business carrying and which would
#: corrupt a log line, a CSV export and a terminal alike. Matched rather than
#: enumerated because the set is every Unicode ``Cc`` codepoint plus the two
#: separators a reason must never contain: no reason needs a newline (it would
#: forge a second line in any log it was ever copied into) or a NUL.
_CONTROL_OR_SEPARATOR = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")

#: What splits a raw reason into the line worth keeping and the body a provider
#: echoed. Separators from :data:`_CONTROL_OR_SEPARATOR` that END a line, so that
#: "first line" means the same thing here as it does in a log viewer.
_LINE_BREAK = re.compile(r"[\r\n\u2028\u2029]")


def sanitize_failure_reason(reason: str | None) -> str | None:
    """The failure reason as it may be STORED, or ``None`` when there is nothing to store.

    Runs at consume time, BEFORE the write, so the value that reaches the schema
    is one bounded line whatever a producer put in the event.

    The PHI guarantee is the PRODUCER's, not this function's: the producer's
    ``failure_reason()`` emits a closed vocabulary - a class name or a
    ``rate_limited`` token - and never a provider's body, so there is no patient
    content in the value to leak. This function is what makes that promise hold
    at the storage seam even if a producer is later changed or a new one is added
    (security-phii-standards). Four rules, in order:

    * everything after the first line break is DROPPED, because that is where a
      provider's echoed request lives. A multi-line body keeps only its status
      line, which is the part that names the failure;
    * the surviving line's control characters are replaced, so no reason can forge
      a second line in a log, a CSV export or a terminal;
    * every run of whitespace collapses to one space, so the stored value is a
      single line whose length is meaningful;
    * the result is capped at :data:`MAX_FAILURE_REASON_CHARS` with an ellipsis, so
      a runaway single-line body is cut rather than stored whole.

    Whitespace-only and empty reasons become ``None`` - "no reason to give" is an
    honest NULL, while a column holding ``"   "`` would read as a named failure
    that says nothing.
    """
    if reason is None:
        return None
    first_line = _LINE_BREAK.split(reason, maxsplit=1)[0]
    stripped = _CONTROL_OR_SEPARATOR.sub(" ", first_line)
    collapsed = " ".join(stripped.split())
    if not collapsed:
        return None
    if len(collapsed) <= MAX_FAILURE_REASON_CHARS:
        return collapsed
    return collapsed[: MAX_FAILURE_REASON_CHARS - len(_FAILURE_REASON_ELLIPSIS)] + (
        _FAILURE_REASON_ELLIPSIS
    )


class AiJobQueuedTelemetryPayload(BaseModel):
    """Observability's mirror of MOD-005's ``ai_job.queued`` payload (B5 #729).

    The enqueue side of the queue: this is the only event that says work ENTERED
    the pipeline, so it is the only thing ``enqueued`` can be counted from.
    ``task_type`` is the QUEUE the job sits in - one queue per pipeline leg - and
    the mirror widens it to ``str`` rather than the producer's ``Literal`` because
    MOD-013 cannot import the producing module to reuse its alias (ADR-0003); the
    leg name is a closed vocabulary on the producer side either way, and a leg
    MOD-013 does not recognise still measures correctly as its own queue.

    The enqueue INSTANT is deliberately absent: it is the envelope's
    ``occurred_at``, read off the delivery, so the age figure is computed from the
    same clock the event was stamped with rather than from a second value the
    producer supplied and could disagree with.

    ``patient_id`` is the actor this enqueue belongs to, and the recent-activity
    read counts DISTINCT pseudonymous hashes of it. There is no ``doctor_id`` to
    mirror: the producer has none to give at enqueue time (ADR-0003 puts the
    drafting doctor in the care schema), so a mirrored field would only ever be
    null.
    """

    ai_job_id: int
    intake_id: int
    task_type: str
    patient_id: int
    trace_id: str | None


class AiJobCompletedUsagePayload(BaseModel):
    """Observability's mirror of the ``ai_job.completed`` payload.

    ``low_confidence`` is the producer's derived flag (always ``False`` for
    transcribe) - never the raw confidence score, which stays in the intake
    schema. MOD-013 accumulates it directly and never recomputes it. Since B4c
    (#719) the payload also carries the identity references attribution reads:
    ``patient_id``, a nullable ``doctor_id`` (null on the transcription and
    structuring legs) and the ``trace_id`` join key - identity only, no PHI.
    """

    ai_job_id: int
    intake_id: int
    task_type: str
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


class AiJobFailedUsagePayload(BaseModel):
    """Observability's mirror of the ``ai_job.failed`` payload.

    ``timeout`` is classified upstream (the producer walks its exception's
    cause chain for ``httpx.TimeoutException``); MOD-013 buckets timeouts
    separately from other failures using only this flag. B4c (#719) carries the
    same identity references as the completed mirror - ``patient_id``, a
    nullable ``doctor_id`` and the ``trace_id`` join key.
    """

    ai_job_id: int
    intake_id: int
    task_type: str
    provider: str
    model: str
    reason: str
    timeout: bool
    patient_id: int
    doctor_id: int | None
    trace_id: str | None


class IntakeDoctorAssignedTelemetryPayload(BaseModel):
    """Observability's mirror of MOD-005's ``intake.doctor_assigned`` payload.

        B7 (#724): the care-attribution edge. Three references and nothing else - the
        intake, the patient and the doctor the patient picked - because that is the
        whole of what attribution needs, and every fact on the row is an identity
        reference rather than clinical content (security-phii-standards no-PHI).
        MOD-005 owns the registry payload model, so MOD-013 registers no duplicate;
        ``run_handler`` re-validates the dispatched intake payload into this local
        mirror before the edge is written.

        This event is the ONLY reason the edge exists. Doctor attribution rides an
        event rather than a join because the alternative - MOD-013 reading
        ``intake_intakes.assigned_partner_id`` or the partner tables - is a
        cross-schema read, which the module isolation rule forbids (ADR-0003, #717
        decision 3). If the producer stopped emitting this, attribution would go
        blind rather than silently start guessing, which is the failure mode the
        event was chosen over a join to avoid.

    **Conflict rule - an intake has exactly one doctor, and the schema says so.**
        ``observability_care_attribution_edges.intake_ref`` is UNIQUE, so two edges
        for one intake cannot coexist; the effect upserts on that key. A second,
        genuinely new event about an already-picked intake - a re-pick - therefore
        OVERWRITES the edge rather than stacking a second one, making the newest pick
        the intake's attribution. The overwrite is monotonic in ``assigned_at``: an
        event older than the edge it would replace is dropped rather than allowed to
        roll the pairing backwards, so "newest pick wins" is a property of the code
        rather than an assumption about delivery order. A redelivery of the SAME event
        is a different thing entirely and never reaches the upsert at all -
        ``run_handler`` writes the ``consumed_events`` ledger row first and returns
        before the effect runs, so a replay can neither fail the constraint nor
        overwrite the provenance columns. "Exactly one doctor" is therefore enforced
        by the schema rather than by trusting the producer to never re-pick.
    """

    intake_id: int
    patient_id: int
    doctor_id: int


class CaseConsultCompleteTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-006's ``case.consult_complete`` payload.

    B4b (#703) counts it as a business event; B4e (#739) also records it as the
    funnel's ``consult_complete`` step, attributed to the doctor. That makes it ONE
    event with two effects, and the two effects MUST share ONE handler seat: the
    product ledger is keyed by ``event_id`` alone and ``run_handler`` writes the
    ``consumed_events`` row first, so a second seat would be told it is a replay and
    would skip its own effect forever - with no error, because a replay is supposed to
    be silent.
    Its field contract mirrors what MOD-006 publishes; MOD-006 owns the registry
    model, so MOD-013 registers no duplicate - ``run_handler`` re-validates the
    dispatched care payload into this local mirror before either effect runs.
    """

    case_id: int
    patient_id: int
    doctor_id: int
    pre_summary_id: int | None = None


class CaseClosedTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-006's ``case.closed`` payload.

    Counted as a business event by B4b (#703) and recorded as the funnel's
    ``case_closed`` step by B4e (#739).
    """

    case_id: int
    patient_id: int
    doctor_id: int
    close_reason: str


class ConsentLifecycleTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-004's ``consent.*`` lifecycle payloads.

    One shape covers ``consent.requested`` (no ``version`` yet) and
    ``consent.granted`` / ``consent.revoked`` (``version`` set). MOD-004 owns
    the registry models; MOD-013 re-validates into this mirror to count the
    business event.
    """

    consent_id: int
    lineage_ref: str
    patient_id: int
    counterparty_type: str
    counterparty_id: str
    record_scope: str
    version: int | None = None


class PartnerRegisteredTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-002's ``partner.registered`` payload (B4b #703)."""

    partner_id: int
    identity_id: int
    partner_type: str


class PartnerVerificationStartedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-002's ``partner.verification_started`` payload.

    No module claimed this registry model before MOD-013 (the partner module
    publishes it but has no consumer), so B4b (#703) registers this mirror:
    the dispatcher reconstructs a claimed ``partner.verification_started``
    outbox row with it before fan-out.
    """

    partner_id: int
    round: int


class PartnerDecisionTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-002's ``partner.activated`` / ``partner.rejected``.

    MOD-001 owns the registry models; MOD-013 registers no duplicate and
    re-validates the dispatched decision payload into this mirror to count it.
    """

    partner_id: int
    identity_id: int
    reason: str | None = None
    round: int | None = None
    decision_by: int | None = None


class PartnerCredentialReviewedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-002's ``partner.credential_reviewed`` payload."""

    partner_id: int
    actor_id: int


class PartnerSelectedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-002's ``partner.selected`` payload.

    Unclaimed before MOD-013 (the partner module publishes it with no
    consumer), so B4b (#703) registers this mirror so the dispatcher can
    reconstruct the row before fan-out. Anonymous product analytics - ids and
    facts only, no actor.
    """

    partner_id: int
    partner_type: str | None = None
    source: str | None = None


class RecordAccessTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-003's ``record.accessed`` payload (B4b #703).

    MOD-011 owns the registry model; MOD-013 re-validates into this mirror to
    count the read. ``metadata`` is carried only so validation matches the
    producer contract - it is never copied into a business count or an alert.
    """

    record_id: int
    actor_id: int
    actor_type: str
    scope: str
    accessed_at: datetime
    metadata: dict[str, Any] | None = None


class AuditEventTelemetryPayload(BaseModel):
    """MOD-013's mirror of the generic ``audit.event`` carrier payload (B4b #703).

    MOD-011 owns the registry model; MOD-013 re-validates into this mirror to
    count the audit carrier. Every producer publishes it, so the count is a
    coarse "audit events recorded" signal.
    """

    action: str
    actor_patient_id: int
    consent_id: int
    lineage_ref: str
    record_scope: str
    version: int


class TamperDetectedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-011's ``audit.tamper_detected`` payload.

    Deliberately carries only the tamper facts safe for an alert -
    ``attempted_operation``, ``target_event_id`` and ``attempted_at``. The
    producer's ``details`` blob (which embeds the attempted row's ``old_data``
    / ``new_data``) is dropped here so it can never reach an alert payload
    (security-phii-standards; plan-phase14 §10 - no PHI in alerts).
    """

    attempted_operation: str
    target_event_id: str | None = None
    attempted_at: datetime


class AiEgressRecordedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-005's ``ai_egress.recorded`` guardrail signal.

    The AI-egress minimization guardrail (``AiEgressContext``) is surfaced, not
    rebuilt (plan-phase14 §10): each PHI-minimized egress is observable in the
    alert feed. MOD-005 owns the registry model; MOD-013 re-validates into this
    mirror. Only ids and the egress reason travel - never the egressed bytes.
    """

    intake_id: int
    ai_job_id: int
    reason: str


class PromptInjectionDetectedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-005's ``ai_egress.prompt_injection_detected``.

    The producer's advisory finding already excludes the transcript and any
    matched text. This mirror re-declares the narrow shape so the handler cannot
    read more if the producer's payload grows later.
    """

    categories: list[str]
    score: int


class IntakeComposerOpenedTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-005's ``intake.composer_opened`` payload (B4e #739).

    The funnel's real ENTRY step, and the only one whose producer publishes a
    ``trace_id``: this event fires when the composer opens, in its own transaction,
    BEFORE any capture exists - so it is the only step that can tell an abandoned
    draft apart from a submit (#717 decision 4, #721).

    ``patient_id`` is re-declared REQUIRED because the producer guarantees it: the
    entry step is the head of an active-actor count, and a composer open with no
    patient behind it is not a thing this producer can emit. The three identity
    fields ``ProductStepPayload`` defaults are inherited, not repeated.
    """

    patient_id: int


class IntakeCapturedTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-005's ``intake.captured`` payload (B4e #739).

    ``duration_s`` is the step's own span - how long the capture took - and is the
    only duration in the funnel: the composer entry is an instant, not a span, so
    its row records NULL rather than a zero that would read as "took no time".
    """

    intake_id: int
    patient_id: int
    duration_s: float | None = None


class IntakeRetryRequestedTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-005's ``intake.retry_requested`` payload (B4e #739).

    The ``re_recorded`` step's source, and the only funnel event with NO identity
    reference at all: it names an intake, a round and a reason. The registry entry
    declares no actor kind for it, so the ledger row records none - a step with no
    human behind it is a machine outcome, not a null-filled placeholder that would
    inflate the active-actor count.
    """

    intake_id: int
    record_attempt: int


class PreSummaryReadyTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-005's ``pre_summary.ready`` payload (B4e #739)."""

    intake_id: int
    pre_summary_id: int
    patient_id: int


class PrescriptionDraftCreatedTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-006's ``prescription.draft_created`` payload (B4e #739).

    ``source`` is widened from the producer's ``PrescriptionSource`` literal to
    ``str``: the funnel records that a draft exists, and a producer that grows a
    source must not make this consumer fail to record a step (ADR-0003).
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int
    source: str
    attempt_no: int


class PrescriptionApprovedTelemetryPayload(ProductStepPayload):
    """MOD-013's mirror of MOD-006's ``prescription.approved`` payload (B4e #739).

    ``edited_yn`` is the one field the annotation queue (#752) reads beyond the
    identity the ledger row needs: the doctor's approved revision differed from
    the stored draft snapshot, which is what splits an acceptance into the
    unchanged and the edited class. The producer derives it against its own
    immutable snapshot and never ships the snapshot itself, so the boolean is
    all that travels.
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int
    edited_yn: bool


class PrescriptionRejectedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-006's ``prescription.rejected`` payload (#752).

    The annotation queue's rejection seat reads the four references and nothing
    else: the producer's free-text ``reason`` is deliberately NOT mirrored, so
    a doctor's rationale cannot reach ``observability_evaluation_scores``. What
    the queue records is the CLASSIFICATION (rejected), never the prose that
    came with it - the handoff note's rule, enforced at the mirror rather than
    trusted to the builder.
    """

    case_id: int
    prescription_id: int
    patient_id: int
    doctor_id: int


class PatientAuthFailedEventPayload(BaseModel):
    """The registry reconstruction shape for ``patient.auth_failed`` (#777).

    No module claimed this event's payload model before the security-signal
    consumers, so MOD-013 registers this mirror and the dispatcher rebuilds a
    claimed outbox row into it before fan-out. It mirrors the producer's field
    contract byte-for-byte (``identity_id``, ``phone_e164``, ``reason``,
    ``attempts_left``) because a narrow registry model would drop fields for
    every future consumer. The security handler re-validates it into
    :class:`PatientAuthFailedTelemetryPayload`, which is where the phone number
    and the attempt budget are shed before anything is written.
    """

    identity_id: int | None
    phone_e164: str
    reason: str
    attempts_left: int | None = None


class OtpFailedEventPayload(BaseModel):
    """The registry reconstruction shape for ``otp.failed`` (#777).

    Same reasoning as :class:`PatientAuthFailedEventPayload`: it mirrors the
    producer contract so the dispatcher can rebuild the row for any consumer.
    The security handler re-validates it into :class:`OtpFailedTelemetryPayload`,
    which keeps only the identity and reason.
    """

    identity_id: int
    phone_e164: str
    reason: str
    lockout_until: datetime | None = None


class PatientAuthFailedTelemetryPayload(BaseModel):
    """MOD-013's security-signal view of ``patient.auth_failed``.

    Carries only the identity reference and failure reason - no phone number,
    OTP value, or free text. The identity is hashed to a pseudonymous key
    before storage (security-phii-standards).
    """

    identity_id: int | None
    reason: str


class OtpFailedTelemetryPayload(BaseModel):
    """MOD-013's security-signal view of ``otp.failed``.

    Carries the identity reference and lockout reason - no phone number or OTP
    value. The identity is hashed to a pseudonymous key before storage.
    """

    identity_id: int
    reason: str


class OperatorMfaFailedTelemetryPayload(BaseModel):
    """MOD-013's security-signal view of ``operator.mfa_failed``.

    Keeps the identity reference and reason only - the lockout lift time, the
    TOTP code and the phone number are all shed before storage. The identity is
    hashed to a pseudonymous key.
    """

    identity_id: int
    reason: str


class RecordDeniedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-003's ``record.denied`` payload for security signals.

    Carries only the actor reference and kind - the producer's ``scope``,
    ``accessed_at`` and free-text ``metadata.denial_reason`` are dropped before
    the consumer runs, so none of them can reach ``observability_security_signals``.
    The actor is hashed to a pseudonymous subject key before storage.
    """

    record_id: int
    actor_id: int
    actor_type: str


#: Registry: the consumed event types that roll into ``obs_business_daily`` and
#: the stable ``metric_key`` each increments. ``metric_key`` mirrors the
#: canonical event-type name so a later phase can add a business metric by
#: adding one line here; the B5a rollup (#704) extends this same registry shape
#: (plan-phase14 §7.2, §8). ``audit.tamper_detected`` is intentionally absent -
#: it surfaces as an alert, not a business count.
BUSINESS_EVENT_METRICS: dict[str, str] = {
    EVENT_CASE_CONSULT_COMPLETE: EVENT_CASE_CONSULT_COMPLETE,
    EVENT_CASE_CLOSED: EVENT_CASE_CLOSED,
    EVENT_PARTNER_REGISTERED: EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_VERIFICATION_STARTED: EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_PARTNER_ACTIVATED: EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED: EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED: EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_SELECTED: EVENT_PARTNER_SELECTED,
    EVENT_CONSENT_REQUESTED: EVENT_CONSENT_REQUESTED,
    EVENT_CONSENT_GRANTED: EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REVOKED: EVENT_CONSENT_REVOKED,
    EVENT_RECORD_ACCESSED: EVENT_RECORD_ACCESSED,
    EVENT_AUDIT_EVENT: EVENT_AUDIT_EVENT,
}

#: Registry: the consumed event types that land in the product event ledger, each
#: mapped to the local mirror ``run_handler`` re-validates the dispatched payload
#: into. The key set is exactly ``PRODUCT_STEP_REGISTRY``'s event types - the funnel
#: registry names WHAT each event means, this one names the payload shape to read it
#: from, and the two are asserted equal rather than allowed to drift: a step with no
#: mirror has nowhere to read its actor from, and a mirror with no step is a payload
#: nobody consumes.
PRODUCT_EVENT_MIRRORS: dict[str, type[ProductStepPayload]] = {
    EVENT_INTAKE_COMPOSER_OPENED: IntakeComposerOpenedTelemetryPayload,
    EVENT_INTAKE_CAPTURED: IntakeCapturedTelemetryPayload,
    EVENT_INTAKE_RETRY_REQUESTED: IntakeRetryRequestedTelemetryPayload,
    EVENT_PRE_SUMMARY_READY: PreSummaryReadyTelemetryPayload,
    EVENT_CASE_CONSULT_COMPLETE: CaseConsultCompleteTelemetryPayload,
    EVENT_CASE_CLOSED: CaseClosedTelemetryPayload,
    EVENT_PRESCRIPTION_DRAFT_CREATED: PrescriptionDraftCreatedTelemetryPayload,
    EVENT_PRESCRIPTION_APPROVED: PrescriptionApprovedTelemetryPayload,
}

#: Registry: the doctor review OUTCOMES that become annotation-queue entries
#: (#752), each mapped to the mirror the queue reads its verdict-bearing fields
#: from. The key set is the terminal outcomes of the doctor's review - approved
#: (split into the unchanged and edited classes by ``edited_yn``) and rejected.
#: ``prescription.reviewed`` is deliberately absent: it announces that an edit
#: was SAVED, carries no outcome to classify, and is not terminal - accepting it
#: would label a draft that may never be approved or rejected. MOD-013 also has
#: a funnel-step seat for ``prescription.approved``; the registries overlap
#: there on purpose, and the ONE seat carries both effects.
ANNOTATION_EVENT_MIRRORS: dict[str, type[BaseModel]] = {
    EVENT_PRESCRIPTION_APPROVED: PrescriptionApprovedTelemetryPayload,
    EVENT_PRESCRIPTION_REJECTED: PrescriptionRejectedTelemetryPayload,
}

#: Alert severities (``obs_alert_events.severity``) - low-cardinality vocabulary
#: the operator feed and the B5a rollup share.
ALERT_SEVERITY_CRITICAL = "critical"
ALERT_SEVERITY_WARNING = "warning"

#: Alert kinds (``obs_alert_events.kind``): the machine-readable alert category.
ALERT_KIND_AUDIT_TAMPER = "audit_tamper"
ALERT_KIND_AI_EGRESS = "ai_egress"


@dataclass(frozen=True)
class AlertRow:
    """The pure decision + column values one event writes to ``obs_alert_events``.

    ``payload`` is a PHI-free JSON map of ids and facts only (coding-standards
    §3; ``error-handling-observability.md`` §5) - never transcript, phone or a
    raw provider payload.
    """

    severity: str
    kind: str
    title: str
    payload: dict[str, Any]


def build_tamper_alert(payload: TamperDetectedTelemetryPayload, producer: str) -> AlertRow:
    """Build the critical alert for one blocked ``audit.tamper_detected`` attempt.

    Mirrors the trigger's tamper facts into a PHI-free payload: the attempted
    operation, the targeted event id and when it happened. The producer's
    ``details`` (row data) is never copied (see
    ``TamperDetectedTelemetryPayload``).
    """
    return AlertRow(
        severity=ALERT_SEVERITY_CRITICAL,
        kind=ALERT_KIND_AUDIT_TAMPER,
        title="Audit tamper attempt blocked",
        payload={
            "source": producer,
            "attempted_operation": payload.attempted_operation,
            "target_event_id": payload.target_event_id,
            "attempted_at": payload.attempted_at.isoformat(),
        },
    )


def build_ai_egress_alert(payload: AiEgressRecordedTelemetryPayload, producer: str) -> AlertRow:
    """Build the informational alert for one PHI-minimized ``ai_egress.recorded``.

    The AI-egress guardrail is surfaced as a monitored signal, not rebuilt
    (plan-phase14 §10): ids plus the egress reason only, never the egressed
    bytes.
    """
    return AlertRow(
        severity=ALERT_SEVERITY_WARNING,
        kind=ALERT_KIND_AI_EGRESS,
        title="AI egress recorded",
        payload={
            "source": producer,
            "intake_id": payload.intake_id,
            "ai_job_id": payload.ai_job_id,
            "reason": payload.reason,
        },
    )
