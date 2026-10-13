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

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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
    ratio,
)
from modules.observability.rollup import RollupReport, RollupRunState, load_rollup_state, run_rollup
from modules.observability.schema.models import (
    observability_ai_cost_budget,
    observability_ai_provider_health,
    observability_ai_usage_daily,
    observability_alert_events,
    observability_business_daily,
)

OBSERVABILITY_SCHEMA = "observability"

__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "OBSERVABILITY_SCHEMA",
    "ROLLUP_MODE_BACKFILL",
    "ROLLUP_MODE_DAILY",
    "CostBudgetView",
    "CostSummary",
    "CostTrend",
    "CostTrendPoint",
    "ObservabilityFacade",
    "ProviderQualityRow",
    "QualityReport",
    "RollupPlan",
    "RollupReport",
    "RollupRunState",
    "RollupThresholds",
    "UsageReport",
    "UsageRow",
    "accumulate_ai_usage",
    "accumulate_business_count",
    "load_rollup_state",
    "plan_rollup_dates",
    "query_cost_summary",
    "query_cost_trend",
    "query_quality",
    "query_usage",
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


# ------------------------------------------------------- operator read API (C1a)
#
# The four aggregates the operator observability routes serve (plan-phase14 §9.1),
# projected out of this schema's own tables. No cross-schema SQL: the ledger MOD-013
# accumulated is the system of record (ADR-0003), and a read never joins another
# module's storage to build it.


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


class ObservabilityFacade:
    """Typed public facade for observability.

    The B4 public surface carries the effects the event consumers run. The C1a
    (``#706``) read seam joins it: ``get_cost_summary``, ``get_cost_trend``,
    ``get_usage``, and ``get_quality`` are what the operator observability routes
    call. Each opens the one settled engine connection and delegates its aggregate
    to the module helper, so routes hold no SQL and the reads stay in this module.

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
