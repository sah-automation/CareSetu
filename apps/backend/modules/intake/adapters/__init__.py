"""MOD-005: composition root for the ``intake`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30): the
worker entrypoint calls it to register this module's handlers on the shared
``HandlerRegistry``. PHASE-7 T04 (#349) freezes the module's event set: it
owns the producer payload models for every intake / pre-summary / AI job
event it publishes so a claimed ``intake_outbox`` row is reconstructed with
a typed payload before fan-out, and registers the module's two §4.2 self-
subscriptions - ``intake.captured`` (async AI pipeline) and
``intake.retry_requested`` (re-record flow). The pipeline body lives in
``pipeline.py`` (T01 #365); this file is the thin handler-registration front.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.intake.adapters.ai_provider_ext import build_ai_gateway
from modules.intake.adapters.pipeline import _build_egress_gate, _run_structuring_pipeline
from modules.intake.domain.events import (
    AiEgressRecordedPayload,
    AiJobCompletedPayload,
    AiJobFailedPayload,
    IntakeCapturedPayload,
    IntakeRetryRequestedPayload,
    PreSummaryLowConfidencePayload,
    PreSummaryReadyPayload,
)
from modules.intake.facade import INTAKE_SCHEMA

#: Mock EXT-002 model id on the ai_jobs row (``{provider}-model`` convention).
MOCK_AI_MODEL = "mock-model"

#: Egress-context placeholders until real patient-profile sourcing lands (T11).
DEFAULT_EGRESS_AGE_RANGE = "30-40"
DEFAULT_EGRESS_SEX = "other"

#: Consent gate the intake AI egress is authorised under (NFR-SEC-006).
AI_EGRESS_COUNTERPARTY_TYPE = "doctor"
AI_EGRESS_COUNTERPARTY_ID = "intake-ai"
AI_EGRESS_RECORD_SCOPE = "consultations"

#: Explicit re-exports for pipeline.py's ``_adapters`` indirection (test patch
#: targets + constants); satisfies mypy --strict no_implicit_reexport.
__all__ = [
    "AI_EGRESS_COUNTERPARTY_ID",
    "AI_EGRESS_COUNTERPARTY_TYPE",
    "AI_EGRESS_RECORD_SCOPE",
    "DEFAULT_EGRESS_AGE_RANGE",
    "DEFAULT_EGRESS_SEX",
    "MOCK_AI_MODEL",
    "_build_egress_gate",
    "build_ai_gateway",
]


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the intake module's event payload models + self-subscriptions.

    MOD-005 owns the producer payload models for its own published events; the
    dispatcher reconstructs a claimed ``intake_outbox`` row with each before
    fan-out. The two §4.2 self-subscriptions (MOD-005 -> MOD-005 self) are
    ``intake.captured`` (the async AI pipeline happy path, T10 #354) and
    ``intake.retry_requested`` (the re-record body, T08).
    """
    for event_type, payload_model in (
        (EVENT_INTAKE_CAPTURED, IntakeCapturedPayload),
        (EVENT_INTAKE_RETRY_REQUESTED, IntakeRetryRequestedPayload),
        (EVENT_PRE_SUMMARY_READY, PreSummaryReadyPayload),
        (EVENT_PRE_SUMMARY_LOW_CONFIDENCE, PreSummaryLowConfidencePayload),
        (EVENT_AI_JOB_COMPLETED, AiJobCompletedPayload),
        (EVENT_AI_JOB_FAILED, AiJobFailedPayload),
        (EVENT_AI_EGRESS_RECORDED, AiEgressRecordedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    registry.register(EVENT_INTAKE_CAPTURED, _on_intake_captured)
    registry.register(EVENT_INTAKE_RETRY_REQUESTED, _on_intake_retry_requested)


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
    """Re-record flow seam (T08 #352). Registered here for the composition root."""

    async def _impl(connection: AsyncConnection, payload: IntakeRetryRequestedPayload) -> None:
        del connection, payload

    await run_handler(
        envelope,
        IntakeRetryRequestedPayload,
        _impl,
        "intake_retry_requested",
        INTAKE_SCHEMA,
    )
