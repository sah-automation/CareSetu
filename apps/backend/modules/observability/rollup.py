"""MOD-013: the nightly rollup adapter - load rows, decide, upsert.

B5a (#704, plan-phase14 §8). This is the only layer that touches the database:
it reads one date of ``observability_ai_usage_daily``, hands the values to the
pure functions in :mod:`modules.observability.domain.rollup`, and persists what
they decide -

* ``observability_ai_provider_health``: the recomputed p50/p95/p99, success rate
  and observed breaker state;
* ``observability_ai_cost_budget``: the month-to-date paise spend snapshot, with
  the calendar-month reset that clears a closed month's spend;
* ``observability_business_daily``: one generic-store row per registered metric;
* ``observability_alert_events``: the threshold alerts from the minimum alert set;
* ``observability_rollup_runs``: the run ledger (B5b #705) - one row per rolled
  day, written in the SAME transaction as the aggregates it describes, which is
  both the pass's idempotency key and the marker the next invocation plans from.

Two invariants carry over from the request path (ADR-0003, coding-standards §2):

* it reads only the ``observability`` schema plus the shared outbox table
  CONTRACT - never another module's domain tables. The budget spend comes from
  MOD-013's own ``observability_ai_usage_daily``, not from ``intake_ai_jobs``, so
  no cross-schema read is needed at all.
* it SNAPSHOTS spend, it never enforces it (PS-10, #408) - a breached budget
  raises an alert and nothing here blocks a call.

Alert writes are idempotent per ``(kind, scope)``: a nightly job that re-runs (or
a backfill that overlaps a nightly pass) raises one open alert per breached
threshold, and resolves it again once the threshold clears.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Table, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.bootstrap import MODULE_SCHEMAS
from bus.dispatcher import count_outbox_rows, discover_outbox_tables
from modules.observability.domain.consumer import AlertRow
from modules.observability.domain.rollup import (
    ALERT_STATUS_OPEN,
    ALERT_STATUS_RESOLVED,
    RESOLVABLE_ALERT_KINDS,
    ROLLUP_MODE_DAILY,
    BudgetSnapshot,
    OutboxTableHealth,
    ProviderHealth,
    ProviderUsage,
    RollupMetricValue,
    RollupThresholds,
    UsageScope,
    alert_key,
    alert_marker,
    budget_period_for,
    build_budget_snapshot,
    compute_provider_health,
    evaluate_budget_alerts,
    evaluate_outbox_health_alerts,
    evaluate_provider_health_alerts,
    evaluated_alert_keys,
    rollup_metrics_for,
)
from modules.observability.schema.models import (
    observability_ai_cost_budget,
    observability_ai_provider_health,
    observability_ai_usage_daily,
    observability_alert_events,
    observability_business_daily,
    observability_rollup_runs,
)

logger = logging.getLogger(__name__)


def _insert_alert(alert: AlertRow) -> Any:
    """The ``observability_alert_events`` insert for one alert row.

    The consumer's public effect write (``facade.record_alert_event``) states the
    same row, but the facade re-exports this module, so importing it back here
    would be circular. One private builder, two callers, no second table shape.
    """
    return insert(observability_alert_events).values(
        severity=alert.severity,
        kind=alert.kind,
        title=alert.title,
        payload=alert.payload,
    )


@dataclass(frozen=True)
class RollupReport:
    """What one rollup pass wrote - the nightly job's log line and its exit signal."""

    target_date: date
    providers: int
    health_rows: int
    metric_rows: int
    budget_snapshots: int
    alerts_raised: int
    alerts_resolved: int


@dataclass(frozen=True)
class _OpenAlert:
    """One open rollup alert, keyed by the ``(kind, scope)`` finding it records."""

    alert_id: UUID
    kind: str
    marker: dict[str, Any]


