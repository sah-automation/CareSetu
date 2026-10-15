"""MOD-013 Observability: typed public sync API + the consumer's effect writes.

The only legal cross-module import target for the ``observability``
module (coding-standards §2, ADR-0003). It is telemetry, not a domain
bounded context: the C1 operator read methods arrive with the operator read
routes, split across two batches - C1a (``#706``) serves spend, usage and
quality; C1b (``#707``) serves the overview, latency, health, alert feed and
deep links. The B4 public surface carries the effects the event consumers
run - the AI-usage aggregation (B4a #702), the registry-driven business-daily
counts and the PHI-free alert rows (B4b #703) - plus the schema constant the
composition root resolves the ledger against.

B6 (#723) adds :func:`record_ai_job_spend`: the one-granular-row-per-AI-job
effect that makes per-patient and per-doctor attribution arithmetic rather than
guesswork, keyed on the one-way actor hashes rather than on raw identity
references.

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

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, literal, literal_column, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.bootstrap import MODULE_SCHEMAS
from bus.dispatcher import count_outbox_rows, discover_outbox_tables
from bus.envelope import Envelope
from modules.observability.domain.consumer import (
    ALERT_SEVERITY_CRITICAL,
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
    AlertRow,
)
from modules.observability.domain.deeplinks import grafana_link, langfuse_link, sentry_link
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.domain.rollup import (
    ALERT_STATUS_OPEN,
    BREAKER_STATE_OPEN,
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    RollupPlan,
    RollupThresholds,
    plan_rollup_dates,
    ratio,
)
from modules.observability.rollup import RollupReport, RollupRunState, load_rollup_state, run_rollup
from modules.observability.schema.models import (
    observability_ai_cost_budget,
    observability_ai_job_spend,
    observability_ai_provider_health,
    observability_ai_usage_daily,
    observability_alert_events,
    observability_business_daily,
    observability_rollup_runs,
)

OBSERVABILITY_SCHEMA = "observability"

#: The two outcomes ``observability_ai_job_spend.status`` can hold - a closed
#: vocabulary the migration's CHECK constraint enforces, so a third state is a
#: migration rather than a silent value.
AI_JOB_SPEND_STATUS_COMPLETED = "completed"
AI_JOB_SPEND_STATUS_FAILED = "failed"

#: Default and ceiling of one page of the alert feed (api-standards §4: default
#: 25, max 100). The feed is paged rather than capped at one screen because the
#: operator page shows its most recent page and can page back through a long
#: incident.
DEFAULT_ALERT_PAGE_SIZE = 25
MAX_ALERT_PAGE_SIZE = 100

__all__ = [
    "AI_JOB_SPEND_STATUS_COMPLETED",
    "AI_JOB_SPEND_STATUS_FAILED",
    "DEFAULT_ALERT_PAGE_SIZE",
    "DEFAULT_WINDOW_DAYS",
    "MAX_ALERT_PAGE_SIZE",
    "OBSERVABILITY_SCHEMA",
    "ROLLUP_MODE_BACKFILL",
    "ROLLUP_MODE_DAILY",
    "AlertEntry",
    "AlertPage",
    "BreakerHealthRow",
    "BusinessCountView",
    "CostBudgetView",
    "CostSummary",
    "CostTrend",
    "CostTrendPoint",
    "Deeplinks",
    "DependencyHealth",
    "LatencyReport",
    "LatencyRow",
    "ObservabilityFacade",
    "OutboxHealthRow",
    "Overview",
    "ProviderQualityRow",
    "QualityReport",
    "RollupPlan",
    "RollupReport",
    "RollupRunState",
    "RollupThresholds",
    "SystemHealth",
    "UsageReport",
    "UsageRow",
    "accumulate_ai_usage",
    "accumulate_business_count",
    "load_rollup_state",
    "plan_rollup_dates",
    "query_alerts",
    "query_cost_summary",
    "query_cost_trend",
    "query_health",
    "query_latency",
    "query_overview",
    "query_quality",
    "query_usage",
    "record_ai_job_spend",
    "record_alert_event",
    "run_rollup",
    "window_for",
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


async def record_ai_job_spend(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    payload: AiJobCompletedUsagePayload | AiJobFailedUsagePayload,
) -> None:
    """Write ONE granular ``observability_ai_job_spend`` row for one finished AI job.

    B6 (#723). ``observability_ai_usage_daily`` answers "what did this scope
    spend" but has already discarded attribution by the time the day closes.
    This row is the granular source the per-patient and per-doctor numbers are
    computed FROM, so it is kept at one row per job rather than per scope.

    Runs in the same ``run_handler`` transaction as the ``consumed_events``
    ledger row and as :func:`accumulate_ai_usage`, so all three roll back
    together and a replayed ``event_id`` writes none of them.

    PHI-free by construction: the identity references on the payload are hashed
    through :func:`~modules.observability.domain.pseudonym.actor_key` before they
    are written, so the raw patient/doctor reference never lands in this schema
    (ADR-0025 D7). Nothing else on the payload is clinical - the transcript, the
    confidence score and the failure reason stay in ``intake``.

    A failed job records zero tokens and zero cost rather than a fabricated free
    call, mirroring what the daily aggregate does; the row's existence and its
    ``failed`` status are the record of the attempt.

    ``ai_job_ref`` is UNIQUE on the table, so this insert is also the enforcement
    of "one row per AI job": the outbox ledger already makes a redelivery of the
    same ``event_id`` a no-op, and a SECOND event about the same job - which no
    current producer emits, since every leg books a fresh job row - would fail
    the constraint instead of quietly doubling one patient's spend.
    """
    if isinstance(payload, AiJobCompletedUsagePayload):
        input_tokens = payload.input_tokens
        output_tokens = payload.output_tokens
        cost_paise = payload.cost_paise
        status = AI_JOB_SPEND_STATUS_COMPLETED
    else:
        input_tokens = 0
        output_tokens = 0
        cost_paise = 0
        status = AI_JOB_SPEND_STATUS_FAILED

    statement = insert(observability_ai_job_spend).values(
        usage_date=envelope.occurred_at.date(),
        ai_job_ref=payload.ai_job_id,
        intake_ref=payload.intake_id,
        patient_key=actor_key(ACTOR_KIND_PATIENT, payload.patient_id),
        doctor_key=(
            actor_key(ACTOR_KIND_DOCTOR, payload.doctor_id)
            if payload.doctor_id is not None
            else None
        ),
        provider=payload.provider,
        model=payload.model,
        task_type=payload.task_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_paise=cost_paise,
        status=status,
        trace_id=payload.trace_id,
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


# ------------------------------------------------------- operator read API (C1)
#
# The nine aggregates the operator observability routes serve (plan-phase14 §9.1),
# projected out of this schema's own tables. No cross-schema SQL: the ledger MOD-013
# accumulated is the system of record (ADR-0003), and a read never joins another
# module's storage to build it. The one exception is the ``/health`` outbox counts,
# which are read through the dispatcher's own sanctioned contract rather than with
# SQL of its own.


class CostBudgetView(BaseModel):
    """One ``(provider, model)`` budget scope: spend against the cap.

    Paise throughout (api-standards §3). ``remaining_paise`` floors at zero and
    ``utilization_pct`` is unbounded above 100, so an overspent scope still reads
    as one overspent scope rather than as a negative remainder.
    """

    provider: str
    model: str
    monthly_limit_paise: int
    alert_threshold_pct: int
    current_spend_paise: int
    billing_period_start: date | None
    billing_period_end: date | None
    remaining_paise: int
    utilization_pct: Decimal
    exhausted: bool


class CostSummary(BaseModel):
    """Spend across the current billing period, plus the per-scope breakdown.

    ``total_spend_paise`` is the sum over ``budgets`` - the whole bill. The cap is
    NOT: ``observability_ai_cost_budget`` holds one snapshotted row per scope, and
    the single bill-wide ``AI_MONTHLY_BUDGET_PAISE`` is written onto every one of
    them, so ``total_limit_paise`` is the cap itself rather than its sum across
    rows. The ``ai_budget`` alert is evaluated against exactly this pair, so the
    headline and the alert cannot disagree.

    ``period_start``/``period_end`` are the bounds the rows carry: the rollup stamps
    them on every snapshot and re-stamps a stale row's period when it resets a
    closed month, so they read as the period the figures belong to. An empty table
    answers zeroes with a ``None`` period, which is "nothing budgeted yet", not
    "spent nothing".
    """

    period_start: date | None
    period_end: date | None
    total_spend_paise: int
    total_limit_paise: int
    remaining_paise: int
    utilization_pct: Decimal
    exhausted: bool
    budgets: list[CostBudgetView]


class CostTrendPoint(BaseModel):
    """One day of the cost trend: what that day cost, and how many calls produced it."""

    usage_date: date
    calls: int
    cost_paise: int


class CostTrend(BaseModel):
    """The daily cost series over the requested window, oldest day first.

    ``days``/``from_date``/``to_date`` echo the window the series was read for, so
    a chart can label its own axis and a caller can see which days are gaps (days
    with no AI job carry no point at all).
    """

    days: int
    from_date: date
    to_date: date
    points: list[CostTrendPoint]


class UsageRow(BaseModel):
    """One ``(provider, model, task_type)`` scope's usage over the window."""

    provider: str
    model: str
    task_type: str
    calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    input_tokens: int
    output_tokens: int
    cost_paise: int


class UsageReport(BaseModel):
    """Calls and tokens by provider and task over the window, plus the totals."""

    days: int
    from_date: date
    to_date: date
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_paise: int
    rows: list[UsageRow]


class ProviderQualityRow(BaseModel):
    """One provider's rolled-up health: the success rate and the breaker state.

    ``success_rate`` is ``None`` for a provider the rollup has no traffic sample
    for, which is not the same as a provider failing every call.
    """

    provider: str
    sample_count: int
    success_rate: Decimal | None
    breaker_state: str


class QualityReport(BaseModel):
    """Output quality over the window, plus the per-provider health breakdown.

    ``success_rate`` is over all calls; ``low_confidence_rate`` is over the
    completions, since a failed job returns no result to have been unconfident
    about. Both are ``None`` rather than zero when their denominator is empty.
    """

    days: int
    from_date: date
    to_date: date
    total_calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    low_confidence_count: int
    success_rate: Decimal | None
    low_confidence_rate: Decimal | None
    providers: list[ProviderQualityRow]


#: Default window of the windowed reads, in days (plan-phase14 §9.1: ``days=30``).
#: The single definition: the routes import it rather than repeating the number,
#: and the facade methods take the window the caller resolved.
DEFAULT_WINDOW_DAYS = 30

#: Two-decimal scale of the percentage figures (``60.00``, not ``60``).
_PCT_QUANTUM = Decimal("0.01")


def window_for(days: int, *, today: date | None = None) -> tuple[date, date]:
    """The inclusive ``[from_date, to_date]`` window of ``days`` UTC days ending today.

    ``days`` counts the days themselves, so ``window_for(1)`` is today alone and the
    default 30-day window covers today plus the 29 days before it. A non-positive
    span is refused rather than silently inverted into a future-dated window.
    """
    if days < 1:
        raise ValueError("days must be positive")
    to_date = today if today is not None else datetime.now(UTC).date()
    return to_date - timedelta(days=days - 1), to_date


def _window_days(from_date: date, to_date: date) -> int:
    """The span of an inclusive window in days - the ``days`` a view echoes back."""
    return (to_date - from_date).days + 1


def _utilization_pct(spend_paise: int, limit_paise: int) -> Decimal:
    """``spend`` as a percentage of ``limit`` at 2dp; an uncapped total reads ``0.00``."""
    if limit_paise <= 0:
        return Decimal("0.00")
    return (Decimal(spend_paise) / Decimal(limit_paise) * 100).quantize(
        _PCT_QUANTUM, rounding=ROUND_HALF_UP
    )


def _budget_view(row: RowMapping) -> CostBudgetView:
    """One ``observability_ai_cost_budget`` row as the cost route answers it.

    The derived columns mirror :class:`~modules.observability.domain.rollup.BudgetSnapshot`
    but are computed here because a read has to survive two shapes the snapshot
    cannot: an uncapped scope (``monthly_limit_paise`` defaults to ``0``) and a row
    the rollup has not stamped a period onto yet (both period columns are nullable).
    An uncapped scope reports ``0.00`` rather than dividing by zero, and is never
    "exhausted" - there is no cap to exhaust.

    ``remaining_paise`` and ``utilization_pct`` are this scope's SHARE against the
    bill-wide cap every row carries (see :func:`query_cost_summary`) - the same
    reading ``BudgetSnapshot`` takes, not a second budget of its own.
    """
    limit = int(row["monthly_limit_paise"])
    spend = int(row["current_spend_paise"])
    capped = limit > 0
    return CostBudgetView(
        provider=row["provider"],
        model=row["model"],
        monthly_limit_paise=limit,
        alert_threshold_pct=int(row["alert_threshold_pct"]),
        current_spend_paise=spend,
        billing_period_start=row["billing_period_start"],
        billing_period_end=row["billing_period_end"],
        remaining_paise=max(0, limit - spend),
        utilization_pct=_utilization_pct(spend, limit),
        exhausted=capped and spend >= limit,
    )


async def query_cost_summary(connection: AsyncConnection) -> CostSummary:
    """Read spend against the budgeted period (``/cost``).

    Spend is the SUM over the rows - each row is one ``(provider, model)`` scope's
    snapshotted month-to-date share (B5a ``build_budget_snapshot``) - so the
    headline is the whole bill, the same total the ``ai_budget`` alert is evaluated
    against.

    The cap is NOT that sum. ``AI_MONTHLY_BUDGET_PAISE`` is ONE cap for the whole
    bill and the rollup writes that same figure onto every scope row, so summing
    ``monthly_limit_paise`` would multiply the budget by the number of scopes and
    understate utilisation. The total cap is the ``max`` over the rows - the one
    cap, and the conservative reading if two rows ever disagree. Every other column
    is derived from that pair, so the headline and the alert cannot disagree.
    """
    rows = await connection.execute(
        select(
            observability_ai_cost_budget.c.provider,
            observability_ai_cost_budget.c.model,
            observability_ai_cost_budget.c.monthly_limit_paise,
            observability_ai_cost_budget.c.alert_threshold_pct,
            observability_ai_cost_budget.c.current_spend_paise,
            observability_ai_cost_budget.c.billing_period_start,
            observability_ai_cost_budget.c.billing_period_end,
        ).order_by(
            observability_ai_cost_budget.c.provider,
            observability_ai_cost_budget.c.model,
        )
    )
    budgets = [_budget_view(row) for row in rows.mappings()]
    total_spend = sum(budget.current_spend_paise for budget in budgets)
    total_limit = max((budget.monthly_limit_paise for budget in budgets), default=0)
    return CostSummary(
        period_start=_earliest_period_start(budgets),
        period_end=_latest_period_end(budgets),
        total_spend_paise=total_spend,
        total_limit_paise=total_limit,
        remaining_paise=max(0, total_limit - total_spend),
        utilization_pct=_utilization_pct(total_spend, total_limit),
        exhausted=total_limit > 0 and total_spend >= total_limit,
        budgets=budgets,
    )


def _earliest_period_start(budgets: Sequence[CostBudgetView]) -> date | None:
    """The oldest period start the budget rows carry, or ``None`` before the rollup."""
    starts = [budget.billing_period_start for budget in budgets if budget.billing_period_start]
    return min(starts) if starts else None


def _latest_period_end(budgets: Sequence[CostBudgetView]) -> date | None:
    """The newest period end the budget rows carry, or ``None`` before the rollup."""
    ends = [budget.billing_period_end for budget in budgets if budget.billing_period_end]
    return max(ends) if ends else None


async def query_cost_trend(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> CostTrend:
    """Read the daily cost series across the window (``/cost/trend``).

    ``observability_ai_usage_daily`` holds one row per
    ``(usage_date, provider, model, task_type)``, so the trend is that table summed
    per day - the daily figure, not the running total. Days with no AI job are
    simply absent from the series; a caller charts them as the gaps they are rather
    than as a spend of zero the rollup never recorded.
    """
    usage = observability_ai_usage_daily
    rows = await connection.execute(
        select(
            usage.c.usage_date,
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.cost_paise), 0).label("cost_paise"),
        )
        .where(usage.c.usage_date.between(from_date, to_date))
        .group_by(usage.c.usage_date)
        .order_by(usage.c.usage_date)
    )
    return CostTrend(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        points=[
            CostTrendPoint(
                usage_date=row["usage_date"],
                calls=int(row["calls"]),
                cost_paise=int(row["cost_paise"]),
            )
            for row in rows.mappings()
        ],
    )


