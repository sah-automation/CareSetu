"""MOD-005: composition root for the ``intake`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30): the
worker entrypoint calls it to register this module's handlers on the shared
``HandlerRegistry``. PHASE-7 T04 (#349) freezes the module's event set: it
owns the producer payload models for every intake / pre-summary / AI job
event it publishes so a claimed ``intake_outbox`` row is reconstructed with
a typed payload before fan-out, and registers the module's §4.2 self-
subscriptions - ``intake.started`` (telemetry-only log + count, T05 #369),
``intake.captured`` (async AI pipeline) and ``intake.retry_requested``
(re-record flow). The pipeline body lives in ``pipeline.py`` (T01 #365);
this file is the thin handler-registration front.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

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
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.intake.adapters.ai_provider_ext import build_ai_gateway
from modules.intake.adapters.ai_provider_mock import MOCK_AI_MODEL, MOCK_AI_PROVIDER
from modules.intake.adapters.pipeline import (
    _build_egress_gate,
    _build_media_store,
    _run_structuring_pipeline,
)
from modules.intake.domain.events import (
    AiEgressRecordedPayload,
    AiJobCompletedPayload,
    AiJobFailedPayload,
    IntakeCapturedPayload,
    IntakeRetryRequestedPayload,
    IntakeStartedPayload,
    PreSummaryLowConfidencePayload,
    PreSummaryReadyPayload,
)
from modules.intake.domain.state_machine import IntakeStatus
from modules.intake.intake_models import INTAKE_SCHEMA

logger = logging.getLogger(__name__)

#: Mock EXT-002 identity on the ai_jobs row (``{provider}-model`` convention)
#: and the insert-time model placeholder until the effective provider/model is
#: known after a successful structure call. Owned by the mock adapter and
#: re-exported here for the pipeline's ``_adapters`` indirection.
MOCK_AI_PROVIDER = MOCK_AI_PROVIDER
MOCK_AI_MODEL = MOCK_AI_MODEL

#: Consent gate the intake AI egress is authorised under (NFR-SEC-006).
AI_EGRESS_COUNTERPARTY_TYPE = "doctor"
AI_EGRESS_COUNTERPARTY_ID = "intake-ai"
AI_EGRESS_RECORD_SCOPE = "consultations"

#: Process-local running total of delivered ``intake.started`` telemetry events
#: (KPI-001 "pipeline counters per loop stage"). Zero at process start and
#: bumped once per ledger-deduped delivery, so a replayed ``event_id`` is
#: idempotently skipped and the count tracks distinct starts. Telemetry only -
#: no domain table and no outbox row is written by this seam (PHASE-7 T05 #369).
_intakes_started_count: int = 0


def intake_started_count() -> int:
    """Return the process-local count of distinct ``intake.started`` deliveries."""
    return _intakes_started_count


#: Explicit re-exports for pipeline.py's ``_adapters`` indirection (test patch
#: targets + constants); satisfies mypy --strict no_implicit_reexport.
__all__ = [
    "AI_EGRESS_COUNTERPARTY_ID",
    "AI_EGRESS_COUNTERPARTY_TYPE",
    "AI_EGRESS_RECORD_SCOPE",
    "MOCK_AI_MODEL",
    "MOCK_AI_PROVIDER",
    "_build_egress_gate",
    "_build_media_store",
    "build_ai_gateway",
]


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the intake module's event payload models + self-subscriptions.

    MOD-005 owns the producer payload models for its own published events; the
    dispatcher reconstructs a claimed ``intake_outbox`` row with each before
    fan-out. The two §4.2 self-subscriptions (MOD-005 -> MOD-005 self) are
    ``intake.captured`` (the async AI pipeline happy path, T10 #354) and
    ``intake.retry_requested`` (the re-record pipeline re-trigger, T09 #406).
    """
    for event_type, payload_model in (
        (EVENT_INTAKE_STARTED, IntakeStartedPayload),
        (EVENT_INTAKE_CAPTURED, IntakeCapturedPayload),
        (EVENT_INTAKE_RETRY_REQUESTED, IntakeRetryRequestedPayload),
        (EVENT_PRE_SUMMARY_READY, PreSummaryReadyPayload),
        (EVENT_PRE_SUMMARY_LOW_CONFIDENCE, PreSummaryLowConfidencePayload),
        (EVENT_AI_JOB_COMPLETED, AiJobCompletedPayload),
        (EVENT_AI_JOB_FAILED, AiJobFailedPayload),
        (EVENT_AI_EGRESS_RECORDED, AiEgressRecordedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    registry.register(EVENT_INTAKE_STARTED, _on_intake_started)
    registry.register(EVENT_INTAKE_CAPTURED, _on_intake_captured)
    registry.register(EVENT_INTAKE_RETRY_REQUESTED, _on_intake_retry_requested)


async def _on_intake_started(envelope: Envelope[BaseModel]) -> None:
    """Consume ``intake.started``: log + count the funnel-telemetry entry.

    Telemetry-only (PHASE-7 T05 #369, KPI-001 pipeline counters). Ledger first
    (``run_handler``) so a replayed ``event_id`` is a no-op, then a structured
    log line carrying modal/language facts and the process-local running count.
    Deliberately touches no domain table and emits no outbox row of its own -
    this subscription IS the funnel metric, not an effect.
    """

    async def _impl(connection: AsyncConnection, payload: IntakeStartedPayload) -> None:
        del connection
        global _intakes_started_count
        _intakes_started_count += 1
        logger.info(
            "intake.started telemetry: patient_id=%s mode=%s language=%s count=%s",
            payload.patient_id,
            payload.mode,
            payload.language,
            _intakes_started_count,
        )

    await run_handler(
        envelope,
        IntakeStartedPayload,
        _impl,
        "intake_started_telemetry",
        INTAKE_SCHEMA,
    )


async def _on_intake_captured(envelope: Envelope[BaseModel]) -> None:
    """Consume ``intake.captured``: run the async AI structuring pipeline.

    Ledger first (``run_handler``), pipeline second, one transaction boundary.
    A redelivered ``event_id`` finds its ledger row and skips (at-least-once -
    exactly one pre-summary per captured event). The pipeline never raises a
    user-visible error: a missing or non-structurable intake degrades to a
    logged skip.
    """

    async def _impl(connection: AsyncConnection, payload: IntakeCapturedPayload) -> None:
        await _run_structuring_pipeline(connection, payload.intake_id)

    await run_handler(
        envelope,
        IntakeCapturedPayload,
        _impl,
        "intake_structuring_pipeline",
        INTAKE_SCHEMA,
    )


async def _on_intake_retry_requested(envelope: Envelope[BaseModel]) -> None:
    """Consume ``intake.retry_requested``: re-run the structuring pipeline.

    Ledger first (``run_handler``), pipeline second, one transaction boundary.
    The re-record facade emits this event AFTER attaching the fresh clip and
    incrementing the record attempt (Re-record -> Structuring, ``RETRY_ACCEPTED``);
    consuming it re-runs ``transcribe -> structure -> pre_summary`` on the new
    clip so a re-recorded intake never stalls in ``structuring`` (PS-07, #406).
    The pipeline's retry entry accepts an intake already in ``structuring``; a
    replayed ``event_id`` finds its ledger row and skips, and the ``intake.captured``
    entry stays strict so a replayed captured on an in-flight intake still skips.
    """

    async def _impl(connection: AsyncConnection, payload: IntakeRetryRequestedPayload) -> None:
        await _run_structuring_pipeline(
            connection,
            payload.intake_id,
            expected_status=IntakeStatus.STRUCTURING,
        )

    await run_handler(
        envelope,
        IntakeRetryRequestedPayload,
        _impl,
        "intake_retry_requested",
        INTAKE_SCHEMA,
    )
