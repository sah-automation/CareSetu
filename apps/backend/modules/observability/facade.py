"""MOD-013 Observability: typed public sync API + the consumer's effect writes.

The only legal cross-module import target for the ``observability``
module (coding-standards §2, ADR-0003). It is telemetry, not a domain
bounded context: typed read methods over the aggregates arrive with the
operator read routes (Batch 1 C1); the B4 public surface carries the effects
the event consumers run - the AI-usage aggregation (B4a #702), the
registry-driven business-daily counts and the PHI-free alert rows (B4b #703) -
plus the schema constant the composition root resolves the ledger against.

The B5a nightly rollup (#704) joins it as :func:`run_rollup`: the off-request-path
pass that recomputes the percentile aggregates, snapshots budget spend and
evaluates the alert thresholds. B5b (#705) adds the two scheduler seams the
scheduled GitHub Action drives it through - :func:`load_rollup_state`, which
reports what the rollup has already covered, and :func:`plan_rollup_dates`, which
turns that state into the dates one invocation rolls (the first-run backfill, the
previous day afterwards). Both are re-exported here so the
``python -m worker.rollup`` entry point reaches them through the facade, like
every other composition-root seam.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, literal_column
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from modules.observability.domain.consumer import (
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
    AlertRow,
)
from modules.observability.domain.rollup import (
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    RollupPlan,
    RollupThresholds,
    plan_rollup_dates,
)
from modules.observability.rollup import RollupReport, RollupRunState, load_rollup_state, run_rollup
from modules.observability.schema.models import (
    observability_ai_usage_daily,
    observability_alert_events,
    observability_business_daily,
)

OBSERVABILITY_SCHEMA = "observability"

__all__ = [
    "OBSERVABILITY_SCHEMA",
    "ROLLUP_MODE_BACKFILL",
    "ROLLUP_MODE_DAILY",
    "ObservabilityFacade",
    "RollupPlan",
    "RollupReport",
    "RollupRunState",
    "RollupThresholds",
    "accumulate_ai_usage",
    "accumulate_business_count",
    "load_rollup_state",
    "plan_rollup_dates",
    "record_alert_event",
    "run_rollup",
]


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


async def accumulate_business_count(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    metric_key: str,
) -> None:
    """Increment one registry-driven business count in ``observability_business_daily``.

    B4b (#703): the consumer's business-event handlers call this for every
    event type in ``BUSINESS_EVENT_METRICS``. The row is keyed by
    ``(metric_key, metric_date)`` with ``metric_date`` taken from the
    envelope's occurrence date (UTC); ``value`` is JSON so later phases add
    fields without schema churn (plan-phase14 §7.2). The increment is atomic
    via ``ON CONFLICT DO UPDATE``: ``value.count`` is bumped in place, so
    concurrent deliveries of distinct events accumulate without a read-modify-
    write race.

    Runs inside the handler's SAME transaction as the ``consumed_events``
    ledger write (the ledger row is recorded first by ``run_handler``), so a
    replayed ``event_id`` never reaches this effect and a crash rolls both back
    together (ADR-0002 §3).
    """
    table = observability_business_daily
    metric_date = envelope.occurred_at.date()
    existing_count = func.coalesce(cast(table.c.value.op("->>")("count"), Integer), 0)
    statement = (
        insert(table)
        .values(metric_key=metric_key, metric_date=metric_date, value={"count": 1})
        .on_conflict_do_update(
            index_elements=["metric_key", "metric_date"],
            set_={
                "value": func.jsonb_set(
                    table.c.value,
                    literal_column("'{count}'::text[]"),
                    func.to_jsonb(existing_count + 1),
                ),
                "updated_at": func.now(),
            },
        )
    )
    await connection.execute(statement)


async def record_alert_event(connection: AsyncConnection, alert: AlertRow) -> None:
    """Insert one PHI-free alert row into ``observability_alert_events``.

    B4b (#703): the consumer's alert handlers (``audit.tamper_detected``, the
    ``ai_egress.recorded`` guardrail signal) call this. The ``id``, ``status``
    (``open``) and ``created_at`` columns take their server defaults. Like every
    other effect, it runs inside the handler's ledger-first transaction so a
    replayed ``event_id`` is a no-op (ADR-0002 §3).
    """
    await connection.execute(
        insert(observability_alert_events).values(
            severity=alert.severity,
            kind=alert.kind,
            title=alert.title,
            payload=alert.payload,
        )
    )


class ObservabilityFacade:
    """Typed public facade for observability (scaffold)."""