def _day_window(target_date: date) -> tuple[datetime, datetime]:
    """The half-open UTC ``[start, end)`` bounds of one calendar day."""
    start = datetime.combine(target_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


@dataclass(frozen=True)
class RollupRunState:
    """What the rollup has already covered - the only inputs the planner needs.

    ``last_rolled_date`` is the newest day on ``observability_rollup_runs``
    (``None`` before the first run, which is what selects the backfill branch).
    ``history_start`` is the oldest ``observability_ai_usage_daily`` date: MOD-013's
    own record of the AI-job history the consumer metered, so the first run sweeps
    all of it without reading ``intake_ai_jobs`` across the module boundary
    (ADR-0003).
    """

    last_rolled_date: date | None
    history_start: date | None


async def _load_rollup_run_state(connection: AsyncConnection, horizon: date) -> RollupRunState:
    """Read the last rolled day and the AI-job history floor from this schema.

    ``horizon`` bounds the ledger read to the days that can actually have been
    rolled. A row dated in the future - from a manual ``--date`` ahead of the clock,
    or a clock that moved back - is invisible to the planner, so it cannot wedge
    every later nightly pass by making the schedule look already-current.
    """
    ledger = observability_rollup_runs
    last_rolled = await connection.execute(
        select(func.max(ledger.c.rollup_date)).where(ledger.c.rollup_date <= horizon)
    )
    usage = observability_ai_usage_daily
    history_start = await connection.execute(select(func.min(usage.c.usage_date)))
    return RollupRunState(
        last_rolled_date=_scalar_date(last_rolled),
        history_start=_scalar_date(history_start),
    )


async def load_rollup_state(engine: AsyncEngine, horizon: date) -> RollupRunState:
    """The scheduler seam: report what the rollup has covered as of ``horizon``."""
    async with engine.connect() as connection:
        return await _load_rollup_run_state(connection, horizon)


def _scalar_date(result: Any) -> date | None:
    """The single ``DATE`` a scalar aggregate returned, or ``None`` over an empty table."""
    value = result.scalar()
    return value if isinstance(value, date) else None


def _reset_budget_period_statement(period_start: date, period_end: date) -> Any:
    """The one UPDATE that rolls ``observability_ai_cost_budget`` into a new month.

    A row whose ``billing_period_start`` predates the period - or carries no period
    at all, since the column is nullable - holds a closed month's spend, so its
    figure comes back to zero and it adopts the new period's bounds. Then the
    pass's snapshots overwrite the scopes that actually spent. Rows already inside
    the period are untouched, which is what makes the reset idempotent: a re-run of
    the same night matches no row.

    Expressed as SQLAlchemy expressions (never raw text) so it compiles for the
    dialect and can be asserted without a database. The NULL arm is explicit
    because ``billing_period_start < period_start`` is NULL-unsafe in SQL - a plain
    comparison silently skips those rows, which is how a row with no period would
    keep last month's spend forever.
    """
    table = observability_ai_cost_budget
    return (
        table.update()
        .where(
            or_(table.c.billing_period_start.is_(None), table.c.billing_period_start < period_start)
        )
        .values(
            billing_period_start=period_start,
            billing_period_end=period_end,
            current_spend_paise=0,
            updated_at=func.now(),
        )
    )


def _insert_rollup_run(
    target_date: date, mode: str, period_start: date, report: RollupReport
) -> Any:
    """The ``observability_rollup_runs`` upsert recording one completed pass.

    Conflict target is ``rollup_date``: re-running a date refreshes its row instead
    of stacking a second one, so the ledger stays one-row-per-day however often the
    scheduled job is retried.
    """
    return (
        insert(observability_rollup_runs)
        .values(
            rollup_date=target_date,
            mode=mode,
            billing_period_start=period_start,
            providers=report.providers,
            health_rows=report.health_rows,
            metric_rows=report.metric_rows,
            budget_snapshots=report.budget_snapshots,
            alerts_raised=report.alerts_raised,
            alerts_resolved=report.alerts_resolved,
        )
        .on_conflict_do_update(
            index_elements=["rollup_date"],
            set_={
                "mode": mode,
                "billing_period_start": period_start,
                "providers": report.providers,
                "health_rows": report.health_rows,
                "metric_rows": report.metric_rows,
                "budget_snapshots": report.budget_snapshots,
                "alerts_raised": report.alerts_raised,
                "alerts_resolved": report.alerts_resolved,
                "ran_at": func.now(),
            },
        )
    )


def _upsert_statement(table: Table, values: dict[str, Any], conflict_keys: Sequence[str]) -> Any:
    """An ``INSERT ... ON CONFLICT DO UPDATE`` refreshing every non-key column.

    Built from SQLAlchemy expressions rather than raw text so it compiles for the
    dialect and can be asserted without a database. The conflict keys keep their
    inserted value; everything else - including ``updated_at`` - is refreshed, so a
    re-run converges on the recomputed figure instead of accumulating.
    """
    set_: dict[str, Any] = {key: value for key, value in values.items() if key not in conflict_keys}
    set_["updated_at"] = func.now()
    return (
        insert(table)
        .values(**values)
        .on_conflict_do_update(index_elements=list(conflict_keys), set_=set_)
    )


# ------------------------------------------------------------------- the reads


async def _load_provider_usage(
    connection: AsyncConnection, target_date: date
) -> list[ProviderUsage]:
    """Load one date of ``observability_ai_usage_daily``, grouped by provider."""
    usage = observability_ai_usage_daily
    statement = (
        select(
            usage.c.provider,
            usage.c.model,
            usage.c.task_type,
            usage.c.calls,
            usage.c.success_count,
            usage.c.failure_count,
            usage.c.timeout_count,
            usage.c.cost_paise,
            usage.c.avg_duration_ms,
        )
        .where(usage.c.usage_date == target_date)
        .order_by(usage.c.provider, usage.c.model, usage.c.task_type)
    )
    rows = (await connection.execute(statement)).all()
    grouped: dict[str, list[UsageScope]] = {}
    for row in rows:
        grouped.setdefault(row.provider, []).append(
            UsageScope(
                model=row.model,
                task_type=row.task_type,
                calls=row.calls,
                success_count=row.success_count,
                failure_count=row.failure_count,
                timeout_count=row.timeout_count,
                cost_paise=row.cost_paise,
                avg_duration_ms=row.avg_duration_ms,
            )
        )
    return [
        ProviderUsage(provider=provider, scopes=tuple(scopes))
        for provider, scopes in grouped.items()
    ]


async def _load_previous_success_rates(
    connection: AsyncConnection,
) -> dict[str, Decimal | None]:
    """The success rate already recorded per provider, for the drop comparison."""
    table = observability_ai_provider_health
    rows = (await connection.execute(select(table.c.provider, table.c.success_rate))).all()
    return {row.provider: row.success_rate for row in rows}


async def _load_period_spend(
    connection: AsyncConnection, period_start: date, target_date: date
) -> dict[tuple[str, str], int]:
    """Month-to-date ``cost_paise`` per ``(provider, model)`` over MOD-013's own rows.

    Snapshots what MOD-013 itself metered, which is the same spend the
    ``BudgetMeter`` aggregates from ``intake_ai_jobs`` - read from inside this
    module's schema so no cross-schema query is needed (ADR-0003).
    """
    usage = observability_ai_usage_daily
    statement = (
        select(usage.c.provider, usage.c.model, func.coalesce(func.sum(usage.c.cost_paise), 0))
        .where(usage.c.usage_date >= period_start, usage.c.usage_date <= target_date)
        .group_by(usage.c.provider, usage.c.model)
    )
    rows = (await connection.execute(statement)).all()
    return {(row.provider, row.model): int(row[2]) for row in rows}


async def _load_budget_limits(
    connection: AsyncConnection,
) -> dict[tuple[str, str], tuple[int, int]]:
    """The ``(monthly_limit_paise, alert_threshold_pct)`` already stored per scope.

    A row an operator has retuned keeps its numbers; a scope with no row inherits
    the thresholds the pass was configured with.
    """
    table = observability_ai_cost_budget
    statement = select(
        table.c.provider,
        table.c.model,
        table.c.monthly_limit_paise,
        table.c.alert_threshold_pct,
    )
    rows = (await connection.execute(statement)).all()
    return {
        (row.provider, row.model): (row.monthly_limit_paise, row.alert_threshold_pct)
        for row in rows
    }


async def _load_outbox_health(
    connection: AsyncConnection, schemas: Sequence[str]
) -> list[OutboxTableHealth]:
    """Every discovered outbox table's row counts, mapped to the pure input type.

    The counting itself is ``bus.dispatcher.count_outbox_rows``: ADR-0003 names
    the dispatcher the only sanctioned cross-schema reader, so the SELECT stays
    there and this layer only reshapes its result into the domain's value type.
    """
    tables = await discover_outbox_tables(connection, schemas)
    counts = await count_outbox_rows(connection, tables)
    return [
        OutboxTableHealth(
            schema=row.table.schema,
            table=row.table.table_name,
            pending=row.pending,
            inflight=row.inflight,
            dead_letter=row.dead_letter,
        )
        for row in counts
    ]


# ----------------------------------------------------------------- the writes


async def _upsert_provider_health(connection: AsyncConnection, health: ProviderHealth) -> None:
    """Refresh one provider's rolling health row (one row per provider)."""
    values: dict[str, Any] = {
        "provider": health.provider,
        "window_start": health.window_start,
        "window_end": health.window_end,
        "sample_count": health.sample_count,
        "success_rate": health.success_rate,
        "p50_duration_ms": health.p50_duration_ms,
        "p95_duration_ms": health.p95_duration_ms,
        "p99_duration_ms": health.p99_duration_ms,
        "breaker_state": health.breaker_state,
    }
    statement = _upsert_statement(observability_ai_provider_health, values, ("provider",))
    await connection.execute(statement)


async def _upsert_business_metric(
    connection: AsyncConnection, target_date: date, metric: RollupMetricValue
) -> None:
    """Write one registry-produced metric into the generic ``business_daily`` store.

    The whole ``value`` is replaced rather than merged: the rollup owns every key
    it publishes, and a re-run must land on the recomputed figure rather than
    leave a stale one behind.
    """
    values: dict[str, Any] = {
        "metric_key": metric.metric_key,
        "metric_date": target_date,
        "value": metric.value,
    }
    statement = _upsert_statement(
        observability_business_daily, values, ("metric_key", "metric_date")
    )
    await connection.execute(statement)


async def _upsert_budget_snapshot(connection: AsyncConnection, snapshot: BudgetSnapshot) -> None:
    """Snapshot one ``(provider, model)`` budget row's spend for the billing period."""
    values: dict[str, Any] = {
        "provider": snapshot.provider,
        "model": snapshot.model,
        "monthly_limit_paise": snapshot.monthly_limit_paise,
        "alert_threshold_pct": snapshot.alert_threshold_pct,
        "current_spend_paise": snapshot.current_spend_paise,
        "billing_period_start": snapshot.billing_period_start,
        "billing_period_end": snapshot.billing_period_end,
    }
    statement = _upsert_statement(observability_ai_cost_budget, values, ("provider", "model"))
    await connection.execute(statement)


# ---------------------------------------------------------------- the alerts


async def _load_open_rollup_alerts(connection: AsyncConnection) -> list[_OpenAlert]:
    """Every open alert this rollup owns, with the marker it would re-raise under.

    Alerts whose payload carries no ``source`` marker are skipped - this pass
    only re-raises or resolves alerts it can identify by marker. Consumer alerts
    (``audit_tamper`` / ``ai_egress``) do carry a ``source`` and so are loaded
    here, but ``_apply_alerts`` never resolves them: their kinds are not in
    :data:`RESOLVABLE_ALERT_KINDS`, so an operator's view of them outlives the
    nightly pass.
    """
    table = observability_alert_events
    statement = select(table.c.id, table.c.kind, table.c.payload).where(
        table.c.status == ALERT_STATUS_OPEN
    )
    rows = (await connection.execute(statement)).all()
    alerts: list[_OpenAlert] = []
    for alert_id, kind, payload in rows:
        if not isinstance(payload, dict):
            continue
        marker = alert_marker(payload)
        if "source" not in marker:
            continue
        alerts.append(_OpenAlert(alert_id=alert_id, kind=kind, marker=marker))
    return alerts


async def _apply_alerts(
    connection: AsyncConnection,
    alerts: Sequence[AlertRow],
    evaluated: set[tuple[str, str]],
    open_alerts: Sequence[_OpenAlert],
) -> tuple[int, int]:
    """Insert the newly-raised alerts and resolve the rollup's stale open ones.

    Idempotent per ``(kind, scope)``: a nightly re-run (or an overlapping
    backfill pass) leaves one open alert per still-breached threshold instead of
    stacking a fresh row each night.

    An open alert is resolved only when THIS pass actually re-evaluated it -
    ``(kind, scope)`` in ``evaluated`` - and the condition has since cleared. A
    pass that saw no traffic for a provider therefore leaves that provider's
    standing ``breaker_open`` alert open rather than clearing it on absence of
    evidence. Kinds in :data:`RESOLVABLE_ALERT_KINDS` are standing conditions;
    the rest (``provider_health_drop``) describe a transition with no steady
    state, so they are raised and left for the operator's history.

    Returns ``(raised, resolved)``.
    """
    already_open = {
        (open_alert.kind, repr(sorted(open_alert.marker.items()))) for open_alert in open_alerts
    }
    raised = 0
    fired: set[tuple[str, str]] = set()
    for alert in alerts:
        key = alert_key(alert.kind, alert.payload)
        fired.add(key)
        if key in already_open:
            continue
        already_open.add(key)
        await connection.execute(_insert_alert(alert))
        raised += 1

    stale = [
        open_alert.alert_id
        for open_alert in open_alerts
        if open_alert.kind in RESOLVABLE_ALERT_KINDS
        and (open_alert.kind, repr(sorted(open_alert.marker.items()))) in evaluated
        and (open_alert.kind, repr(sorted(open_alert.marker.items()))) not in fired
    ]
    resolved = 0
    if stale:
        result = await connection.execute(
            observability_alert_events.update()
            .where(observability_alert_events.c.id.in_(stale))
            .values(status=ALERT_STATUS_RESOLVED)
        )
        resolved = int(result.rowcount or 0)
    return raised, resolved


# ------------------------------------------------------------- the invocation


async def run_rollup(
    engine: AsyncEngine,
    target_date: date,
    *,
    thresholds: RollupThresholds,
    mode: str = ROLLUP_MODE_DAILY,
    schemas: Sequence[str] = MODULE_SCHEMAS,
) -> RollupReport:
    """Run the whole rollup for ``target_date`` in one transaction.

    The invocation seam B5b's nightly GitHub Action calls: it takes an engine and
    a date, needs no web process awake, and is safe to re-run for the same date -
    every write is an upsert, so a retried job converges instead of double
    counting. Loads, decides, persists, and returns what it wrote.

    Every provider observed on ``target_date`` gets its health row plus one
    generic-store row per registered metric; every ``(provider, model)`` seen
    month-to-date gets a budget snapshot; the budget rows left over from a closed
    month are rolled into this period first; the minimum alert set is evaluated
    once per pass; and the whole thing ends by writing the ``mode``-tagged
    ``observability_rollup_runs`` row - in this SAME transaction, so the
    ``last_rolled`` marker can never advance past a pass that did not commit.
    """
    window_start, window_end = _day_window(target_date)
    period_start, period_end = budget_period_for(target_date)

    async with engine.begin() as connection:
        await connection.execute(_reset_budget_period_statement(period_start, period_end))
        usages = await _load_provider_usage(connection, target_date)
        previous_rates = await _load_previous_success_rates(connection)
        period_spend = await _load_period_spend(connection, period_start, target_date)
        stored_limits = await _load_budget_limits(connection)
        outbox_health = await _load_outbox_health(connection, schemas)

        alerts: list[AlertRow] = []
        health_rows = 0
        metric_rows = 0

        for usage in usages:
            health = compute_provider_health(
                usage.provider,
                window_start,
                window_end,
                usage,
                breaker_open_below=thresholds.breaker_open_success_rate,
            )
            await _upsert_provider_health(connection, health)
            health_rows += 1
            for metric in rollup_metrics_for(usage, health):
                await _upsert_business_metric(connection, target_date, metric)
                metric_rows += 1
            alerts.extend(
                evaluate_provider_health_alerts(
                    health, previous_rates.get(usage.provider), thresholds
                )
            )

        snapshots = 0
        for (provider, model), spend_paise in sorted(period_spend.items()):
            stored_limit, stored_pct = stored_limits.get(
                (provider, model),
                (thresholds.monthly_budget_paise, thresholds.budget_alert_threshold_pct),
            )
            await _upsert_budget_snapshot(
                connection,
                build_budget_snapshot(
                    provider,
                    model,
                    spend_paise,
                    monthly_limit_paise=stored_limit,
                    period_start=period_start,
                    period_end=period_end,
                    alert_threshold_pct=stored_pct,
                ),
            )
            snapshots += 1

        # The cap is ONE monthly budget compared against TOTAL spend, the same
        # figure BudgetMeter.meter() reports - so the alert is evaluated on the
        # month's aggregate, not once per (provider, model) row.
        alerts.extend(
            evaluate_budget_alerts(
                sum(period_spend.values()),
                thresholds,
                period_start=period_start,
                period_end=period_end,
            )
        )

        for table_health in outbox_health:
            alerts.extend(evaluate_outbox_health_alerts(table_health, thresholds))

        # What this pass could have re-raised. The resolve step closes an open
        # alert only inside this set, so absence of evidence never clears one.
        evaluated = evaluated_alert_keys(
            providers=[usage.provider for usage in usages],
            tables=[table_health.qualified_name for table_health in outbox_health],
        )

        raised, resolved = await _apply_alerts(
            connection,
            alerts,
            evaluated,
            await _load_open_rollup_alerts(connection),
        )

        report = RollupReport(
            target_date=target_date,
            providers=len(usages),
            health_rows=health_rows,
            metric_rows=metric_rows,
            budget_snapshots=snapshots,
            alerts_raised=raised,
            alerts_resolved=resolved,
        )
        await connection.execute(_insert_rollup_run(target_date, mode, period_start, report))

    logger.info(
        "rollup for %s (%s, period %s) refreshed %d provider health row(s), %d metric "
        "row(s) and %d budget snapshot(s); raised %d alert(s), resolved %d",
        report.target_date,
        mode,
        period_start,
        report.health_rows,
        report.metric_rows,
        report.budget_snapshots,
        report.alerts_raised,
        report.alerts_resolved,
    )
    return report