async def query_usage(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> UsageReport:
    """Read calls and tokens per provider/task scope across the window (``/usage``).

    Grouping by ``(provider, model, task_type)`` - the table's own scope key - turns
    the per-day rows into one lifetime-per-window row each, which is the "calls and
    tokens by provider/task" split the plan asks for.
    """
    usage = observability_ai_usage_daily
    rows = await connection.execute(
        select(
            usage.c.provider,
            usage.c.model,
            usage.c.task_type,
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.success_count), 0).label("success_count"),
            func.coalesce(func.sum(usage.c.failure_count), 0).label("failure_count"),
            func.coalesce(func.sum(usage.c.timeout_count), 0).label("timeout_count"),
            func.coalesce(func.sum(usage.c.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(usage.c.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(usage.c.cost_paise), 0).label("cost_paise"),
        )
        .where(usage.c.usage_date.between(from_date, to_date))
        .group_by(usage.c.provider, usage.c.model, usage.c.task_type)
        .order_by(usage.c.provider, usage.c.model, usage.c.task_type)
    )
    scopes = [
        UsageRow(
            provider=row["provider"],
            model=row["model"],
            task_type=row["task_type"],
            calls=int(row["calls"]),
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            timeout_count=int(row["timeout_count"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cost_paise=int(row["cost_paise"]),
        )
        for row in rows.mappings()
    ]
    return UsageReport(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        total_calls=sum(scope.calls for scope in scopes),
        total_input_tokens=sum(scope.input_tokens for scope in scopes),
        total_output_tokens=sum(scope.output_tokens for scope in scopes),
        total_cost_paise=sum(scope.cost_paise for scope in scopes),
        rows=scopes,
    )


async def query_quality(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> QualityReport:
    """Read the quality rates across the window plus per-provider health (``/quality``).

    Two reads of this schema, never one joined query: the window totals come from
    ``observability_ai_usage_daily`` (``success_rate`` over ALL calls,
    ``low_confidence_rate`` over the completions that produced an answer - a failed
    job returns no result to have been unconfident about), while the per-provider
    breakdown is the B5a-computed ``observability_ai_provider_health`` row, whose
    percentiles and breaker state are already rolled up per provider.
    """
    usage = observability_ai_usage_daily
    totals = await connection.execute(
        select(
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.success_count), 0).label("success_count"),
            func.coalesce(func.sum(usage.c.failure_count), 0).label("failure_count"),
            func.coalesce(func.sum(usage.c.timeout_count), 0).label("timeout_count"),
            func.coalesce(func.sum(usage.c.low_confidence_count), 0).label("low_confidence_count"),
        ).where(usage.c.usage_date.between(from_date, to_date))
    )
    row = totals.mappings().one()
    calls = int(row["calls"])
    success_count = int(row["success_count"])
    low_confidence_count = int(row["low_confidence_count"])

    health = observability_ai_provider_health
    providers = await connection.execute(
        select(
            health.c.provider,
            health.c.sample_count,
            health.c.success_rate,
            health.c.breaker_state,
        ).order_by(health.c.provider)
    )
    return QualityReport(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        total_calls=calls,
        success_count=success_count,
        failure_count=int(row["failure_count"]),
        timeout_count=int(row["timeout_count"]),
        low_confidence_count=low_confidence_count,
        success_rate=ratio(success_count, calls),
        low_confidence_rate=ratio(low_confidence_count, success_count),
        providers=[
            ProviderQualityRow(
                provider=entry["provider"],
                sample_count=int(entry["sample_count"]),
                success_rate=entry["success_rate"],
                breaker_state=entry["breaker_state"],
            )
            for entry in providers.mappings()
        ],
    )


class Overview(BaseModel):
    """The operator landing page's headline KPIs (plan-phase14 §9.1).

    One number per question the dashboard opens with: is the bill on plan, is the
    AI working, is anything broken, and is the telemetry itself fresh. Each is
    read from the aggregate that already owns it, so the overview can never
    disagree with the route behind the tile - ``spend_paise`` and friends ARE
    ``/cost``'s headline, and the rates are ``/quality``'s.

    The windowed figures cover ``[from_date, to_date]``; spend and the alert
    counts do not, because the budget is a billing-period figure and an alert
    stays open until a later pass resolves it.
    """

    days: int
    from_date: date
    to_date: date
    total_calls: int
    success_count: int
    success_rate: Decimal | None
    low_confidence_count: int
    low_confidence_rate: Decimal | None
    #: The slowest provider's p95 across the last rolled day - the worst AI
    #: latency the ledger knows of, which is the figure an SLO is written
    #: against. ``None`` until a provider has a rolled latency sample.
    p95_duration_ms: Decimal | None
    spend_paise: int
    budget_paise: int
    budget_utilization_pct: Decimal
    budget_exhausted: bool
    open_alerts: int
    critical_open_alerts: int
    open_breakers: int
    #: The registry-driven business event counts the B4b consumer accumulated over
    #: the window (plan-phase14 §7.2), newest store first by key. The last thing
    #: an operator page shows above the fold: not just that the system is healthy,
    #: but what it actually did today.
    business_counts: list[BusinessCountView]
    #: The newest day the nightly rollup covered - how stale the percentiles,
    #: the budget snapshot and the health rows above can be.
    last_rolled_date: date | None


class LatencyRow(BaseModel):
    """One provider's rolled latency distribution.

    Percentiles come from ``observability_ai_provider_health``, which the nightly
    rollup recomputes over the whole recorded history it can see and stamps with
    the window it ranked. They are therefore "as of the last roll", not "over a
    requested window" - ``window_start``/``window_end`` say which.

    Each percentile is ``None`` for a provider with no timed completion, which is
    not the same as a provider that responded instantly.
    """

    provider: str
    sample_count: int
    p50_duration_ms: Decimal | None
    p95_duration_ms: Decimal | None
    p99_duration_ms: Decimal | None
    window_start: datetime | None
    window_end: datetime | None


class LatencyReport(BaseModel):
    """Per-provider p50/p95/p99, plus how fresh those percentiles are.

    No ``days`` param on purpose: the percentiles are a rolling snapshot the
    rollup writes, not a windowed aggregate the read can re-derive, so a window
    here would describe a period the numbers were never computed over. The HTTP
    server's own route latency rides the OTel ``caresetu.http.server.duration``
    histogram and is read from the OTLP backend, not from Postgres (see
    plan-phase14 §5).
    """

    last_rolled_date: date | None
    providers: list[LatencyRow]


class DependencyHealth(BaseModel):
    """One dependency's state as this read observed it.

    Two statuses, both reachable, and neither overstated. ``up`` means the read
    itself reached the dependency (the database probe) or the deployment has it
    configured (the cache, which is deliberately never dialled per request - see
    :func:`query_health`). ``disabled`` means the deployment switched it off,
    which for the optional Redis cache is a configuration choice with a SQL
    fallback rather than an outage.

    ``latency_ms`` is the round trip this read measured and is present only when
    one was taken; ``detail`` carries the human-readable reason for a
    ``disabled`` dependency.
    """

    name: str
    status: str
    latency_ms: Decimal | None = None
    detail: str | None = None


class OutboxHealthRow(BaseModel):
    """One outbox table's undelivered and terminally-failed rows.

    Read through ``bus.dispatcher.count_outbox_rows``, never with SQL of this
    module's own: ADR-0003 names the dispatcher the only sanctioned cross-schema
    reader, and the outbox row contract is its to define. ``backlog`` is
    ``pending`` plus ``inflight`` - rows still owed a delivery attempt.

    ``table_schema`` is spelled out rather than named ``schema``, which would
    shadow the pydantic field BaseModel itself carries.
    """

    table_schema: str
    table: str
    pending: int
    inflight: int
    dead_letter: int
    backlog: int


class BreakerHealthRow(BaseModel):
    """One AI provider's recorded breaker state (the rollup observes, never trips)."""

    provider: str
    breaker_state: str


class BusinessCountView(BaseModel):
    """One registry-driven business event's count over the window.

    ``metric_key`` is the ``BUSINESS_EVENT_METRICS`` key the B4b consumer
    accumulates (plan-phase14 §7.2); ``count`` is the ``value.count`` the B4a-style
    increment maintains in ``observability_business_daily``.

    A key with no event in the window is ABSENT rather than zero: the store holds
    what was counted, and inventing a row per registered key would make a metric
    nobody fires look like one that fired and did nothing.
    """

    metric_key: str
    count: int


class SystemHealth(BaseModel):
    """Dependency reachability plus the outbox and circuit-breaker state.

    Everything an operator needs to answer "is something stuck?" without leaving
    the page: whether the stores answered, how much is queued for delivery, how
    many deliveries are terminally failed, and which providers the rollup last
    saw below its success-rate floor.

    A database this read cannot reach is not reported here - with no database
    there are no counts to report either, so the request fails through the app's
    own error path rather than answering 200 with an empty body that an external
    monitor would read as healthy.
    """

    dependencies: list[DependencyHealth]
    outbox: list[OutboxHealthRow]
    outbox_backlog: int
    dead_letter_rows: int
    breakers: list[BreakerHealthRow]
    open_breakers: int


class AlertEntry(BaseModel):
    """One ``observability_alert_events`` row as the operator feed answers it.

    ``payload`` is the PHI-free map the producers wrote (ids and figures only -
    ``error-handling-observability.md`` §5); the read passes it through rather
    than reshaping it, so an alert reads the same in the feed as it does in the
    database.
    """

    id: UUID
    severity: str
    kind: str
    title: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    acked_by: int | None
    acked_at: datetime | None


class AlertPage(BaseModel):
    """One page of the alert feed, newest first, plus the full match count.

    Paged as api-standards §4 asks, with ``total_count`` counting every matching
    row rather than the page alone, so a client can tell a full page from the end
    of the feed. Ties on ``created_at`` are broken by ``id``, which keeps a page
    stable while a pass is still inserting.
    """

    alerts: list[AlertEntry]
    total_count: int


class Deeplinks(BaseModel):
    """The operator page's outbound vendor links (plan-phase14 §9.1).

    Every key is optional and independently ``None``: a deployment with Sentry but
    no Grafana answers with a Sentry link and an absent Grafana one. The route
    never fails over an unconfigured vendor - see
    :mod:`modules.observability.domain.deeplinks`.
    """

    grafana: str | None = None
    sentry: str | None = None
    langfuse: str | None = None


# ------------------------------------------------------- operator read API (C1b)
#
# The five reads C1b adds. Same rules as C1a above: this module's own tables,
# the dispatcher's sanctioned outbox contract where a cross-schema figure is
# wanted, and vendor URLs derived by pure functions over Settings.


def _elapsed_ms(started: float) -> Decimal:
    """Milliseconds since a :func:`time.perf_counter` reading, at 2dp."""
    return Decimal(f"{(perf_counter() - started) * 1000:.2f}")


async def _last_rolled_date(connection: AsyncConnection) -> date | None:
    """The newest day the nightly rollup covered, or ``None`` before its first pass.

    The freshness marker both ``/overview`` and ``/latency`` carry: every rolled
    figure the operator sees - percentiles, budget snapshots, provider health -
    is only as current as this date.
    """
    result = await connection.execute(
        select(func.max(observability_rollup_runs.c.rollup_date)).select_from(
            observability_rollup_runs
        )
    )
    value = result.scalar()
    return value if isinstance(value, date) else None


async def query_overview(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> Overview:
    """Read the headline KPIs (``/overview``).

    Deliberately composed from the aggregates that already own each figure rather
    than re-derived in one wide query: the spend is ``query_cost_summary``'s
    summary verbatim (so the overview's budget tile is the same arithmetic the
    ``ai_budget`` alert is raised against), the rates are the same windowed sums
    ``/quality`` reads, and the freshness marker is the rollup ledger's newest
    date. One extra read of the budget rows is cheaper than a second copy of the
    cap-versus-spend rule that could drift from the first.
    """
    usage = observability_ai_usage_daily
    totals = await connection.execute(
        select(
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.success_count), 0).label("success_count"),
            func.coalesce(func.sum(usage.c.low_confidence_count), 0).label("low_confidence_count"),
        ).where(usage.c.usage_date.between(from_date, to_date))
    )
    row = totals.mappings().one()
    calls = int(row["calls"])
    success_count = int(row["success_count"])
    low_confidence_count = int(row["low_confidence_count"])

    alerts = observability_alert_events
    open_alerts = await connection.execute(
        select(
            func.count().label("open_alerts"),
            func.count()
            .filter(alerts.c.severity == ALERT_SEVERITY_CRITICAL)
            .label("critical_open_alerts"),
        ).where(alerts.c.status == ALERT_STATUS_OPEN)
    )
    alert_row = open_alerts.mappings().one()

    health = observability_ai_provider_health
    provider_health = await connection.execute(
        select(
            func.max(health.c.p95_duration_ms).label("p95_duration_ms"),
            func.count()
            .filter(health.c.breaker_state == BREAKER_STATE_OPEN)
            .label("open_breakers"),
        )
    )
    health_row = provider_health.mappings().one()

    business = observability_business_daily
    business_rows = await connection.execute(
        select(
            business.c.metric_key,
            cast(business.c.value.op("->>")("count"), Integer).label("count"),
        )
        .where(business.c.metric_date.between(from_date, to_date))
        .order_by(business.c.metric_key)
    )

    last_rolled = await _last_rolled_date(connection)
    cost = await query_cost_summary(connection)
    return Overview(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        total_calls=calls,
        success_count=success_count,
        success_rate=ratio(success_count, calls),
        low_confidence_count=low_confidence_count,
        low_confidence_rate=ratio(low_confidence_count, success_count),
        p95_duration_ms=health_row["p95_duration_ms"],
        spend_paise=cost.total_spend_paise,
        budget_paise=cost.total_limit_paise,
        budget_utilization_pct=cost.utilization_pct,
        budget_exhausted=cost.exhausted,
        open_alerts=int(alert_row["open_alerts"]),
        critical_open_alerts=int(alert_row["critical_open_alerts"]),
        open_breakers=int(health_row["open_breakers"]),
        business_counts=[
            BusinessCountView(metric_key=entry["metric_key"], count=int(entry["count"]))
            for entry in business_rows.mappings()
        ],
        last_rolled_date=last_rolled,
    )


async def query_latency(connection: AsyncConnection) -> LatencyReport:
    """Read each provider's rolled p50/p95/p99 (``/latency``).

    The percentiles are the B5a rollup's own ``observability_ai_provider_health``
    rows, read verbatim with the window it ranked them over - recomputing them
    here would rank a different sample (this request's window) than the one the
    alert thresholds were evaluated against.

    Providers the rollup has no latency sample for are absent entirely: there is
    no row to project, and inventing a zero-percentile provider would read as a
    provider that answered instantly.
    """
    health = observability_ai_provider_health
    rows = await connection.execute(
        select(
            health.c.provider,
            health.c.sample_count,
            health.c.p50_duration_ms,
            health.c.p95_duration_ms,
            health.c.p99_duration_ms,
            health.c.window_start,
            health.c.window_end,
        ).order_by(health.c.provider)
    )
    return LatencyReport(
        last_rolled_date=await _last_rolled_date(connection),
        providers=[
            LatencyRow(
                provider=entry["provider"],
                sample_count=int(entry["sample_count"]),
                p50_duration_ms=entry["p50_duration_ms"],
                p95_duration_ms=entry["p95_duration_ms"],
                p99_duration_ms=entry["p99_duration_ms"],
                window_start=entry["window_start"],
                window_end=entry["window_end"],
            )
            for entry in rows.mappings()
        ],
    )


async def query_health(connection: AsyncConnection, *, cache_configured: bool) -> SystemHealth:
    """Read dependency state plus outbox and breaker state (``/health``).

    The database entry is a timed round trip on this very connection, so the
    figure an operator reads is the one this request experienced. The cache entry
    is resolved from Settings and never dialled: the plan's Redis is optional
    with a SQL fallback, so the route must not spend a connection timeout
    discovering that on every dashboard load - an unconfigured cache is reported
    ``disabled``, the configuration choice it is.

    Outbox counts come from ``bus.dispatcher``: ADR-0003 names the dispatcher the
    only sanctioned cross-schema reader, so the SELECT stays there and this layer
    only reshapes its rows. Every ``*_outbox`` table of every module schema is
    counted, because a stuck outbox is stuck regardless of which module published
    it.
    """
    started = perf_counter()
    await connection.execute(select(literal(1)))
    dependencies = [
        DependencyHealth(name="database", status="up", latency_ms=_elapsed_ms(started)),
        DependencyHealth(
            name="cache",
            status="up" if cache_configured else "disabled",
            detail=None if cache_configured else "REDIS_URL is unset; reads fall back to SQL",
        ),
    ]

    counts = await count_outbox_rows(
        connection, await discover_outbox_tables(connection, MODULE_SCHEMAS)
    )
    outbox = [
        OutboxHealthRow(
            table_schema=row.table.schema,
            table=row.table.table_name,
            pending=row.pending,
            inflight=row.inflight,
            dead_letter=row.dead_letter,
            backlog=row.backlog,
        )
        for row in counts
    ]

    health = observability_ai_provider_health
    breaker_rows = await connection.execute(
        select(health.c.provider, health.c.breaker_state).order_by(health.c.provider)
    )
    breakers = [
        BreakerHealthRow(provider=entry["provider"], breaker_state=entry["breaker_state"])
        for entry in breaker_rows.mappings()
    ]
    return SystemHealth(
        dependencies=dependencies,
        outbox=outbox,
        outbox_backlog=sum(row.backlog for row in outbox),
        dead_letter_rows=sum(row.dead_letter for row in outbox),
        breakers=breakers,
        open_breakers=sum(1 for row in breakers if row.breaker_state == BREAKER_STATE_OPEN),
    )


async def query_alerts(
    connection: AsyncConnection, *, page: int, page_size: int, status: str | None = None
) -> AlertPage:
    """Read one page of the alert feed, newest first (``/alerts``).

    Unfiltered, this is the operator's standing-problems view; ``status`` narrows
    it to what is still open or to what a later pass has resolved. The feed is
    ordered newest first and carries only PHI-free columns, so it can be rendered
    inline on the operator page (plan-phase14 §9.2).

    ``total_count`` is a second aggregate over the same filter rather than
    ``len(alerts)``, so a caller can page back through a long feed without paging
    to find out there is more.
    """
    filter_clause = (
        (observability_alert_events.c.status == status) if status is not None else true()
    )
    counted = await connection.execute(
        select(func.count()).select_from(observability_alert_events).where(filter_clause)
    )
    total = int(counted.scalar_one())

    columns = (
        observability_alert_events.c.id,
        observability_alert_events.c.severity,
        observability_alert_events.c.kind,
        observability_alert_events.c.title,
        observability_alert_events.c.payload,
        observability_alert_events.c.status,
        observability_alert_events.c.created_at,
        observability_alert_events.c.acked_by,
        observability_alert_events.c.acked_at,
    )
    rows = await connection.execute(
        select(*columns)
        .where(filter_clause)
        .order_by(
            observability_alert_events.c.created_at.desc(),
            observability_alert_events.c.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    alerts = [
        AlertEntry(
            id=entry["id"],
            severity=entry["severity"],
            kind=entry["kind"],
            title=entry["title"],
            payload=entry["payload"],
            status=entry["status"],
            created_at=entry["created_at"],
            acked_by=entry["acked_by"],
            acked_at=entry["acked_at"],
        )
        for entry in rows.mappings()
    ]
    return AlertPage(alerts=alerts, total_count=total)


def build_deeplinks(
    *,
    grafana_url: str | None = None,
    sentry_dsn: str | None = None,
    langfuse_host: str | None = None,
    langfuse_public_key: str | None = None,
) -> Deeplinks:
    """Derive the vendor deep links from Settings (``/deeplinks``).

    No database and no network: the read is a projection of configuration, so it
    cannot fail because a vendor is absent or unreachable. Each key is derived
    independently, which is what lets a Sentry-only deployment answer with a
    Sentry link and nothing else.
    """
    return Deeplinks(
        grafana=grafana_link(grafana_url),
        sentry=sentry_link(sentry_dsn),
        langfuse=langfuse_link(langfuse_host, langfuse_public_key),
    )


class ObservabilityFacade:
    """Typed public facade for observability.

    The B4 public surface carries the effects the event consumers run. The C1
    (``#706``/``#707``) read seam joins it: ``get_cost_summary``,
    ``get_cost_trend``, ``get_usage``, ``get_quality``, ``get_overview``,
    ``get_latency``, ``get_health``, ``get_alerts`` and ``get_deeplinks`` are what
    the operator observability routes call. Each opens the one settled engine
    connection and delegates its aggregate to the module helper, so routes hold
    no SQL and the reads stay in this module.

    The windowed reads take ``days`` and an optional ``today`` so the caller - or a
    test - can pin the window; the routes own the default
    (:data:`DEFAULT_WINDOW_DAYS`) and production leaves ``today`` unset, so the
    facade reads the current UTC day.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_cost_summary(self) -> CostSummary:
        """Read this billing period's spend against the budget (no window)."""
        async with self._engine.begin() as connection:
            return await query_cost_summary(connection)

    async def get_cost_trend(self, *, days: int, today: date | None = None) -> CostTrend:
        """Read the daily cost series over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_cost_trend(connection, from_date=from_date, to_date=to_date)

    async def get_usage(self, *, days: int, today: date | None = None) -> UsageReport:
        """Read calls and tokens per provider/task scope over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_usage(connection, from_date=from_date, to_date=to_date)

    async def get_quality(self, *, days: int, today: date | None = None) -> QualityReport:
        """Read the quality rates and per-provider health over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_quality(connection, from_date=from_date, to_date=to_date)

    async def get_overview(self, *, days: int, today: date | None = None) -> Overview:
        """Read the headline KPIs over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_overview(connection, from_date=from_date, to_date=to_date)

    async def get_latency(self) -> LatencyReport:
        """Read the rolled per-provider percentiles (no window - see ``LatencyReport``)."""
        async with self._engine.begin() as connection:
            return await query_latency(connection)

    async def get_health(self, *, cache_configured: bool) -> SystemHealth:
        """Read dependency reachability plus outbox and breaker state."""
        async with self._engine.begin() as connection:
            return await query_health(connection, cache_configured=cache_configured)

    async def get_alerts(
        self, *, page: int, page_size: int, status: str | None = None
    ) -> AlertPage:
        """Read one page of the alert feed, optionally narrowed by status."""
        async with self._engine.begin() as connection:
            return await query_alerts(connection, page=page, page_size=page_size, status=status)

    def get_deeplinks(
        self,
        *,
        grafana_url: str | None = None,
        sentry_dsn: str | None = None,
        langfuse_host: str | None = None,
        langfuse_public_key: str | None = None,
    ) -> Deeplinks:
        """Derive the vendor deep links from the configured Settings.

        Synchronous: it reads configuration, never storage. It stays on the facade
        so the routes keep the one seam every other read goes through and the
        derivation has one home to be tested in.
        """
        return build_deeplinks(
            grafana_url=grafana_url,
            sentry_dsn=sentry_dsn,
            langfuse_host=langfuse_host,
            langfuse_public_key=langfuse_public_key,
        )
