"""MOD-013: event handlers for the ``observability`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30): the
worker entrypoint calls it to register this module's handlers on the shared
``HandlerRegistry``. B4a (#702) wires the async telemetry consumer: the
``ai_job.completed`` / ``ai_job.failed`` events MOD-005 publishes are consumed
through the shared ``run_handler`` harness with MOD-013's own payload mirrors,
accumulating one ``observability_ai_usage_daily`` row per (usage_date,
provider, model, task_type) scope. Every handler is idempotent (ADR-0002 §3):
its ``consumed_events`` ledger row is written FIRST - in the SAME transaction
as the upsert - so replaying a delivered ``event_id`` is a no-op and a crash
rolls both back together (exactly-once accumulation).

B4b (#703) extends the consumer to the rest of MOD-013's registry
subscriptions - ``case.*``, ``partner.*``, ``consent.*``, ``record.accessed``,
``audit.event`` and the two guardrail signals (``audit.tamper_detected``,
``ai_egress.recorded``). The business-event families increment the
registry-driven ``observability_business_daily`` counter; the two guardrail
signals write PHI-free ``observability_alert_events`` rows. Both effects ride
the same ledger-first ``run_handler`` transaction, so every subscription is
replay-safe.

B6 (#723) adds the granular attribution effect to the two ``ai_job.*`` handlers:
each finished AI job writes one ``observability_ai_job_spend`` row carrying the
usage date, the intake reference, HASHED patient and doctor keys, provider,
model, task type, tokens, cost, status and trace id. It runs in the same
transaction as the ledger row and the daily accumulation, so the replay proof
that holds for one holds for all three.

B7 (#724) registers the care-attribution subscription, ``intake.doctor_assigned``:
the edge. It writes one ``observability_care_attribution_edges`` row per doctor
pick - intake reference plus the hashed patient and doctor keys - in the same
ledger-first transaction. Doctor attribution rides this event rather than a join
to the care schema, which the module isolation rule forbids (ADR-0003); the edge
exists only because the event said so.

MOD-005 owns the registry payload models for ``ai_job.*`` (its self-
subscription seam registers them), so MOD-013 registers handlers ONLY - the
``run_handler`` harness re-validates the dispatched intake payload into the
local mirror before the effect runs, matching the MOD-011 consumer shape for
events it does not own (``partner.activated`` / ``partner.rejected``). The same
holds for the other owned families; MOD-013 registers a mirror ONLY for the
events no module has claimed (``partner.verification_started``,
``partner.selected``).
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AI_JOB_QUEUED,
    EVENT_AUDIT_EVENT,
    EVENT_AUDIT_TAMPER_DETECTED,
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REQUESTED,
    EVENT_CONSENT_REVOKED,
    EVENT_INTAKE_DOCTOR_ASSIGNED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
    EVENT_RECORD_ACCESSED,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.observability.domain.consumer import (
    BUSINESS_EVENT_METRICS,
    AiEgressRecordedTelemetryPayload,
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
    AiJobQueuedTelemetryPayload,
    AuditEventTelemetryPayload,
    CaseClosedTelemetryPayload,
    CaseConsultCompleteTelemetryPayload,
    ConsentLifecycleTelemetryPayload,
    IntakeDoctorAssignedTelemetryPayload,
    PartnerCredentialReviewedTelemetryPayload,
    PartnerDecisionTelemetryPayload,
    PartnerRegisteredTelemetryPayload,
    PartnerSelectedTelemetryPayload,
    PartnerVerificationStartedTelemetryPayload,
    RecordAccessTelemetryPayload,
    TamperDetectedTelemetryPayload,
    build_ai_egress_alert,
    build_tamper_alert,
)
from modules.observability.domain.pseudonym import ACTOR_KIND_PATIENT, actor_key
from modules.observability.facade import (
    OBSERVABILITY_SCHEMA,
    accumulate_ai_usage,
    accumulate_business_count,
    close_ai_queue_item,
    record_ai_job_spend,
    record_ai_queue_open,
    record_alert_event,
    record_care_attribution_edge,
)

#: B4b (#703): the consumed event types that roll into ``obs_business_daily``,
#: each mapped to the local mirror ``run_handler`` re-validates the dispatched
#: payload into. The key set is ``BUSINESS_EVENT_METRICS`` (domain) - the
#: registry drives both the handler seats and the ``metric_key`` each writes.
_BUSINESS_EVENT_MIRRORS: dict[str, type[BaseModel]] = {
    EVENT_CASE_CONSULT_COMPLETE: CaseConsultCompleteTelemetryPayload,
    EVENT_CASE_CLOSED: CaseClosedTelemetryPayload,
    EVENT_PARTNER_REGISTERED: PartnerRegisteredTelemetryPayload,
    EVENT_PARTNER_VERIFICATION_STARTED: PartnerVerificationStartedTelemetryPayload,
    EVENT_PARTNER_ACTIVATED: PartnerDecisionTelemetryPayload,
    EVENT_PARTNER_REJECTED: PartnerDecisionTelemetryPayload,
    EVENT_PARTNER_CREDENTIAL_REVIEWED: PartnerCredentialReviewedTelemetryPayload,
    EVENT_PARTNER_SELECTED: PartnerSelectedTelemetryPayload,
    EVENT_CONSENT_REQUESTED: ConsentLifecycleTelemetryPayload,
    EVENT_CONSENT_GRANTED: ConsentLifecycleTelemetryPayload,
    EVENT_CONSENT_REVOKED: ConsentLifecycleTelemetryPayload,
    EVENT_RECORD_ACCESSED: RecordAccessTelemetryPayload,
    EVENT_AUDIT_EVENT: AuditEventTelemetryPayload,
}

#: The consumed event types no module has claimed a payload model for, so
#: MOD-013 registers its mirror (the dispatcher reconstructs the outbox row with
#: the registered model before fan-out). Every other consumed event's model is
#: owned by its producer module and must NOT be re-registered - the registry's
#: one-model-per-type guard would raise (registry.py).
_UNCLAIMED_EVENT_MIRRORS: dict[str, type[BaseModel]] = {
    EVENT_PARTNER_VERIFICATION_STARTED: PartnerVerificationStartedTelemetryPayload,
    EVENT_PARTNER_SELECTED: PartnerSelectedTelemetryPayload,
}


def _patient_actor(payload: BaseModel) -> str:
    """The pseudonymous PATIENT actor behind an AI job payload (B5 #729).

    One function rather than a lambda per handler seat, so the three AI job events
    cannot each hash a little differently - the recent-activity figure counts
    DISTINCT keys off this ledger, and a handler that spelled the derivation its
    own way would silently split one patient into two actors.

    Returns the hash, never the raw reference: the ledger row is durable and a
    board read must not be able to name anybody. Typed as :class:`BaseModel`
    because the harness's projection parameter is generic over every mirror model;
    it is only ever handed one of the three that declares ``patient_id``.
    """
    reference: int = payload.patient_id  # type: ignore[attr-defined]
    return actor_key(ACTOR_KIND_PATIENT, reference)


def _register_business_counter(
    registry: HandlerRegistry, event_type: str, mirror: type[BaseModel]
) -> None:
    """Register one business-count handler for ``event_type`` (B4b #703).

    A distinct closure per event type (the registry rejects a reused handler
    seat on the same type). The handler writes its ledger row FIRST via
    ``run_handler``, then increments the registry's ``metric_key`` - so a
    replayed ``event_id`` is a no-op.
    """
    metric_key = BUSINESS_EVENT_METRICS[event_type]

    async def handler(envelope: Envelope[BaseModel]) -> None:
        async def _impl(connection: AsyncConnection, payload: BaseModel) -> None:
            del payload
            await accumulate_business_count(connection, envelope, metric_key)

        await run_handler(
            envelope,
            mirror,
            _impl,
            f"accumulate_business_metric_{event_type.replace('.', '_')}",
            OBSERVABILITY_SCHEMA,
        )

    registry.register(event_type, handler)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the observability module's event handlers (B4a #702)."""

    async def record_ai_job_queued(envelope: Envelope[BaseModel]) -> None:
        """Consume ``ai_job.queued``: add one still-open job to the queue table.

        B5 (#729). The ENQUEUE side of the queue, and the reason depth and age are
        measurable at all: ``ai_job.completed`` / ``ai_job.failed`` say what became
        of work that has already finished, so with only those two there is nothing
        to subtract them from and a stalled job is invisible until it is gone.

        Ledger first, then the effect, one transaction - a redelivered ``event_id``
        finds its ledger row and skips both (at-least-once). The row it writes is
        deleted by the completion/failure handlers, which is what makes depth
        exactly ``enqueued - completed - failed``.
        """

        async def _impl(connection: AsyncConnection, payload: AiJobQueuedTelemetryPayload) -> None:
            await record_ai_queue_open(connection, envelope, payload)

        await run_handler(
            envelope,
            AiJobQueuedTelemetryPayload,
            _impl,
            "record_ai_queue_open",
            OBSERVABILITY_SCHEMA,
            actor_key_of=_patient_actor,
        )

    registry.register(EVENT_AI_JOB_QUEUED, record_ai_job_queued)

    async def accumulate_ai_job_completed(envelope: Envelope[BaseModel]) -> None:
        """Consume ``ai_job.completed``: accumulate one success into the daily row.

        Ledger first, then all three effects, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips them all (at-least-once).
        B6 (#723) adds the second effect - the one-granular-row-per-job
        ``observability_ai_job_spend`` record the attribution aggregate is
        computed from - in the SAME transaction as the daily accumulation, so the
        two can never disagree about how many jobs ran. B5 (#729) adds the third:
        closing the job's queue row, because a completed job is no longer queued.
        """

        async def _impl(connection: AsyncConnection, payload: AiJobCompletedUsagePayload) -> None:
            await accumulate_ai_usage(connection, envelope, payload)
            await record_ai_job_spend(connection, envelope, payload)
            await close_ai_queue_item(connection, payload)

        await run_handler(
            envelope,
            AiJobCompletedUsagePayload,
            _impl,
            "accumulate_ai_usage_completed",
            OBSERVABILITY_SCHEMA,
            actor_key_of=_patient_actor,
        )

    registry.register(EVENT_AI_JOB_COMPLETED, accumulate_ai_job_completed)

    async def accumulate_ai_job_failed(envelope: Envelope[BaseModel]) -> None:
        """Consume ``ai_job.failed``: accumulate one failure/timeout into the row.

        Ledger first, then all three effects, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips them all (at-least-once).
        Timeouts are bucketed separately from other failures via the event's
        derived flag. The attempt is still recorded as a per-job row with zero
        tokens and zero cost: a job that was tried and failed spent nothing, but
        it did happen, and cost-per-pass is a ratio over attempts. Since B5 (#729)
        it also closes the job's queue row - a FAILED job left queued is the worst
        kind of stuck, because it never recovers and never clears.
        """

        async def _impl(connection: AsyncConnection, payload: AiJobFailedUsagePayload) -> None:
            await accumulate_ai_usage(connection, envelope, payload)
            await record_ai_job_spend(connection, envelope, payload)
            await close_ai_queue_item(connection, payload)

        await run_handler(
            envelope,
            AiJobFailedUsagePayload,
            _impl,
            "accumulate_ai_usage_failed",
            OBSERVABILITY_SCHEMA,
            actor_key_of=_patient_actor,
        )

    registry.register(EVENT_AI_JOB_FAILED, accumulate_ai_job_failed)

    # B4b (#703): the rest of MOD-013's subscriptions. The registry-driven
    # business counts roll each event family into ``obs_business_daily``; the
    # two alert families surface the tamper guard and the AI-egress guardrail.
    for event_type, mirror in _UNCLAIMED_EVENT_MIRRORS.items():
        registry.register_payload_model(event_type, mirror)

    for event_type, mirror in _BUSINESS_EVENT_MIRRORS.items():
        _register_business_counter(registry, event_type, mirror)

    async def record_tamper_alert(envelope: Envelope[BaseModel]) -> None:
        """Consume ``audit.tamper_detected``: write one PHI-free alert row.

        The tamper guard is surfaced, not rebuilt (plan-phase14 §10): the
        ledger row is written first, then the blocked attempt becomes a
        critical ``obs_alert_events`` row. The producer's ``details`` blob is
        dropped by the mirror, so no row data can reach the payload.
        """

        async def _impl(
            connection: AsyncConnection, payload: TamperDetectedTelemetryPayload
        ) -> None:
            await record_alert_event(connection, build_tamper_alert(payload, envelope.producer))

        await run_handler(
            envelope,
            TamperDetectedTelemetryPayload,
            _impl,
            "record_tamper_alert",
            OBSERVABILITY_SCHEMA,
        )

    registry.register(EVENT_AUDIT_TAMPER_DETECTED, record_tamper_alert)

    async def record_ai_egress_alert(envelope: Envelope[BaseModel]) -> None:
        """Consume ``ai_egress.recorded``: write one PHI-free alert row.

        The AI-egress minimization guardrail is surfaced as a monitored signal,
        not rebuilt (plan-phase14 §10): each PHI-minimized egress becomes an
        informational ``obs_alert_events`` row carrying ids plus the egress
        reason only.
        """

        async def _impl(
            connection: AsyncConnection, payload: AiEgressRecordedTelemetryPayload
        ) -> None:
            await record_alert_event(connection, build_ai_egress_alert(payload, envelope.producer))

        await run_handler(
            envelope,
            AiEgressRecordedTelemetryPayload,
            _impl,
            "record_ai_egress_alert",
            OBSERVABILITY_SCHEMA,
        )

    registry.register(EVENT_AI_EGRESS_RECORDED, record_ai_egress_alert)

    async def record_care_attribution(envelope: Envelope[BaseModel]) -> None:
        """Consume ``intake.doctor_assigned``: record the intake -> doctor edge.

        B7 (#724). The single effect, so it is a plain ``run_handler`` call rather
        than the registry-driven business-counter loop: the row this writes is not
        a count but the pairing the nightly rollup resolves an intake's spend
        through. ``run_handler`` writes the ``consumed_events`` ledger row FIRST,
        in the same transaction as the edge, so a redelivered ``event_id`` writes
        no edge and a crash rolls both back together.

        No business counter rides along, deliberately. ``intake.doctor_assigned``
        is not a funnel step or an activity signal - it is the attribution edge,
        and counting it would put a second meaning on the same delivery. The
        activity counts come from the product event ledger's own event family
        (#722's composer-opened entry step), not from this one.
        """

        async def _impl(
            connection: AsyncConnection, payload: IntakeDoctorAssignedTelemetryPayload
        ) -> None:
            await record_care_attribution_edge(connection, envelope, payload)

        await run_handler(
            envelope,
            IntakeDoctorAssignedTelemetryPayload,
            _impl,
            "record_care_attribution_edge",
            OBSERVABILITY_SCHEMA,
        )

    registry.register(EVENT_INTAKE_DOCTOR_ASSIGNED, record_care_attribution)
