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
    EVENT_AUDIT_EVENT,
    EVENT_AUDIT_TAMPER_DETECTED,
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
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.observability.domain.consumer import (
    BUSINESS_EVENT_METRICS,
    AiEgressRecordedTelemetryPayload,
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
    AuditEventTelemetryPayload,
    CaseClosedTelemetryPayload,
    CaseConsultCompleteTelemetryPayload,
    ConsentLifecycleTelemetryPayload,
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
from modules.observability.facade import (
    OBSERVABILITY_SCHEMA,
    accumulate_ai_usage,
    accumulate_business_count,
    record_alert_event,
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

    async def accumulate_ai_job_completed(envelope: Envelope[BaseModel]) -> None:
        """Consume ``ai_job.completed``: accumulate one success into the daily row.

        Ledger first, upsert second, one transaction: a redelivered ``event_id``
        finds its ledger row and skips the upsert (at-least-once).
        """

        async def _impl(connection: AsyncConnection, payload: AiJobCompletedUsagePayload) -> None:
            await accumulate_ai_usage(connection, envelope, payload)

        await run_handler(
            envelope,
            AiJobCompletedUsagePayload,
            _impl,
            "accumulate_ai_usage_completed",
            OBSERVABILITY_SCHEMA,
        )

    registry.register(EVENT_AI_JOB_COMPLETED, accumulate_ai_job_completed)

    async def accumulate_ai_job_failed(envelope: Envelope[BaseModel]) -> None:
        """Consume ``ai_job.failed``: accumulate one failure/timeout into the row.

        Ledger first, upsert second, one transaction: a redelivered ``event_id``
        finds its ledger row and skips the upsert (at-least-once). Timeouts are
        bucketed separately from other failures via the event's derived flag.
        """

        async def _impl(connection: AsyncConnection, payload: AiJobFailedUsagePayload) -> None:
            await accumulate_ai_usage(connection, envelope, payload)

        await run_handler(
            envelope,
            AiJobFailedUsagePayload,
            _impl,
            "accumulate_ai_usage_failed",
            OBSERVABILITY_SCHEMA,
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
