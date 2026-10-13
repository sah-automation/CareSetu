"""MOD-013 Observability: typed public sync API + the consumer's effect writes.

The only legal cross-module import target for the ``observability``
module (coding-standards §2, ADR-0003). It is telemetry, not a domain
bounded context: typed read methods over the aggregates arrive with the
operator read routes (Batch 1 C1); this B4 (#702) public surface carries the
AI-usage aggregation effect the event consumers run, plus the schema constant
the composition root resolves the ledger against.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from modules.observability.domain.consumer import (
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
)
from modules.observability.schema.models import observability_ai_usage_daily

OBSERVABILITY_SCHEMA = "observability"


async def accumulate_ai_usage(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    payload: AiJobCompletedUsagePayload | AiJobFailedUsagePayload,
) -> None:
    """Accumulate one finished AI job into ``observability_ai_usage_daily``.

    Runs inside the handler's SAME transaction as the ``consumed_events``
    ledger write (the ledger row is recorded first by ``run_handler``), so a
    replayed ``event_id`` skips the effect and a crash rolls both back
    (ADR-0002 §3). The row is keyed by ``(usage_date, provider, model,
    task_type)`` with ``usage_date`` taken from the envelope's occurrence date
    (UTC) and all counters accumulated via ``ON CONFLICT DO UPDATE``.

    Completed jobs increment ``success_count``/``calls``, the token/cost
    totals, ``low_confidence_count`` when the derived flag is set, and fold the
    duration into the running ``avg_duration_ms`` mean over completions. Failed
    jobs increment ``failure_count`` (or ``timeout_count``, mutually exclusive
    buckets - ``calls == success + failure + timeout``). ``p95_duration_ms``
    stays NULL: the percentile columns are (re)computed by the nightly B5
    rollup (#704) from the raw event history, not here.
    """
    table = observability_ai_usage_daily
    usage_date = envelope.occurred_at.date()

    if isinstance(payload, AiJobCompletedUsagePayload):
        success_inc = 1
        timeout_inc = 0
        failure_inc = 0
        low_conf_inc = 1 if payload.low_confidence else 0
        input_inc = payload.input_tokens
        output_inc = payload.output_tokens
        cost_inc = payload.cost_paise
        duration = payload.duration_ms
    else:
        success_inc = 0
        timeout_inc = 1 if payload.timeout else 0
        failure_inc = 1 - timeout_inc
        low_conf_inc = 0
        input_inc = 0
        output_inc = 0
        cost_inc = 0
        duration = None

    if duration is not None:
        # Running mean over completions: the existing mean weighted by the
        # existing success count plus the new duration, over the new count.
        # ``coalesce`` covers rows born from failures (success_count 0 / NULL mean).
        new_avg = (func.coalesce(table.c.avg_duration_ms, 0) * table.c.success_count + duration) / (
            table.c.success_count + 1
        )
    else:
        new_avg = table.c.avg_duration_ms

    statement = (
        insert(table)
        .values(
            usage_date=usage_date,
            provider=payload.provider,
            model=payload.model,
            task_type=payload.task_type,
            calls=1,
            success_count=success_inc,
            failure_count=failure_inc,
            timeout_count=timeout_inc,
            low_confidence_count=low_conf_inc,
            input_tokens=input_inc,
            output_tokens=output_inc,
            cost_paise=cost_inc,
            avg_duration_ms=duration,
            p95_duration_ms=None,
        )
        .on_conflict_do_update(
            index_elements=["usage_date", "provider", "model", "task_type"],
            set_={
                "calls": table.c.calls + 1,
                "success_count": table.c.success_count + success_inc,
                "failure_count": table.c.failure_count + failure_inc,
                "timeout_count": table.c.timeout_count + timeout_inc,
                "low_confidence_count": table.c.low_confidence_count + low_conf_inc,
                "input_tokens": table.c.input_tokens + input_inc,
                "output_tokens": table.c.output_tokens + output_inc,
                "cost_paise": table.c.cost_paise + cost_inc,
                "avg_duration_ms": new_avg,
                "updated_at": func.now(),
            },
        )
    )
    await connection.execute(statement)


class ObservabilityFacade:
    """Typed public facade for observability (scaffold)."""
