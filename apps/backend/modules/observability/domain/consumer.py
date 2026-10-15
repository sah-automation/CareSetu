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

B7 (#724) adds the ``intake.doctor_assigned`` mirror: the care-attribution
edge's three references - intake, patient, doctor - and nothing else. It is the
mirror that makes "which doctor does this intake belong to" answerable inside
this schema without any module reading another's tables (ADR-0003).
"""

from __future__ import annotations

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
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_RECORD_ACCESSED,
)

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


class CaseConsultCompleteTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-006's ``case.consult_complete`` payload.

    B4b (#703): the observability consumer counts this business event. Its
    field contract mirrors what MOD-006 publishes; MOD-006 owns the registry
    model, so MOD-013 registers no duplicate - ``run_handler`` re-validates the
    dispatched care payload into this local mirror before the count runs.
    """

    case_id: int
    patient_id: int
    doctor_id: int
    pre_summary_id: int | None = None


class CaseClosedTelemetryPayload(BaseModel):
    """MOD-013's mirror of MOD-006's ``case.closed`` payload (B4b #703)."""

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
