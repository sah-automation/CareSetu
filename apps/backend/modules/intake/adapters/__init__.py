"""MOD-005: event handlers for the ``intake`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. PHASE-7 T04 (#349) freezes the module's
event set: it owns the producer payload models for every intake /
pre-summary / AI job event it publishes (the producer owns the model, cf.
notify's ``register_payload_model``) so a claimed ``intake_outbox`` row is
reconstructed with a typed payload before fan-out, and it registers the
module's two self-subscriptions from the §4.2 registry - ``intake.captured``
(self-trigger for the async AI pipeline) and ``intake.retry_requested``
(re-record flow). The pipeline/re-record bodies themselves (structuring,
pre-summary publish, degrade paths) land in T08/T10/T11; the registration
seams ship here.
"""

from __future__ import annotations

from pydantic import BaseModel

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
from bus.registry import HandlerRegistry
from modules.intake.domain.events import (
    AiEgressRecordedPayload,
    AiJobCompletedPayload,
    AiJobFailedPayload,
    IntakeCapturedPayload,
    IntakeRetryRequestedPayload,
    PreSummaryLowConfidencePayload,
    PreSummaryReadyPayload,
)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the intake module's event payload models + self-subscriptions.

    MOD-005 owns the producer payload models for its own published events; the
    dispatcher reconstructs a claimed ``intake_outbox`` row with each before
    fan-out. The two §4.2 self-subscriptions (MOD-005 -> MOD-005 self) are
    registered as seams - ``intake.captured`` (async AI pipeline) and
    ``intake.retry_requested`` (re-record flow), whose bodies T08/T10/T11
    flesh out.
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

    async def _on_intake_captured(envelope: Envelope[BaseModel]) -> None:
        """Self-subscription seam: trigger the async AI pipeline on capture.

        No-op for now - the structuring/pre-summary pipeline body lands in
        T10 (pipeline happy path) and T11 (degradation); this registration is
        the incident the worker composition wires.
        """
        del envelope

    async def _on_intake_retry_requested(envelope: Envelope[BaseModel]) -> None:
        """Self-subscription seam: drive the re-record flow on retry request.

        No-op for now - the re-record body lands in T08 (media re-record);
        this registration is the seam the worker composition wires.
        """
        del envelope

    registry.register(EVENT_INTAKE_CAPTURED, _on_intake_captured)
    registry.register(EVENT_INTAKE_RETRY_REQUESTED, _on_intake_retry_requested)
