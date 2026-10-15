"""MOD-005: the shared AI-job metering shape for every metered AI leg (B4 #722).

One insert, one complete and one fail helper, shared by the transcribe, structure
AND draft legs so the row write and the bus event cannot drift between them
(PS-03: a pass is a metered row per leg that ran - never a silent, unlogged
egress). Before #722 the helpers lived privately in ``adapters/pipeline.py``,
which left the prescription-drafting leg - driven from
``IntakeFacade.request_rx_draft``, not from the pipeline - with no way to meter
itself without importing the pipeline's privates. They moved here so the drafting
seam and the pipeline share one implementation.

Every helper writes on the caller's connection and never opens a transaction of
its own, so the job row and its event ride the SAME transaction as whatever else
the leg is finalizing (ADR-0002 §1): an event written after the commit could
describe work that rolled back, and an event that never lands leaves the
MOD-013 usage aggregate structurally unable to count the spend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import get_settings
from bus.outbox_writer import write_outbox
from modules.intake.adapters.ai_provider_mock import MOCK_AI_MODEL
from modules.intake.domain.events import (
    AiTaskType,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
)
from modules.intake.intake_models import INTAKE_SCHEMA
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.intake.pricing import compute_cost_paise
from modules.intake.schema.models import intake_ai_jobs
from observability.logging import get_trace_id


def configured_plan() -> tuple[str, str]:
    """The deployment's configured (provider, model) - the pre-call booking.

    ``AI_PROVIDER`` is a whitelist name so it is normalised to lower case; the
    model falls back to the mock's own identity when the deployment names none,
    so the booking column is never empty. This is the PLAN, not what served:
    :func:`complete_ai_job` overwrites it with the effective values once the call
    returns. Owned here so every metered leg books the same plan - the facade and
    the pipeline resolve it once, from one place.
    """
    settings = get_settings()
    return settings.ai_provider.strip().lower(), settings.ai_model or MOCK_AI_MODEL


async def insert_ai_job(
    connection: AsyncConnection,
    intake_id: int,
    *,
    provider: str,
    model: str,
    task_type: AiTaskType = "structure",
) -> int:
    """Create the running ai_jobs row for this leg (markable failed on error).

    The row is a booking marked BEFORE the provider call, so its provider/model
    are the configured plan (provider + placeholder model). A later successful
    leg finalization (:func:`complete_ai_job`) overwrites them with the effective
    serving values; a failure path only touches status/error_message.
    ``task_type`` defaults to ``structure`` (the pipeline's charge); the
    transcribe leg books a ``transcribe`` row and the drafting leg a ``draft``
    row, all with the SAME pre-call shape.
    """
    job_insert = await connection.execute(
        intake_ai_jobs.insert()
        .values(
            intake_id=intake_id,
            task_type=task_type,
            provider=provider,
            model=model,
            status="running",
            attempts=1,
        )
        .returning(intake_ai_jobs.c.id)
    )
    return int(job_insert.scalar_one())


def failure_reason(exc: BaseException) -> str:
    """A short, PHI-free operational failure reason for the job + event."""
    return type(exc).__name__


def is_timeout(exc: BaseException) -> bool:
    """True when ``exc``'s cause chain bottoms out in a provider timeout.

    ``post_with_backoff`` re-raises ``Ext002CallError(...) from exc``, so a
    timed-out HTTP call keeps its ``httpx.TimeoutException`` cause. The failed
    job classifies the failure as a timeout here - the telemetry consumer only
    reads the boolean off the event (B4a #702), never the gateway internals.
    """
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, httpx.TimeoutException):
            return True
        current = current.__cause__ or current.__context__
    return False


async def fail_ai_job(
    connection: AsyncConnection,
    *,
    ai_job_id: int,
    intake_id: int,
    patient_id: int,
    doctor_id: int | None,
    task_type: AiTaskType,
    reason: str,
    provider: str,
    model: str,
    timeout: bool,
) -> None:
    """Mark the ai_jobs row ``failed`` and publish ``ai_job.failed``.

    Runs in the SAME transaction as the rest of the failure path, so a timeout /
    malformed-output failure durably records the failed job and its bus event
    alongside whatever else the leg was writing (ADR-0002 §1). The event carries
    the configured plan's provider/model (the pre-call booking on the job row)
    and the derived ``timeout`` classification so the MOD-013 usage aggregate can
    bucket timeouts separately (B4a #702). It also carries the identity
    references B4c (#719) needs for attribution: the ``patient_id`` and
    ``doctor_id`` in scope at the caller and the ambient ``trace_id`` resolved
    producer-locally - identity only, no PHI.

    Tokens are deliberately NOT recorded here. A failed provider call returns an
    exception, not a usage report, so the row keeps whatever it durably knows
    (the pre-call booking) rather than a fabricated zero-charge success; the
    failed job is counted as a failed call, not as free spend.
    """
    await connection.execute(
        intake_ai_jobs.update()
        .where(intake_ai_jobs.c.id == ai_job_id)
        .values(
            status="failed",
            error_message=reason,
            updated_at=datetime.now(UTC),
        )
    )
    await write_outbox(
        connection,
        INTAKE_SCHEMA,
        INTAKE_OUTBOX_TABLE,
        ai_job_failed_envelope(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type=task_type,
            reason=reason,
            provider=provider,
            model=model,
            timeout=timeout,
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=get_trace_id(),
        ),
    )


async def complete_ai_job(
    connection: AsyncConnection,
    *,
    ai_job_id: int,
    intake_id: int,
    patient_id: int,
    doctor_id: int | None,
    task_type: AiTaskType,
    provider: str,
    model: str,
    confidence: float,
    elapsed_ms: int,
    input_tokens: int,
    output_tokens: int,
    low_confidence: bool,
) -> None:
    """Persist a successful AI job + publish ``ai_job.completed`` (shared leg shape).

    The completed row carries the effective (serving) provider/model, the
    provider confidence, the provider's reported token usage priced into
    ``cost_paise`` by the per-model pricing helper (#399), and the call latency;
    then ``ai_job.completed`` is emitted. The event carries the same metering
    facts plus the derived ``low_confidence`` flag so the MOD-013 usage aggregate
    accumulates from the event alone (B4a #702), and the identity references
    B4c (#719) needs for per-patient/doctor attribution - the ``patient_id`` and
    ``doctor_id`` in scope at the caller and the ambient ``trace_id`` resolved
    producer-locally. Runs in the SAME transaction as the rest of the success
    path so a pass is a metered row per leg that ran - never a silent, unlogged
    egress (PS-03). Shared by the transcribe (``task_type="transcribe"``, #401),
    structure (``task_type="structure"``) and draft (``task_type="draft"``,
    #722) legs so the completion shape cannot drift between them.
    """
    cost_paise = compute_cost_paise(model, input_tokens=input_tokens, output_tokens=output_tokens)
    await connection.execute(
        intake_ai_jobs.update()
        .where(intake_ai_jobs.c.id == ai_job_id)
        .values(
            status="completed",
            provider=provider,
            model=model,
            confidence=Decimal(str(confidence)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_paise=cost_paise,
            duration_ms=elapsed_ms,
            updated_at=datetime.now(UTC),
        )
    )
    await write_outbox(
        connection,
        INTAKE_SCHEMA,
        INTAKE_OUTBOX_TABLE,
        ai_job_completed_envelope(
            ai_job_id=ai_job_id,
            intake_id=intake_id,
            task_type=task_type,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_paise=cost_paise,
            duration_ms=elapsed_ms,
            low_confidence=low_confidence,
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=get_trace_id(),
        ),
    )


__all__ = [
    "complete_ai_job",
    "fail_ai_job",
    "failure_reason",
    "insert_ai_job",
    "is_timeout",
]
