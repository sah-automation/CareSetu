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

T3.5 (#752) adds the annotation-queue effect to the doctor review OUTCOMES -
``prescription.approved`` (whose seat already existed as a funnel step, so it
now carries two effects) and ``prescription.rejected`` (a new seat, one effect).
The queue is the ``source = 'human'`` half of ``observability_evaluation_scores``
(see ``domain.annotation``); it is fed here through the bus like every other
subscription, and the outcome CLASS is all a seat ever reads - the doctor's
free-text rationale is dropped by the rejected mirror before this file runs.
#753 gates the effect behind ANNOTATION_QUEUE_ENABLED (off by default): with the
gate off the approval keeps its funnel-step seat minus the annotation flag and
the rejection gets no seat at all, so no other feature moves.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import get_settings
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
from modules.observability.domain.annotation import annotation_trace_id
from modules.observability.domain.consumer import (
    ANNOTATION_EVENT_MIRRORS,
    BUSINESS_EVENT_METRICS,
    PRODUCT_EVENT_MIRRORS,
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
from modules.observability.domain.product import (
    ProductStep,
    ProductStepPayload,
    product_steps,
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
    record_annotation,
    record_care_attribution_edge,
    record_product_event,
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


@dataclass(frozen=True)
class _Seat:
    """The ONE handler seat an event type gets in this module, and its effects.

    ``event_type`` -> seat, built from the two registries this module reads
    (:data:`BUSINESS_EVENT_METRICS` and the funnel-step registry) rather than
    written out by hand.

    **One seat per event type, not one per effect** - and that is forced rather than
    chosen. ``observability.consumed_events`` is keyed by ``event_id`` ALONE within
    a schema, so the second handler to be delivered an envelope finds the ledger row
    the first one wrote, is correctly told it is a replay, and skips its own effect
    forever. Two effects on one event type therefore have to share one
    ``run_handler`` transaction, which is exactly how the three AI-job effects
    (#723) and the attribution edge (#724) already work.

    Getting this wrong is invisible: the second effect simply never runs, and its
    table stays empty with nothing failing.
    """

    event_type: str
    mirror: type[BaseModel]
    #: The ``metric_key`` this event increments in ``observability_business_daily``,
    #: or ``None`` when it is not a business event.
    business_metric: str | None
    #: The funnel step this event is recorded as, or ``None`` when it is not a step.
    product_step: ProductStep | None
    #: Whether this outcome becomes an annotation-queue entry (#752), the
    #: ``source = 'human'`` row the doctor's verdict writes. True for the two
    #: review outcomes in ``ANNOTATION_EVENT_MIRRORS``; a delivery carries it
    #: alongside whichever of the other two effects apply, never instead.
    annotation: bool

    @property
    def handler_name(self) -> str:
        """What the ``consumed_events`` row records this seat as having been.

        Names the EFFECTS, not the event, because an operator reading the ledger is
        asking what this module did with the delivery - and a seat carrying two
        effects must not be filed under one of them.
        """
        effects = []
        if self.business_metric is not None:
            effects.append("business_count")
        if self.product_step is not None:
            effects.append(f"product_event_{self.product_step.funnel}_{self.product_step.step}")
        if self.annotation:
            effects.append("annotation")
        return "record_" + "_and_".join(effects)


def _seats(*, annotation_enabled: bool) -> tuple[_Seat, ...]:
    """Every seat this module registers for an event it merely CONSUMES.

    The registry-driven path, and the reason "adding a funnel step is a registry
    entry, not a schema change" is true in fact rather than in intent: nothing here
    enumerates the funnel, and a step registered tomorrow gets its seat from this
    same function with no edit to this file.

    Where an event belongs to more than one registry - ``case.consult_complete`` /
    ``case.closed`` are business events AND funnel steps, ``prescription.approved``
    is a funnel step AND a review outcome (#752) - it gets ONE seat carrying every
    effect that applies, because the consumed-event ledger is keyed by ``event_id``
    alone and a second seat would be told it is a replay: see :class:`_Seat`.

    ``annotation_enabled`` is the #753 ``ANNOTATION_QUEUE_ENABLED`` gate, read once
    at the composition seam (:func:`register_handlers`). Off, the annotation effect
    leaves every seat: ``prescription.rejected``, whose ONLY effect it is, gets no
    seat at all (a no-effect handler would write a ledger row naming no effect),
    while ``prescription.approved`` keeps its funnel-step seat with the flag
    dropped - the gate moves nothing but the gate.
    """
    steps = {step.event_type: step for step in product_steps()}
    event_types = set(BUSINESS_EVENT_METRICS) | set(steps)
    if annotation_enabled:
        event_types |= set(ANNOTATION_EVENT_MIRRORS)
    return tuple(
        _Seat(
            event_type=event_type,
            mirror=_mirror_for(event_type, steps),
            business_metric=BUSINESS_EVENT_METRICS.get(event_type),
            product_step=steps.get(event_type),
            annotation=annotation_enabled and event_type in ANNOTATION_EVENT_MIRRORS,
        )
        for event_type in sorted(event_types)
    )


def _mirror_for(event_type: str, steps: Mapping[str, ProductStep]) -> type[BaseModel]:
    """The mirror a seat re-validates the dispatched payload into.

    The product registry's mirror when the event is a funnel step - it carries the
    identity fields the ledger row needs, and since #752 also ``edited_yn``, which
    the annotation effect splits the acceptance into two classes by. The annotation
    mirror next, for an outcome with no step to its name (``prescription.rejected``),
    and the business mirror otherwise. The registries overlap on ``prescription.
    approved`` and the two ``case.*`` events, and the product mirror is the wider of
    the shapes because it inherits ``ProductStepPayload``.
    """
    if event_type in steps:
        return PRODUCT_EVENT_MIRRORS[event_type]
    if event_type in ANNOTATION_EVENT_MIRRORS:
        return ANNOTATION_EVENT_MIRRORS[event_type]
    return _BUSINESS_EVENT_MIRRORS[event_type]


def _register_seat(registry: HandlerRegistry, seat: _Seat) -> None:
    """Register ``seat``'s single handler closure for its event type.

    The handler writes its ``consumed_events`` ledger row FIRST via ``run_handler``
    and only then its effects, in ONE transaction - so a replayed ``event_id`` is a
    no-op for all of them together and a crash rolls them all back together.
    """
    business_metric = seat.business_metric
    product_step = seat.product_step
    annotation = seat.annotation

    async def handler(envelope: Envelope[BaseModel]) -> None:
        async def _impl(connection: AsyncConnection, payload: BaseModel) -> None:
            if business_metric is not None:
                await accumulate_business_count(connection, envelope, business_metric)
            if product_step is not None:
                await record_product_event(
                    connection,
                    envelope,
                    product_step,
                    cast("ProductStepPayload", payload),
                )
            if annotation:
                await record_annotation(
                    connection,
                    payload,
                    trace_id=annotation_trace_id(),
                    occurred_at=envelope.occurred_at,
                )

        await run_handler(
            envelope,
            seat.mirror,
            _impl,
            seat.handler_name,
            OBSERVABILITY_SCHEMA,
        )

    registry.register(seat.event_type, handler)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the observability module's event handlers (B4a #702).

    #753: ``ANNOTATION_QUEUE_ENABLED`` is read HERE, at the composition seam -
    the same place the notify adapter reads its settings - so the gate lives at
    one layer up from the seats and no delivery ever re-reads it. With the gate
    off, :func:`_seats` simply never offers the annotation-only seat, and every
    other registration runs exactly as it did before the gate existed.
    """
    annotation_enabled = get_settings().annotation_queue_enabled

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

    # The event types no module has claimed a payload model for, so MOD-013 registers
    # its mirror. Declared SEPARATELY from the seats above because claiming a registry
    # model is a different act from taking a handler seat: it changes what the
    # dispatcher reconstructs a claimed outbox row with, not what this module does on
    # delivery. Both are registry-driven, so neither is a hand-maintained list.
    for event_type, mirror in _UNCLAIMED_EVENT_MIRRORS.items():
        registry.register_payload_model(event_type, mirror)

    # B4b (#703) + B4e (#739): the registry-driven seats for the events this module
    # merely CONSUMES - the business counts and the product event ledger's funnel
    # steps, from one seat per event type carrying whichever effects apply. #753:
    # the annotation gate is resolved above, before this loop, so the seats it
    # builds are the seats this deployment opted into.
    for seat in _seats(annotation_enabled=annotation_enabled):
        _register_seat(registry, seat)

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
