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
``pre_summary.low_confidence`` and ``report.filed`` - as ledgered telemetry
seams (#424).

The subscription bodies are deliberately connector-only: a finalized /
low-confidence pre-summary reaching the care module is a funnel fact, not a
write. The case-birth write (``pre_summary.ready`` -> ``care_cases`` row) and
the forced-review flag belong to later integration passes once the producer
event carries the patient identity (the payload today carries only
``intake_id`` + ``pre_summary_id``, and ``care_cases.patient_id`` is NOT
NULL); ``report.filed`` case-context attachment is Phase 9. Each handler
ledgers first (``run_handler``) so a replayed ``event_id`` is a no-op, then
logs a structured, PHI-free line keyed by that ``event_id`` (error-handling-
observability §3) with its process-local counter - mirroring the
``intake.started`` funnel telemetry seam (PHASE-7 T05 #369).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
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
from modules.care.care_models import CARE_SCHEMA
from modules.care.domain.events import (
    CaseClosedPayload,
    CaseConsultCompletePayload,
    PrescriptionApprovedPayload,
    PrescriptionDraftCreatedPayload,
    PrescriptionIssuedPayload,
    PrescriptionRejectedPayload,
    PrescriptionReviewedPayload,
)

logger = logging.getLogger(__name__)


#: Consumer-side mirrors of the events care subscribes to. care cannot import
#: the producing module's ``domain`` package (ADR-0003 facade-only isolation),
#: so it validates each inbound payload against its own minimal, PHI-free copy.
#: Only the ids care needs are declared; producer-only fields (e.g. the report
#: filename) are ignored on validation - they never cross into care.
class CarePreSummaryReadyPayload(BaseModel):
    """Subject of ``pre_summary.ready``: a pre-summary draft reached the care module."""

    intake_id: int
    pre_summary_id: int


class CarePreSummaryLowConfidencePayload(BaseModel):
    """Subject of ``pre_summary.low_confidence``: a below-confidence pre-summary."""

    intake_id: int
    pre_summary_id: int


class CareReportFiledPayload(BaseModel):
    """Subject of ``report.filed``: a lab report was filed into the patient record."""

    order_id: int


#: Process-local running totals of delivered inbound telemetry events (KPI-001
#: "pipeline counters per loop stage" family). Zero at process start and bumped
#: once per ledger-deduped delivery, so a replayed ``event_id`` is idempotently
#: skipped and each count tracks distinct deliveries. Telemetry only - no
#: domain table and no outbox row is written by these seams (PHASE-8 T08 #424).
_COUNTERS: dict[str, int] = {}


def pre_summary_ready_count() -> int:
    """Return the process-local count of distinct ``pre_summary.ready`` deliveries."""
    return _COUNTERS.get(EVENT_PRE_SUMMARY_READY, 0)


def pre_summary_low_confidence_count() -> int:
    """Return the process-local count of distinct ``pre_summary.low_confidence`` deliveries."""
    return _COUNTERS.get(EVENT_PRE_SUMMARY_LOW_CONFIDENCE, 0)


def report_filed_count() -> int:
    """Return the process-local count of distinct ``report.filed`` deliveries."""
    return _COUNTERS.get(EVENT_REPORT_FILED, 0)


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
            _COUNTERS[event_type] = _COUNTERS.get(event_type, 0) + 1
            logger.info(
                "%s telemetry event_id=%s %s count=%s",
                label,
                envelope.event_id,
                _format_payload_fields(payload, field_names),
                _COUNTERS[event_type],
            )

        await run_handler(envelope, payload_model, _impl, ledger_suffix, CARE_SCHEMA)

    return handler


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the care module's event payload models + inbound subscriptions.

    MOD-006 owns the producer payload models for the seven events it publishes,
    incl. ``prescription.issued`` (the producer owns its contract); the
    dispatcher reconstructs a claimed ``care_outbox`` row with each before
    fan-out. The three §4.2 inbound subscriptions (MOD-005 -> MOD-006,
    MOD-007 -> MOD-006) are ledgered telemetry seams.
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

    # pre_summary.ready: the case-birth signal - a case is born when its
    # pre-summary is finalized. The spawn write is deferred (the producer
    # payload carries no patient identity), so this seam records the funnel
    # fact and the count only (AMB-006, ADR-0001).
    registry.register(
        EVENT_PRE_SUMMARY_READY,
        _make_telemetry_handler(
            event_type=EVENT_PRE_SUMMARY_READY,
            label="pre_summary.ready",
            payload_model=CarePreSummaryReadyPayload,
            ledger_suffix="pre_summary_ready_telemetry",
            field_names=("intake_id", "pre_summary_id"),
        ),
    )
    # pre_summary.low_confidence: the forced-review handshake-gate outset. The
    # gate lives at CareFacade.mark_consult_complete; this seam records the
    # funnel fact that a low-confidence summary reached the care module.
    registry.register(
        EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
        _make_telemetry_handler(
            event_type=EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
            label="pre_summary.low_confidence",
            payload_model=CarePreSummaryLowConfidencePayload,
            ledger_suffix="pre_summary_low_confidence_telemetry",
            field_names=("intake_id", "pre_summary_id"),
        ),
    )
    # report.filed: Phase 9 (MOD-007) case-context attachment seam. MOD-003
    # persists report.filed into the timeline; here only the order id travels.
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
