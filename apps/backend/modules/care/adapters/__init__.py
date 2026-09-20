"""MOD-006: composition root for the ``care`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30): the
worker entrypoint calls it to register this module's handlers on the shared
``HandlerRegistry``. PHASE-8 T08 (#424) freezes the module's event set: care
owns the producer payload models for every case / prescription event it
publishes - ``case.consult_complete``, ``case.closed``,
``prescription.draft_created``, ``prescription.reviewed``,
``prescription.approved``, ``prescription.rejected`` **and**
``prescription.issued`` - so a claimed ``care_outbox`` row is reconstructed
with a typed payload before fan-out (producer owns its contract; health
consumes ``prescription.issued`` through its own tolerant mirror). It also
registers the module's §4.2 inbound subscriptions - ``pre_summary.ready``,
``pre_summary.low_confidence`` and ``report.filed``.

PHASE-8 review-close T2 (#428) turns the pre-summary subscriptions from pure
telemetry seams into real case-birth writes:

- ``pre_summary.ready`` births the care case: the insert (patient,
  ``pre_summary_id``, PreSummary stage, ``forced_review`` false) shares ONE
  transaction with the consumed-event mark, so an at-least-once replay of the
  same ``event_id`` is a no-op (ledger dedupe) and a second ready delivery for
  an already-born pre_summary never double-inserts (per-pre_summary guard).
  In-flight pre-T2 payloads carry no patient identity; those deliveries degrade
  to the telemetry-only log instead of crashing.
- ``pre_summary.low_confidence`` sets ``forced_review`` on the matching case -
  record-and-surface only (ADR-0015 posture), the handshake gate itself is
  untouched (that changes in T4). Delivery may precede the birth event
  (delivery order across outboxes is not guaranteed); a missing case is a
  logged no-op, never an error.
- ``report.filed`` case-context attachment is Phase 9; it stays a ledgered
  telemetry seam (#424).

Each handler ledgers first (``run_handler``) so a replayed ``event_id`` is a
no-op, then applies its effect and logs a structured, PHI-free line keyed by
that ``event_id`` (error-handling-observability §3) with its process-local
counter (``modules.care.telemetry``) - mirroring the ``intake.started`` funnel
telemetry seam (PHASE-7 T05 #369).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
    EVENT_REPORT_FILED,
)
from bus.handler_harness import run_handler
from bus.registry import Handler, HandlerRegistry
from modules.care import telemetry
from modules.care.care_models import CARE_SCHEMA
from modules.care.telemetry import (
    pre_summary_low_confidence_count,
    pre_summary_ready_count,
    report_filed_count,
)

#: Re-exports of the telemetry-helper accessors so existing adapter imports keep
#: working (no behaviour change); explicit for mypy --strict no_implicit_reexport.
__all__ = [
    "pre_summary_low_confidence_count",
    "pre_summary_ready_count",
    "register_handlers",
    "report_filed_count",
]
from modules.care.domain.events import (
    CaseClosedPayload,
    CaseConsultCompletePayload,
    PrescriptionApprovedPayload,
    PrescriptionDraftCreatedPayload,
    PrescriptionIssuedPayload,
    PrescriptionRejectedPayload,
    PrescriptionReviewedPayload,
)
from modules.care.schema.models import (
    STAGE_PRE_SUMMARY,
    care_cases,
)

logger = logging.getLogger(__name__)


#: Consumer-side mirrors of the events care subscribes to. care cannot import
#: the producing module's ``domain`` package (ADR-0003 facade-only isolation),
#: so it validates each inbound payload against its own minimal, PHI-free copy.
#: Only the ids care needs are declared; producer-only fields (e.g. the report
#: filename) are ignored on validation - they never cross into care.
class CarePreSummaryReadyPayload(BaseModel):
    """Subject of ``pre_summary.ready``: a pre-summary draft/review reached care.

    ``patient_id`` is the owning patient identity the case-birth write needs
    (``care_cases.patient_id`` is NOT NULL). It is optional here because
    pre-T2 in-flight payloads do not carry it; those deliveries degrade to the
    telemetry-only log while the enriched events roll through (tolerant mirror).
    """

    intake_id: int
    pre_summary_id: int
    patient_id: int | None = None


class CarePreSummaryLowConfidencePayload(BaseModel):
    """Subject of ``pre_summary.low_confidence``: a below-confidence pre-summary."""

    intake_id: int
    pre_summary_id: int


class CareReportFiledPayload(BaseModel):
    """Subject of ``report.filed``: a lab report was filed into the patient record."""

    order_id: int


def _format_payload_fields(payload: BaseModel, field_names: tuple[str, ...]) -> str:
    """Render a PHI-free ``name=value`` context for a telemetry log line."""
    return " ".join(f"{name}={getattr(payload, name)}" for name in field_names)


def _make_telemetry_handler(
    *,
    event_type: str,
    label: str,
    payload_model: type[BaseModel],
    ledger_suffix: str,
    field_names: tuple[str, ...],
) -> Handler:
    """Build a ledgered, PHI-free telemetry seam handler for one inbound event.

    Connector-only by design: ledger first (``run_handler``) so a replayed
    ``event_id`` is a no-op, then a log line keyed by that ``event_id``
    (error-handling-observability §3) with the process-local running count.
    Touches no domain table and emits no outbox row (PHASE-8 T08 #424).
    """

    async def handler(envelope: Envelope[BaseModel]) -> None:
        async def _impl(connection: AsyncConnection, payload: BaseModel) -> None:
            del connection
            telemetry.bump_count(event_type)
            logger.info(
                "%s telemetry event_id=%s %s count=%s",
                label,
                envelope.event_id,
                _format_payload_fields(payload, field_names),
                telemetry.count_for(event_type),
            )

        await run_handler(envelope, payload_model, _impl, ledger_suffix, CARE_SCHEMA)

    return handler


async def _on_pre_summary_ready(envelope: Envelope[BaseModel]) -> None:
    """Consume ``pre_summary.ready``: birth the care case for the finalized summary.

    The case-birth write (patient, ``pre_summary_id``, PreSummary stage,
    ``forced_review`` false) shares ONE transaction with the consumed-event
    mark (``run_handler``), so an at-least-once replay of the same ``event_id``
    is a ledger no-op and can never double-insert. A second *distinct* ready
    delivery naming an already-born pre_summary (intake emits the event at both
    Draft creation and Final review) is guarded two ways: the SELECT fast path
    catches the common case, and ``INSERT ... ON CONFLICT DO NOTHING`` on the
    DB-level unique index ``uq_care_cases_pre_summary_id`` catches the
    concurrent-distinct-event race. Both paths yield exactly one care case per
    finalized pre-summary (US2). Pre-T2 in-flight payloads carry no patient
    identity and degrade to the telemetry-only log (the old behaviour) instead of
    crashing.
    """

    async def _impl(connection: AsyncConnection, payload: CarePreSummaryReadyPayload) -> None:
        telemetry.bump_count(EVENT_PRE_SUMMARY_READY)
        logger.info(
            "pre_summary.ready telemetry event_id=%s intake_id=%s pre_summary_id=%s count=%s",
            envelope.event_id,
            payload.intake_id,
            payload.pre_summary_id,
            telemetry.count_for(EVENT_PRE_SUMMARY_READY),
        )
        if payload.patient_id is None:
            logger.warning(
                "pre_summary.ready event_id=%s pre_summary_id=%s carries no patient "
                "identity; skipping case birth (pre-T2 payload in flight)",
                envelope.event_id,
                payload.pre_summary_id,
            )
            return

        existing = (
            await connection.execute(
                select(care_cases.c.id).where(care_cases.c.pre_summary_id == payload.pre_summary_id)
            )
        ).first()
        if existing is not None:
            logger.info(
                "pre_summary.ready event_id=%s pre_summary_id=%s case already born; skipping",
                envelope.event_id,
                payload.pre_summary_id,
            )
            return

        result = await connection.execute(
            insert(care_cases)
            .values(
                patient_id=payload.patient_id,
                pre_summary_id=payload.pre_summary_id,
                stage=STAGE_PRE_SUMMARY,
                forced_review=False,
            )
            .on_conflict_do_nothing(index_elements=["pre_summary_id"])
        )
        if result.rowcount == 0:
            logger.info(
                "pre_summary.ready event_id=%s pre_summary_id=%s case already born "
                "(concurrent); skipping",
                envelope.event_id,
                payload.pre_summary_id,
            )
            return
        logger.info(
            "pre_summary.ready event_id=%s birthed care case for pre_summary_id=%s",
            envelope.event_id,
            payload.pre_summary_id,
        )

    await run_handler(
        envelope,
        CarePreSummaryReadyPayload,
        _impl,
        "pre_summary_ready_case_birth",
        CARE_SCHEMA,
    )


async def _on_pre_summary_low_confidence(envelope: Envelope[BaseModel]) -> None:
    """Consume ``pre_summary.low_confidence``: flag the matching case for review.

    Sets ``forced_review`` true on the care case born for this pre_summary -
    record-and-surface only (ADR-0015): the handshake's single gate is untouched
    (that changes in T4 via ``mark_consult_complete``). Idempotent by design (an
    UPDATE is naturally replay-safe), and the delay case - ``low_confidence``
    delivered before ``pre_summary.ready`` births the case, since delivery order
    across outboxes is not guaranteed - degrades to a logged no-op, never an
    error. Ledger first (``run_handler``) so a replayed ``event_id`` skips.
    """

    async def _impl(
        connection: AsyncConnection, payload: CarePreSummaryLowConfidencePayload
    ) -> None:
        telemetry.bump_count(EVENT_PRE_SUMMARY_LOW_CONFIDENCE)
        logger.info(
            "pre_summary.low_confidence telemetry event_id=%s intake_id=%s "
            "pre_summary_id=%s count=%s",
            envelope.event_id,
            payload.intake_id,
            payload.pre_summary_id,
            telemetry.count_for(EVENT_PRE_SUMMARY_LOW_CONFIDENCE),
        )

        row = (
            await connection.execute(
                select(care_cases.c.id).where(care_cases.c.pre_summary_id == payload.pre_summary_id)
            )
        ).first()
        if row is None:
            logger.info(
                "pre_summary.low_confidence event_id=%s pre_summary_id=%s has no care case "
                "yet (delivery may precede the birth event); forced_review flag skipped",
                envelope.event_id,
                payload.pre_summary_id,
            )
            return

        await connection.execute(
            care_cases.update()
            .where(care_cases.c.pre_summary_id == payload.pre_summary_id)
            .values(forced_review=True)
        )
        logger.info(
            "pre_summary.low_confidence event_id=%s set forced_review on case "
            "for pre_summary_id=%s",
            envelope.event_id,
            payload.pre_summary_id,
        )

    await run_handler(
        envelope,
        CarePreSummaryLowConfidencePayload,
        _impl,
        "pre_summary_low_confidence_forced_review",
        CARE_SCHEMA,
    )


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the care module's event payload models + inbound subscriptions.

    MOD-006 owns the producer payload models for the seven events it publishes,
    incl. ``prescription.issued`` (the producer owns its contract); the
    dispatcher reconstructs a claimed ``care_outbox`` row with each before
    fan-out. The three §4.2 inbound subscriptions (MOD-005 -> MOD-006,
    MOD-007 -> MOD-006) birth the care case / set the forced-review flag on
    ``pre_summary.*`` and stay a ledgered telemetry seam for ``report.filed``
    (Phase 9 case-context attachment).
    """
    for event_type, payload_model in (
        (EVENT_CASE_CONSULT_COMPLETE, CaseConsultCompletePayload),
        (EVENT_CASE_CLOSED, CaseClosedPayload),
        (EVENT_PRESCRIPTION_DRAFT_CREATED, PrescriptionDraftCreatedPayload),
        (EVENT_PRESCRIPTION_REVIEWED, PrescriptionReviewedPayload),
        (EVENT_PRESCRIPTION_APPROVED, PrescriptionApprovedPayload),
        (EVENT_PRESCRIPTION_REJECTED, PrescriptionRejectedPayload),
        (EVENT_PRESCRIPTION_ISSUED, PrescriptionIssuedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    registry.register(EVENT_PRE_SUMMARY_READY, _on_pre_summary_ready)
    registry.register(EVENT_PRE_SUMMARY_LOW_CONFIDENCE, _on_pre_summary_low_confidence)
    registry.register(
        EVENT_REPORT_FILED,
        _make_telemetry_handler(
            event_type=EVENT_REPORT_FILED,
            label="report.filed",
            payload_model=CareReportFiledPayload,
            ledger_suffix="report_filed_telemetry",
            field_names=("order_id",),
        ),
    )
