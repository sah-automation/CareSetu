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

MOD-005 owns the registry payload models for ``ai_job.*`` (its self-
subscription seam registers them), so MOD-013 registers handlers ONLY - the
``run_handler`` harness re-validates the dispatched intake payload into the
local mirror before the effect runs, matching the MOD-011 consumer shape for
events it does not own (``partner.activated`` / ``partner.rejected``).
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import EVENT_AI_JOB_COMPLETED, EVENT_AI_JOB_FAILED
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.observability.domain.consumer import (
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
)
from modules.observability.facade import OBSERVABILITY_SCHEMA, accumulate_ai_usage


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
