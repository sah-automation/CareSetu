"""C1 #706/#707: the MOD-013 operator read facade's aggregation SQL.

Pins the documented read aggregates - spend against the budgeted period, the
daily cost trend, calls/tokens per provider/task scope, the quality rates, the
overview's headline KPIs, the rolled latency percentiles, request throughput with
its capture-liveness answer, dependency/outbox health, the alert feed and the
period-parameterised business spend read - against a mocked connection, so the window
that reaches SQL, the aggregation, and the derived arithmetic are all covered without
a live database (coding-standards §2: DB-free unit surface).

Every SELECT is against the ``observability`` schema only: the read facade never
crosses a module boundary (ADR-0003). The ``/health`` outbox counts are the one
exception and they reach another schema only through the dispatcher's own
sanctioned counting function, which is stubbed here and asserted in the round-trip
test against real outbox rows.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote

import pytest

from bus.dispatcher import OutboxRowCounts, OutboxTable
from modules.observability.domain.rollup import ALERT_STATUS_OPEN, ALERT_STATUS_RESOLVED
from modules.observability.facade import (
    BUSINESS_PERIOD_MONTH,
    BUSINESS_PERIOD_TODAY,
    BUSINESS_PERIOD_WEEK,
    DEFAULT_ERROR_WINDOW_MINUTES,
    ERROR_STATUS_VOCABULARY,
    BusinessCountView,
    ObservabilityFacade,
    build_deeplinks,
    error_status,
    period_window,
    query_alerts,
    query_business,
    query_cost_summary,
    query_cost_trend,
    query_error_feed,
    query_health,
    query_latency,
    query_overview,
    query_provider_board,
    query_quality,
    query_reliability,
    query_throughput,
    query_usage,
    window_for,
)

_TODAY = date(2026, 10, 12)
#: ``window_for(30)``: 30 inclusive UTC days ending today.
_FROM = date(2026, 9, 13)
_PERIOD_START = date(2026, 10, 1)
_PERIOD_END = date(2026, 10, 31)

#: The window ``get_throughput(minutes=60)`` resolves against a pinned instant. The
#: series is per minute, so these are instants and not dates.
_NOW = datetime(2026, 10, 14, 12, 34, 56, tzinfo=UTC)
_FROM_TS = datetime(2026, 10, 14, 11, 34, 56, tzinfo=UTC)


class _FakeMappings:
    """``Result.mappings()``: iterable rows, plus the aggregate ``.one()``/``.all()``."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def one(self) -> dict[str, object]:
        return self._rows[0]

    def all(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)

    def scalar(self) -> object:
        """The single value a bare ``MAX(date)`` aggregate returns."""
        return self._rows[0]["value"] if self._rows else None

    def scalar_one(self) -> object:
        """The single value a bare ``COUNT(*)`` aggregate returns."""
        return self._rows[0]["total"]


def _connection(*results: list[dict[str, object]]) -> AsyncMock:
    """A connection whose ``execute`` replays ``results`` in call order."""
    connection = AsyncMock()
    pending = [_FakeResult(rows) for rows in results]
    connection.execute = AsyncMock(side_effect=pending)
    return connection


def _engine(connection: AsyncMock) -> MagicMock:
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _compiled(connection: AsyncMock, call_index: int = 0) -> str:
    statement = connection.execute.await_args_list[call_index].args[0]
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


# ------------------------------------------------------------------ window


def test_window_for_is_days_inclusive_of_today() -> None:
    assert window_for(30, today=_TODAY) == (_FROM, _TODAY)
    assert window_for(1, today=_TODAY) == (_TODAY, _TODAY)
    assert window_for(7, today=_TODAY) == (date(2026, 10, 6), _TODAY)


def test_window_for_defaults_to_the_current_utc_day() -> None:
    assert window_for(30)[1] == datetime.now(UTC).date()


@pytest.mark.parametrize("days", [0, -1])
def test_window_for_refuses_a_non_positive_span(days: int) -> None:
    with pytest.raises(ValueError, match="days must be positive"):
        window_for(days, today=_TODAY)


# ------------------------------------------------------------------ cost


#: Budget scopes in the order the ``ORDER BY provider, model`` SELECT delivers them.
_BUDGET_ROWS: list[dict[str, object]] = [
    {
        "provider": "openai",
        "model": "gpt-4o",
        "monthly_limit_paise": 50_000,
        "alert_threshold_pct": 80,
        "current_spend_paise": 60_000,
        "billing_period_start": _PERIOD_START,
        "billing_period_end": _PERIOD_END,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "monthly_limit_paise": 100_000,
        "alert_threshold_pct": 80,
        "current_spend_paise": 30_000,
        "billing_period_start": _PERIOD_START,
        "billing_period_end": _PERIOD_END,
    },
]


async def test_cost_summary_sums_the_budgeted_period() -> None:
    summary = await query_cost_summary(_connection(_BUDGET_ROWS))

    assert summary.period_start == _PERIOD_START
    assert summary.period_end == _PERIOD_END
    assert summary.total_spend_paise == 90_000
    # Spend sums across scopes; the cap does NOT - the rollup writes the single
    # bill-wide cap onto every scope row, so summing it would double the budget.
    assert summary.total_limit_paise == 100_000
    assert summary.remaining_paise == 10_000
    assert summary.utilization_pct == Decimal("90.00")
    # 90k of the 100k cap is inside it, even though one scope alone breached its own.
    assert summary.exhausted is False
    assert [budget.model for budget in summary.budgets] == ["gpt-4o", "gpt-4o-mini"]


async def test_cost_summary_orders_scopes_by_provider_then_model() -> None:
    connection = _connection([_BUDGET_ROWS[1], _BUDGET_ROWS[0]])

    summary = await query_cost_summary(connection)

    assert (
        "ORDER BY observability.observability_ai_cost_budget.provider, "
        "observability.observability_ai_cost_budget.model" in _compiled(connection)
    )
    # The ORDER BY is what sorts them - the rows themselves pass through untouched.
    assert [budget.model for budget in summary.budgets] == ["gpt-4o-mini", "gpt-4o"]


async def test_cost_summary_flags_an_overspent_scope() -> None:
    summary = await query_cost_summary(_connection(_BUDGET_ROWS))

    over = summary.budgets[0]
    assert over.provider == "openai"
    assert over.model == "gpt-4o"
    assert over.current_spend_paise == 60_000
    assert over.remaining_paise == 0
    assert over.utilization_pct == Decimal("120.00")
    assert over.exhausted is True
    assert over.alert_threshold_pct == 80


async def test_cost_summary_reads_the_bill_wide_cap_not_the_sum_of_the_scopes() -> None:
    """One cap, one bill: a second scope must not buy a second budget.

    ``_BUDGET_ROWS`` carries the same real-world shape the B5a rollup writes - one
    ``AI_MONTHLY_BUDGET_PAISE`` figure repeated per scope - except that its two rows
    disagree, so the ``max`` the summary takes is the conservative one.
    """
    same_cap = [dict(row, monthly_limit_paise=100_000) for row in _BUDGET_ROWS]

    summary = await query_cost_summary(_connection(same_cap))

    assert {budget.monthly_limit_paise for budget in summary.budgets} == {100_000}
    assert summary.total_limit_paise == 100_000
    assert summary.utilization_pct == Decimal("90.00")


async def test_cost_summary_reads_an_uncapped_scope_without_dividing_by_zero() -> None:
    rows = [
        {
            "provider": "anthropic",
            "model": "claude-3-5-haiku",
            "monthly_limit_paise": 0,
            "alert_threshold_pct": 80,
            "current_spend_paise": 0,
            "billing_period_start": None,
            "billing_period_end": None,
        }
    ]

    summary = await query_cost_summary(_connection(rows))

    assert summary.period_start is None
    assert summary.period_end is None
    assert summary.utilization_pct == Decimal("0.00")
    assert summary.exhausted is False
    assert summary.budgets[0].utilization_pct == Decimal("0.00")
    assert summary.budgets[0].exhausted is False


async def test_cost_summary_with_no_budget_rows_is_zeroed_not_an_error() -> None:
    summary = await query_cost_summary(_connection([]))

    assert summary.total_spend_paise == 0
    assert summary.total_limit_paise == 0
    assert summary.remaining_paise == 0
    assert summary.utilization_pct == Decimal("0.00")
    assert summary.exhausted is False
    assert summary.budgets == []


async def test_facade_cost_summary_delegates_through_its_engine() -> None:
    facade = ObservabilityFacade(_engine(_connection(_BUDGET_ROWS)))

    summary = await facade.get_cost_summary()

    assert summary.total_spend_paise == 90_000
    assert summary.total_limit_paise == 100_000


# ------------------------------------------------------------------ trend


_TREND_ROWS: list[dict[str, object]] = [
    {"usage_date": date(2026, 9, 13), "calls": 2, "cost_paise": 30},
    {"usage_date": date(2026, 10, 11), "calls": 4, "cost_paise": 70},
    {"usage_date": date(2026, 10, 12), "calls": 6, "cost_paise": 110},
]


async def test_cost_trend_sums_each_day_chronologically() -> None:
    connection = _connection(_TREND_ROWS)

    trend = await query_cost_trend(connection, from_date=_FROM, to_date=_TODAY)

    assert trend.days == 30
    assert trend.from_date == _FROM
    assert trend.to_date == _TODAY
    assert [(point.usage_date, point.calls, point.cost_paise) for point in trend.points] == [
        (date(2026, 9, 13), 2, 30),
        (date(2026, 10, 11), 4, 70),
        (date(2026, 10, 12), 6, 110),
    ]


async def test_cost_trend_bounds_the_window_in_sql() -> None:
    connection = _connection(_TREND_ROWS)

    await query_cost_trend(connection, from_date=_FROM, to_date=_TODAY)

    sql = _compiled(connection)
    usage = "observability.observability_ai_usage_daily.usage_date"
    assert f"{usage} BETWEEN '2026-09-13' AND '2026-10-12'" in sql
    assert f"GROUP BY {usage}" in sql


async def test_cost_trend_with_no_traffic_is_an_empty_series() -> None:
    trend = await query_cost_trend(_connection([]), from_date=_FROM, to_date=_TODAY)

    assert trend.points == []


# ------------------------------------------------------------------ usage


#: Usage scopes in the order the ``ORDER BY provider, model, task_type`` SELECT
#: delivers them.
_USAGE_ROWS: list[dict[str, object]] = [
    {
        "provider": "anthropic",
        "model": "claude-3-5-haiku",
        "task_type": "triage",
        "calls": 1,
        "success_count": 0,
        "failure_count": 0,
        "timeout_count": 1,
        "input_tokens": 120,
        "output_tokens": 0,
        "cost_paise": 10,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "task_type": "summarize",
        "calls": 3,
        "success_count": 3,
        "failure_count": 0,
        "timeout_count": 0,
        "input_tokens": 400,
        "output_tokens": 90,
        "cost_paise": 90,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "task_type": "triage",
        "calls": 5,
        "success_count": 4,
        "failure_count": 1,
        "timeout_count": 0,
        "input_tokens": 1_000,
        "output_tokens": 200,
        "cost_paise": 250,
    },
]


async def test_usage_aggregates_calls_and_tokens_per_scope() -> None:
    connection = _connection(_USAGE_ROWS)

    usage = await query_usage(connection, from_date=_FROM, to_date=_TODAY)

    assert (usage.days, usage.from_date, usage.to_date) == (30, _FROM, _TODAY)
    assert usage.total_calls == 9
    assert usage.total_input_tokens == 1_520
    assert usage.total_output_tokens == 290
    assert usage.total_cost_paise == 350
    assert [
        (row.provider, row.model, row.task_type, row.calls, row.cost_paise) for row in usage.rows
    ] == [
        ("anthropic", "claude-3-5-haiku", "triage", 1, 10),
        ("openai", "gpt-4o-mini", "summarize", 3, 90),
        ("openai", "gpt-4o-mini", "triage", 5, 250),
    ]


async def test_usage_groups_by_provider_model_and_task() -> None:
    connection = _connection(_USAGE_ROWS)

    await query_usage(connection, from_date=_FROM, to_date=_TODAY)

    sql = _compiled(connection)
    usage = "observability.observability_ai_usage_daily"
    assert f"GROUP BY {usage}.provider, {usage}.model, {usage}.task_type" in sql
    assert f"{usage}.usage_date BETWEEN '2026-09-13' AND '2026-10-12'" in sql


async def test_usage_with_no_traffic_is_zeroed_not_an_error() -> None:
    usage = await query_usage(_connection([]), from_date=_FROM, to_date=_TODAY)

    assert usage.rows == []
    assert usage.total_calls == 0
    assert usage.total_cost_paise == 0


# ------------------------------------------------------------------ quality


_TOTALS_ROW: dict[str, object] = {
    "calls": 9,
    "success_count": 7,
    "failure_count": 1,
    "timeout_count": 1,
    "low_confidence_count": 2,
}

_HEALTH_ROWS: list[dict[str, object]] = [
    {
        "provider": "anthropic",
        "sample_count": 0,
        "success_rate": None,
        "breaker_state": "closed",
    },
    {
        "provider": "openai",
        "sample_count": 7,
        "success_rate": Decimal("0.7778"),
        "breaker_state": "closed",
    },
]


async def test_quality_reports_rates_over_the_window_and_the_provider_health() -> None:
    connection = _connection([_TOTALS_ROW], _HEALTH_ROWS)

    quality = await query_quality(connection, from_date=_FROM, to_date=_TODAY)

    assert (quality.days, quality.from_date, quality.to_date) == (30, _FROM, _TODAY)
    assert quality.total_calls == 9
    assert quality.success_count == 7
    assert quality.failure_count == 1
    assert quality.timeout_count == 1
    assert quality.low_confidence_count == 2
    # 7 of 9 calls succeeded; 2 of the 7 completions were low confidence.
    assert quality.success_rate == Decimal("0.7778")
    assert quality.low_confidence_rate == Decimal("0.2857")
    assert [(row.provider, row.success_rate, row.breaker_state) for row in quality.providers] == [
        ("anthropic", None, "closed"),
        ("openai", Decimal("0.7778"), "closed"),
    ]


async def test_quality_rates_are_none_without_traffic() -> None:
    empty: dict[str, object] = {
        "calls": 0,
        "success_count": 0,
        "failure_count": 0,
        "timeout_count": 0,
        "low_confidence_count": 0,
    }

    quality = await query_quality(_connection([empty], []), from_date=_FROM, to_date=_TODAY)

    assert quality.success_rate is None
    assert quality.low_confidence_rate is None
    assert quality.providers == []


_FROM_PATTERN = re.compile(r"FROM\s+(\S+)")


def _from_target(connection: AsyncMock, call_index: int = 0) -> str:
    """The single table a read's ``FROM`` names - never more than one, never a join."""
    match = _FROM_PATTERN.search(_compiled(connection, call_index))
    assert match is not None
    return match.group(1)


async def test_every_read_selects_from_the_observability_schema_only() -> None:
    """ADR-0003 module isolation: the read API joins no other module's storage."""
    cost = _connection(_BUDGET_ROWS)
    trend = _connection(_TREND_ROWS)
    usage = _connection(_USAGE_ROWS)
    quality = _connection([_TOTALS_ROW], _HEALTH_ROWS)
    overview = _connection(*_OVERVIEW_ROWS, _BUDGET_ROWS)
    latency = _connection(_LATENCY_ROWS, [{"value": _TODAY}])
    throughput = _connection([_MINUTE_12_34], [{"total": 2}], _ROUTE_ROWS)

    await query_cost_summary(cost)
    await query_cost_trend(trend, from_date=_FROM, to_date=_TODAY)
    await query_usage(usage, from_date=_FROM, to_date=_TODAY)
    await query_quality(quality, from_date=_FROM, to_date=_TODAY)
    await query_overview(overview, from_date=_FROM, to_date=_TODAY)
    await query_latency(latency)
    await query_throughput(throughput, from_ts=_FROM_TS, to_ts=_NOW)

    table = "observability.observability_ai_"
    assert _from_target(cost) == f"{table}cost_budget"
    assert _from_target(trend) == f"{table}usage_daily"
    assert _from_target(usage) == f"{table}usage_daily"
    # Quality is two reads of this schema, never one joined query.
    assert _from_target(quality, 0) == f"{table}usage_daily"
    assert _from_target(quality, 1) == f"{table}provider_health"
    # The overview composes the same per-aggregate reads, one table each.
    assert _from_target(overview, 0) == f"{table}usage_daily"
    assert _from_target(overview, 1) == "observability.observability_alert_events"
    assert _from_target(overview, 2) == f"{table}provider_health"
    assert _from_target(overview, 3) == "observability.observability_business_daily"
    assert _from_target(overview, 4) == "observability.observability_rollup_runs"
    assert _from_target(overview, 5) == f"{table}cost_budget"
    assert _from_target(latency, 0) == f"{table}provider_health"
    assert _from_target(latency, 1) == "observability.observability_rollup_runs"
    # Throughput is three reads of ONE counter table - the per-minute series, the
    # distinct-pair count and the busiest pairs - never a join against another module.
    counter = "observability.observability_http_minute"
    assert _from_target(throughput, 0) == counter
    assert _from_target(throughput, 2) == counter
    # The distinct-pair count wraps the same table in a subquery, so its FROM is the
    # derived table rather than the table itself.
    assert counter in _compiled(throughput, 1)
    assert "SELECT count(*) AS count_1 FROM (SELECT DISTINCT" in " ".join(
        _compiled(throughput, 1).split()
    )


@pytest.mark.parametrize(
    ("method", "connection_args"),
    [
        ("get_cost_trend", (_TREND_ROWS,)),
        ("get_usage", (_USAGE_ROWS,)),
        ("get_quality", ([_TOTALS_ROW], _HEALTH_ROWS)),
    ],
)
async def test_facade_windowed_reads_resolve_days_against_a_pinned_today(
    method: str, connection_args: tuple[list[dict[str, object]], ...]
) -> None:
    """The routes pass ``days``; the facade turns it into the window it queries."""
    facade = ObservabilityFacade(_engine(_connection(*connection_args)))

    view = await getattr(facade, method)(days=7, today=_TODAY)

    assert view.days == 7
    assert view.from_date == date(2026, 10, 6)
    assert view.to_date == _TODAY


# ---------------------------------------------------------------- overview


#: The six results ``query_overview`` reads, in the order it issues them: the
#: windowed usage sums, the open-alert counts, the provider-health aggregate, the
#: registry-driven business counts, the rollup ledger's newest date, then the
#: budget rows behind ``/cost``.
_OVERVIEW_ROWS: tuple[list[dict[str, object]], ...] = (
    [{"calls": 9, "success_count": 7, "low_confidence_count": 2}],
    [{"open_alerts": 4, "critical_open_alerts": 1}],
    [{"p95_duration_ms": Decimal("8400.00"), "open_breakers": 1}],
    [{"metric_key": "case.consult_complete", "count": 6}],
    [{"value": _TODAY}],
)


async def test_overview_reports_the_headline_figures() -> None:
    overview = await query_overview(
        _connection(*_OVERVIEW_ROWS, _BUDGET_ROWS), from_date=_FROM, to_date=_TODAY
    )

    assert (overview.days, overview.from_date, overview.to_date) == (30, _FROM, _TODAY)
    # 7 of 9 calls succeeded; 2 of the 7 completions were low confidence.
    assert overview.total_calls == 9
    assert overview.success_rate == Decimal("0.7778")
    assert overview.low_confidence_rate == Decimal("0.2857")
    assert overview.p95_duration_ms == Decimal("8400.00")
    assert overview.open_alerts == 4
    assert overview.critical_open_alerts == 1
    assert overview.open_breakers == 1
    assert overview.business_counts == [
        BusinessCountView(metric_key="case.consult_complete", count=6)
    ]
    assert overview.last_rolled_date == _TODAY


async def test_overview_spend_is_the_cost_reads_own_headline() -> None:
    """One budget arithmetic, so the tile and the alert can never disagree."""
    overview = await query_overview(
        _connection(*_OVERVIEW_ROWS, _BUDGET_ROWS), from_date=_FROM, to_date=_TODAY
    )

    cost = await query_cost_summary(_connection(_BUDGET_ROWS))
    assert overview.spend_paise == cost.total_spend_paise == 90_000
    assert overview.budget_paise == cost.total_limit_paise == 100_000
    assert overview.budget_utilization_pct == cost.utilization_pct
    assert overview.budget_exhausted == cost.exhausted


async def test_overview_rates_are_none_before_the_first_rollup() -> None:
    empty = (
        [{"calls": 0, "success_count": 0, "low_confidence_count": 0}],
        [{"open_alerts": 0, "critical_open_alerts": 0}],
        [{"p95_duration_ms": None, "open_breakers": 0}],
        [],
        [],
        [],
    )

    overview = await query_overview(_connection(*empty), from_date=_FROM, to_date=_TODAY)

    assert overview.success_rate is None
    assert overview.low_confidence_rate is None
    assert overview.p95_duration_ms is None
    assert overview.business_counts == []
    assert overview.last_rolled_date is None
    assert overview.spend_paise == 0
    assert overview.budget_paise == 0
    assert overview.budget_utilization_pct == Decimal("0.00")


async def test_overview_windowed_reads_resolve_days_against_a_pinned_today() -> None:
    facade = ObservabilityFacade(_engine(_connection(*_OVERVIEW_ROWS, _BUDGET_ROWS)))

    overview = await facade.get_overview(days=7, today=_TODAY)

    assert (overview.days, overview.from_date, overview.to_date) == (
        7,
        date(2026, 10, 6),
        _TODAY,
    )


# ----------------------------------------------------------------- latency


_LATENCY_ROWS: list[dict[str, object]] = [
    {
        "provider": "openai",
        "sample_count": 8,
        "p50_duration_ms": Decimal("1200.00"),
        "p95_duration_ms": Decimal("8400.00"),
        "p99_duration_ms": Decimal("15100.00"),
        "window_start": datetime(2026, 10, 12, tzinfo=UTC),
        "window_end": datetime(2026, 10, 13, tzinfo=UTC),
    }
]


async def test_latency_projects_the_rolled_percentiles_with_their_window() -> None:
    report = await query_latency(_connection(_LATENCY_ROWS, [{"value": _TODAY}]))

    assert report.last_rolled_date == _TODAY
    assert len(report.providers) == 1
    row = report.providers[0]
    assert (row.provider, row.sample_count) == ("openai", 8)
    assert row.p50_duration_ms == Decimal("1200.00")
    assert row.p95_duration_ms == Decimal("8400.00")
    assert row.p99_duration_ms == Decimal("15100.00")
    assert row.window_start == datetime(2026, 10, 12, tzinfo=UTC)
    assert row.window_end == datetime(2026, 10, 13, tzinfo=UTC)


async def test_latency_is_empty_before_the_first_rollup() -> None:
    report = await query_latency(_connection([], []))

    assert report.last_rolled_date is None
    assert report.providers == []


async def test_latency_keeps_an_unsampled_providers_null_percentiles() -> None:
    """No timed completion is absent evidence, not an instant response."""
    unsampled = [{**_LATENCY_ROWS[0], "sample_count": 0, "p50_duration_ms": None}]

    report = await query_latency(_connection(unsampled, [{"value": _TODAY}]))

    assert report.providers[0].sample_count == 0
    assert report.providers[0].p50_duration_ms is None


# ------------------------------------------------- provider board (B9 #728)


_BOARD_ROWS: list[dict[str, object]] = [
    {
        "provider": "anthropic",
        "sample_count": 1,
        "success_rate": Decimal("0.5000"),
        "timeout_count": 1,
        "rate_limit_count": 0,
        "p50_duration_ms": Decimal("900.00"),
        "p95_duration_ms": Decimal("1500.00"),
        "p99_duration_ms": Decimal("1800.00"),
        "breaker_state": "open",
        "last_error": "ConnectError",
        "window_start": datetime(2026, 10, 12, tzinfo=UTC),
        "window_end": datetime(2026, 10, 13, tzinfo=UTC),
    },
    {
        "provider": "openai",
        "sample_count": 8,
        "success_rate": Decimal("0.8750"),
        "timeout_count": 0,
        "rate_limit_count": 2,
        "p50_duration_ms": Decimal("1200.00"),
        "p95_duration_ms": Decimal("8400.00"),
        "p99_duration_ms": Decimal("15100.00"),
        "breaker_state": "closed",
        "last_error": "rate_limited",
        "window_start": datetime(2026, 10, 12, tzinfo=UTC),
        "window_end": datetime(2026, 10, 13, tzinfo=UTC),
    },
    {
        "provider": "together-ai",
        "sample_count": 0,
        "success_rate": None,
        "timeout_count": 0,
        "rate_limit_count": 0,
        "p50_duration_ms": None,
        "p95_duration_ms": None,
        "p99_duration_ms": None,
        "breaker_state": "closed",
        "last_error": None,
        "window_start": None,
        "window_end": None,
    },
]


async def test_the_board_derives_a_status_per_provider_from_the_stored_counters() -> None:
    """#717 story 37: triage without reading numbers, from ONE table read."""
    report = await query_provider_board(_connection(_BOARD_ROWS, [{"value": _TODAY}]))

    assert report.last_rolled_date == _TODAY
    assert [(row.provider, row.status) for row in report.providers] == [
        ("anthropic", "down"),
        ("openai", "degraded"),
        ("together-ai", "healthy"),
    ]


async def test_the_board_carries_every_figure_the_triage_needs() -> None:
    """Rate limits, timeouts, the rate, the three percentiles, the breaker, the error."""
    report = await query_provider_board(_connection(_BOARD_ROWS, [{"value": _TODAY}]))

    row = next(entry for entry in report.providers if entry.provider == "openai")
    assert row.success_rate == Decimal("0.8750")
    assert row.sample_count == 8
    assert row.timeout_count == 0
    assert row.rate_limit_count == 2
    assert (row.p50_duration_ms, row.p95_duration_ms, row.p99_duration_ms) == (
        Decimal("1200.00"),
        Decimal("8400.00"),
        Decimal("15100.00"),
    )
    assert row.breaker_state == "closed"
    assert row.last_error == "rate_limited"
    assert row.window_start == datetime(2026, 10, 12, tzinfo=UTC)


async def test_the_board_is_empty_before_the_first_rollup_rather_than_all_healthy() -> None:
    """A fabricated row would read as a provider answering normally."""
    report = await query_provider_board(_connection([], []))

    assert report.providers == []
    assert report.last_rolled_date is None


async def test_the_board_reads_only_the_observability_schema() -> None:
    """No cross-module read is introduced by the board (#717 out-of-scope list)."""
    connection = _connection(_BOARD_ROWS, [{"value": _TODAY}])

    await query_provider_board(connection)

    assert _from_target(connection, 0) == "observability.observability_ai_provider_health"
    assert _from_target(connection, 1) == "observability.observability_rollup_runs"
    compiled = _compiled(connection, 0)
    assert "intake." not in compiled
    assert "last_error" in compiled and "rate_limit_count" in compiled


# -------------------------------------------------------------- throughput (B9 #727)
#
# The three reads ``query_throughput`` issues, in order: the per-minute series, the
# count of distinct route/method pairs in the window, then the busiest of those
# pairs. ``_connection`` replays them in that order.

_MINUTE_12_33: dict[str, object] = {
    "minute_ts": datetime(2026, 10, 14, 12, 33, tzinfo=UTC),
    "requests": 4,
    "errors": 0,
}
_MINUTE_12_34: dict[str, object] = {
    "minute_ts": datetime(2026, 10, 14, 12, 34, tzinfo=UTC),
    "requests": 10,
    "errors": 3,
}
_ROUTE_ROWS: list[dict[str, object]] = [
    {
        "route_template": "/v1/cases/{case_id}/entries",
        "method": "POST",
        "requests": 12,
        "errors": 3,
    },
    {
        "route_template": "/health",
        "method": "GET",
        "requests": 2,
        "errors": 0,
    },
]


def _throughput(
    minutes: list[dict[str, object]],
    routes: list[dict[str, object]] = _ROUTE_ROWS,
    routes_total: int = 2,
) -> AsyncMock:
    return _connection(minutes, [{"total": routes_total}], routes)


async def test_throughput_sums_the_window_and_reports_the_rate() -> None:
    report = await query_throughput(
        _throughput([_MINUTE_12_33, _MINUTE_12_34]), from_ts=_FROM_TS, to_ts=_NOW
    )

    assert report.minutes == 60
    assert (report.from_ts, report.to_ts) == (_FROM_TS, _NOW)
    assert (report.requests, report.errors) == (14, 3)
    # The stored 5xx numerator over the stored denominator - 3 of 14.
    assert report.error_rate == Decimal("0.2143")
    # 14 requests spread over the whole hour, not over the two busy minutes.
    assert report.requests_per_minute == Decimal("0.23")


async def test_throughput_keeps_the_per_minute_series_in_order() -> None:
    """A spike is only visible if the minutes keep their order and stay separate."""
    report = await query_throughput(
        _throughput([_MINUTE_12_33, _MINUTE_12_34]), from_ts=_FROM_TS, to_ts=_NOW
    )

    assert [(point.minute_ts, point.requests, point.errors) for point in report.points] == [
        (datetime(2026, 10, 14, 12, 33, tzinfo=UTC), 4, 0),
        (datetime(2026, 10, 14, 12, 34, tzinfo=UTC), 10, 3),
    ]
    assert report.points[0].error_rate == Decimal("0.0000")
    assert report.points[1].error_rate == Decimal("0.3000")


async def test_throughput_leaves_quiet_minutes_absent_rather_than_zero() -> None:
    """A zero-filled minute is indistinguishable from a counter that stopped."""
    report = await query_throughput(_throughput([_MINUTE_12_34]), from_ts=_FROM_TS, to_ts=_NOW)

    assert [point.minute_ts.minute for point in report.points] == [34]


async def test_throughput_reports_the_busiest_routes_with_their_own_rate() -> None:
    report = await query_throughput(_throughput([]), from_ts=_FROM_TS, to_ts=_NOW)

    assert [
        (row.route_template, row.method, row.requests, row.error_rate) for row in report.routes
    ] == [
        ("/v1/cases/{case_id}/entries", "POST", 12, Decimal("0.2500")),
        ("/health", "GET", 2, Decimal("0.0000")),
    ]
    assert report.routes_total == 2


async def test_throughput_reports_the_busy_route_total_even_when_the_list_is_capped() -> None:
    """A truncated breakdown that does not say so reads as the whole truth."""
    report = await query_throughput(
        _throughput([], routes=_ROUTE_ROWS[:1], routes_total=214), from_ts=_FROM_TS, to_ts=_NOW
    )

    assert len(report.routes) == 1
    assert report.routes_total == 214


async def test_throughput_bounds_the_window_in_sql_on_the_minute_index() -> None:
    """A wide window must be narrowed by the index, not by dragging the table in."""
    connection = _throughput([_MINUTE_12_34])
    await query_throughput(connection, from_ts=_FROM_TS, to_ts=_NOW)

    assert "minute_ts >=" in _compiled(connection, 0)
    assert "minute_ts <" in _compiled(connection, 0)


async def test_throughput_with_nothing_recorded_reports_no_capture_rather_than_a_clean_window() -> (
    None
):
    """#727: the whole point of the read - an empty feed is not a healthy system.

    ``error_rate`` and ``requests_per_minute`` are ``None`` rather than ``0.0000``,
    because ``None`` says "nothing was measured" and ``0`` says "nothing failed",
    and only one of those is a fact about the platform.
    """
    report = await query_throughput(
        _throughput([], routes=[], routes_total=0), from_ts=_FROM_TS, to_ts=_NOW
    )

    assert report.requests == 0
    assert report.errors == 0
    assert report.error_rate is None
    assert report.requests_per_minute is None
    assert report.points == []
    assert report.routes == []
    assert report.routes_total == 0
    assert report.capture.capturing is False
    assert report.capture.requests_recorded == 0
    assert report.capture.last_recorded_at is None


async def test_throughput_reports_capture_liveness_when_traffic_was_recorded() -> None:
    """The other side of the same distinction: requests seen, and none of them failed."""
    report = await query_throughput(
        _throughput(
            [_MINUTE_12_33],
            routes=[{"route_template": "/health", "method": "GET", "requests": 4, "errors": 0}],
        ),
        from_ts=_FROM_TS,
        to_ts=_NOW,
    )

    assert report.error_rate == Decimal("0.0000")
    assert report.capture.capturing is True
    assert report.capture.requests_recorded == 4
    assert report.capture.last_recorded_at == datetime(2026, 10, 14, 12, 33, tzinfo=UTC)


async def test_throughput_keeps_an_empty_denominator_null_in_a_single_point() -> None:
    """A minute row with no requests is a stored zero, and its rate is unknown."""
    report = await query_throughput(
        _throughput([{**_MINUTE_12_34, "requests": 0, "errors": 0}]), from_ts=_FROM_TS, to_ts=_NOW
    )

    assert report.points[0].error_rate is None


async def test_the_throughput_window_is_half_open_and_resolves_against_a_pinned_now() -> None:
    """``to_ts`` is an instant, not a minute: rounding it down would hide the live one."""
    facade = ObservabilityFacade(_engine(_throughput([_MINUTE_12_34])))

    view = await facade.get_throughput(minutes=60, now=_NOW)

    assert view.minutes == 60
    assert view.to_ts == _NOW
    assert view.from_ts == _FROM_TS


async def test_the_throughput_window_floors_at_whole_minutes() -> None:
    """``now`` carries seconds, and a reported span that ticks every second is unusable."""
    facade = ObservabilityFacade(_engine(_throughput([])))

    view = await facade.get_throughput(
        minutes=60, now=datetime(2026, 10, 14, 12, 34, 30, tzinfo=UTC)
    )

    assert view.minutes == 60


@pytest.mark.parametrize("minutes", [0, -1])
async def test_the_throughput_window_refuses_a_non_positive_span(minutes: int) -> None:
    facade = ObservabilityFacade(_engine(_throughput([])))

    with pytest.raises(ValueError, match="minutes must be positive"):
        await facade.get_throughput(minutes=minutes, now=_NOW)


# ------------------------------------------------------------------ health

_OUTBOX_COUNTS = (
    OutboxRowCounts(
        table=OutboxTable(schema="iam", table_name="iam_outbox"),
        pending=7,
        inflight=2,
        dead_letter=1,
    ),
    OutboxRowCounts(
        table=OutboxTable(schema="intake", table_name="intake_outbox"),
        pending=0,
        inflight=0,
        dead_letter=0,
    ),
)

_BREAKER_ROWS: list[dict[str, object]] = [
    {"provider": "anthropic", "breaker_state": "open"},
    {"provider": "openai", "breaker_state": "closed"},
]


def _stub_dispatcher(
    monkeypatch: pytest.MonkeyPatch, counts: tuple[OutboxRowCounts, ...] = _OUTBOX_COUNTS
) -> None:
    """Stub the dispatcher's two sanctioned outbox reads at the facade's seam."""

    async def discover(connection: object, schemas: object) -> tuple[OutboxTable, ...]:
        return tuple(row.table for row in counts)

    async def count(
        connection: object, tables: tuple[OutboxTable, ...]
    ) -> tuple[OutboxRowCounts, ...]:
        return counts

    monkeypatch.setattr("modules.observability.facade.discover_outbox_tables", discover)
    monkeypatch.setattr("modules.observability.facade.count_outbox_rows", count)


async def test_health_reports_dependencies_outbox_and_breakers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dispatcher(monkeypatch)
    connection = _connection([], _BREAKER_ROWS)

    health = await query_health(connection, cache_configured=False)

    database = next(entry for entry in health.dependencies if entry.name == "database")
    assert database.status == "up"
    assert database.latency_ms is not None and database.latency_ms >= 0
    cache = next(entry for entry in health.dependencies if entry.name == "cache")
    assert cache.status == "disabled"
    assert cache.latency_ms is None
    # Backlog is pending + inflight across every module's outbox; dead letters sum.
    assert health.outbox_backlog == 9
    assert health.dead_letter_rows == 1
    assert [(row.table_schema, row.table, row.backlog) for row in health.outbox] == [
        ("iam", "iam_outbox", 9),
        ("intake", "intake_outbox", 0),
    ]
    assert health.open_breakers == 1
    assert [(row.provider, row.breaker_state) for row in health.breakers] == [
        ("anthropic", "open"),
        ("openai", "closed"),
    ]


async def test_health_reports_a_configured_cache_as_up_not_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dispatcher(monkeypatch)

    health = await query_health(_connection([], _BREAKER_ROWS), cache_configured=True)

    cache = next(entry for entry in health.dependencies if entry.name == "cache")
    assert cache.status == "up"
    assert cache.detail is None


async def test_health_facade_reads_the_cache_flag_the_caller_resolved() -> None:
    facade = ObservabilityFacade(_engine(_connection([], [], _BREAKER_ROWS)))

    health = await facade.get_health(cache_configured=True)

    assert next(entry for entry in health.dependencies if entry.name == "cache").status == "up"


# -------------------------------------------------------------- reliability

_RELIABILITY_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

_QUEUE_ROWS: list[dict[str, object]] = [
    {
        "queue": "structure",
        "depth": 3,
        # 40 minutes old - a stalled queue, which is the figure that leads.
        "oldest_enqueued_at": _RELIABILITY_NOW - timedelta(minutes=40),
    },
    {
        "queue": "transcribe",
        "depth": 1,
        "oldest_enqueued_at": _RELIABILITY_NOW - timedelta(seconds=5),
    },
]


async def test_reliability_reports_depth_and_age_per_queue_and_the_outbox_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dispatcher(monkeypatch)
    connection = _connection(_QUEUE_ROWS, [{"total": 2}])

    report = await query_reliability(connection, minutes=60, now=_RELIABILITY_NOW, grafana_url=None)

    assert [(row.queue, row.depth, row.oldest_age_s) for row in report.queues] == [
        ("structure", 3, 2400),
        ("transcribe", 1, 5),
    ]
    assert report.queue_depth == 4
    # The headline age is the OLDEST across the queues, not an average of them:
    # averaging would halve a forty-minute stall behind a fresh transcribe.
    assert report.oldest_queued_age_s == 2400
    # The per-outbox breakdown comes from the SAME figures /health serves, so the
    # two reads cannot disagree - and it is a breakdown, not a total, so a stuck
    # module is identifiable instead of averaged against five healthy ones.
    assert [(row.table_schema, row.backlog) for row in report.outbox] == [("iam", 9), ("intake", 0)]
    assert report.outbox_backlog == 9
    assert report.dead_letter_rows == 1


async def test_reliability_reports_recent_activity_and_links_concurrency_rather_than_storing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dispatcher(monkeypatch)
    connection = _connection(_QUEUE_ROWS, [{"total": 2}])

    report = await query_reliability(
        connection, minutes=60, now=_RELIABILITY_NOW, grafana_url="https://grafana.example.com/"
    )

    assert report.recent_active_actors == 2
    assert report.activity_window_minutes == 60
    # True concurrency is NOT a field on this read - it is a link to the tracing
    # backend, because a number that changes every millisecond cannot be stored in
    # Postgres and an approximation beside the real one would be read as the figure.
    assert not hasattr(report, "concurrency")
    assert report.concurrency_grafana_link is not None
    assert report.concurrency_grafana_link.startswith("https://grafana.example.com/explore?left=")
    assert "caresetu.http.server.inflight" in unquote(report.concurrency_grafana_link)


async def test_reliability_answers_an_empty_pipeline_without_inventing_an_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dispatcher(monkeypatch)
    connection = _connection([], [{"total": 0}])

    report = await query_reliability(connection, minutes=60, now=_RELIABILITY_NOW, grafana_url=None)

    assert report.queues == []
    assert report.queue_depth == 0
    assert report.oldest_queued_age_s is None
    assert report.recent_active_actors == 0
    # No Grafana configured is an ABSENT link, never a broken one.
    assert report.concurrency_grafana_link is None


async def test_reliability_facade_resolves_its_window_against_the_pinned_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dispatcher(monkeypatch)
    facade = ObservabilityFacade(_engine(_connection(_QUEUE_ROWS, [{"total": 1}])))

    report = await facade.get_reliability(minutes=15, now=_RELIABILITY_NOW, grafana_url=None)

    assert report.activity_window_minutes == 15
    assert report.oldest_queued_age_s == 2400


@pytest.mark.parametrize("minutes", [0, -1])
async def test_the_reliability_window_refuses_a_non_positive_span(
    minutes: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_dispatcher(monkeypatch)
    facade = ObservabilityFacade(_engine(_connection(_QUEUE_ROWS, [{"total": 1}])))

    with pytest.raises(ValueError, match="minutes must be positive"):
        await facade.get_reliability(minutes=minutes, now=_RELIABILITY_NOW, grafana_url=None)


# ------------------------------------------------------------------ alerts


_ALERT_ROWS: list[dict[str, object]] = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "severity": "critical",
        "kind": "breaker_open",
        "title": "AI provider breaker open for anthropic",
        "payload": {"source": "rollup", "provider": "anthropic"},
        "status": "open",
        "created_at": datetime(2026, 10, 12, 3, 0, tzinfo=UTC),
        "acked_by": None,
        "acked_at": None,
    }
]


async def test_alerts_pass_the_row_through_phi_free() -> None:
    page = await query_alerts(_connection([{"total": 1}], _ALERT_ROWS), page=1, page_size=25)

    assert page.total_count == 1
    entry = page.alerts[0]
    assert entry.kind == "breaker_open"
    assert entry.severity == "critical"
    assert entry.payload == {"source": "rollup", "provider": "anthropic"}
    assert entry.acked_by is None


async def test_alerts_are_newest_first_with_a_stable_tiebreak() -> None:
    connection = _connection([{"total": 1}], _ALERT_ROWS)

    await query_alerts(connection, page=1, page_size=10)

    sql = _compiled(connection, 1)
    assert re.search(r"ORDER BY\s+observability\.observability_alert_events\.created_at DESC", sql)
    assert re.search(r"observability\.observability_alert_events\.id DESC", sql)
    assert "LIMIT" in sql


async def test_alerts_page_offsets_past_the_rows_already_read() -> None:
    connection = _connection([{"total": 30}], _ALERT_ROWS)

    await query_alerts(connection, page=3, page_size=10)

    assert "OFFSET 20" in _compiled(connection, 1)


async def test_alerts_narrow_to_a_status_when_one_is_given() -> None:
    connection = _connection([{"total": 1}], _ALERT_ROWS)

    await query_alerts(connection, page=1, page_size=10, status="open")

    # Both the count and the page carry the filter, so total_count is the filtered total.
    assert "WHERE observability.observability_alert_events.status" in _compiled(connection, 0)
    assert "WHERE observability.observability_alert_events.status" in _compiled(connection, 1)


async def test_alerts_are_empty_before_any_finding() -> None:
    page = await query_alerts(_connection([{"total": 0}], []), page=1, page_size=25)

    assert page.total_count == 0
    assert page.alerts == []


# ------------------------------------------------------------------ errors


#: The instant the feed's open/resolved split is decided against, and a failure
#: five minutes before it (inside the default hour) and three hours before it
#: (outside). Two arms of one judgement, so a test can show the boundary is the
#: window rather than a stored column.
_ERROR_NOW = datetime(2026, 10, 14, 12, 34, 56, tzinfo=UTC)


def _error_row(
    fingerprint: str, *, route_template: str, minutes_ago: int, occurrences: int
) -> dict[str, object]:
    """One collapsed error row as the capture left it, placed ``minutes_ago`` back."""
    seen = _ERROR_NOW - timedelta(minutes=minutes_ago)
    return {
        "fingerprint": fingerprint,
        "route_template": route_template,
        "method": "POST",
        "status_code": 500,
        "status_class": "5xx",
        "kind": "unhandled_exception",
        "code": "INTERNAL_SERVER_ERROR",
        "trace_id": f"trace-{fingerprint}",
        "occurrences": occurrences,
        "first_seen_at": seen - timedelta(minutes=30),
        "last_seen_at": seen,
    }


_ERROR_OPEN = _error_row(
    "a" * 64, route_template="/v1/cases/{case_id}/entries", minutes_ago=5, occurrences=412
)
_ERROR_RESOLVED = _error_row(
    "b" * 64, route_template="/v1/intakes/{intake_id}/media", minutes_ago=180, occurrences=1
)
_ERROR_ROWS = [_ERROR_OPEN, _ERROR_RESOLVED]
#: What the single aggregate over the unfiltered feed reports for those two rows:
#: two DISTINCT failures, 413 occurrences between them.
_ERROR_TOTALS = [{"entries": 2, "occurrences": 413}]


async def _error_feed(
    *,
    rows: list[dict[str, object]] | None = None,
    totals: list[dict[str, object]] | None = None,
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    window_minutes: int = DEFAULT_ERROR_WINDOW_MINUTES,
) -> tuple[object, AsyncMock]:
    """Run the read over a mocked connection and hand back the page and the mock."""
    connection = _connection(
        totals if totals is not None else _ERROR_TOTALS,
        rows if rows is not None else [],
    )
    view = await query_error_feed(
        connection,
        page=page,
        page_size=page_size,
        status=status,
        now=_ERROR_NOW,
        window_minutes=window_minutes,
    )
    return view, connection


async def test_the_error_feed_names_the_template_method_status_and_trace() -> None:
    """The four things an operator needs to act, and never a concrete request path."""
    view, _ = await _error_feed(rows=[_ERROR_OPEN])

    (entry,) = view.errors
    assert entry.route_template == "/v1/cases/{case_id}/entries"
    assert entry.method == "POST"
    assert entry.status_code == 500
    assert entry.status_class == "5xx"
    assert entry.kind == "unhandled_exception"
    # The cross-tool join key, the way the capture recorded it.
    assert entry.trace_id == f"trace-{'a' * 64}"
    assert entry.code == "INTERNAL_SERVER_ERROR"


async def test_a_repeat_is_one_entry_carrying_its_count_and_its_most_recent_sighting() -> None:
    """A loop is a count, not a wall - and the stamp is when it LAST happened."""
    view, _ = await _error_feed(rows=[_ERROR_OPEN])

    (entry,) = view.errors
    assert entry.occurrences == 412
    assert entry.last_seen_at == _ERROR_NOW - timedelta(minutes=5)
    # ``first_seen_at`` is carried too: "started this morning" is a different
    # question from "happening again right now", and only one stamp answers both.
    assert entry.first_seen_at == _ERROR_NOW - timedelta(minutes=35)


async def test_the_feed_reports_distinct_failures_and_occurrences_as_two_figures() -> None:
    """They are different questions, and a client labelling the page needs both."""
    view, _ = await _error_feed()

    assert (view.total_count, view.total_occurrences) == (2, 413)


async def test_the_feed_totals_are_one_aggregate_over_the_same_filter_as_the_page() -> None:
    """Two aggregates could describe two different sets of failures."""
    _, connection = await _error_feed(status="open")

    aggregate = _compiled(connection, 0)
    assert "count(*) AS entries" in aggregate
    # COALESCE, not a bare SUM: an empty filter is 0 occurrences, and summing NULL
    # over it would answer the same "nothing happened" with two different numbers.
    assert "coalesce(sum(" in aggregate
    assert "observability_error_events.occurrences), 0) AS occurrences" in aggregate
    # The filter reaches BOTH statements, so the count is the filter's count.
    for index in (0, 1):
        assert "last_seen_at >=" in _compiled(connection, index)


async def test_the_feed_is_most_recently_seen_first_with_a_stable_tiebreak() -> None:
    _, connection = await _error_feed(rows=_ERROR_ROWS)

    sql = _compiled(connection, 1)
    assert re.search(
        r"ORDER BY\s+observability\.observability_error_events\.last_seen_at DESC",
        sql,
    )
    # Two failures can share a last sighting - a drain updates a repeat in place - so
    # the tiebreak is what stops a page shuffling under a client paging back.
    assert "observability.observability_error_events.fingerprint ASC" in sql
    assert "LIMIT" in sql


async def test_the_feed_pages() -> None:
    _, connection = await _error_feed(page=3, page_size=10)

    assert "OFFSET 20" in _compiled(connection, 1)


async def test_the_open_filter_keeps_only_what_happened_inside_the_window() -> None:
    _, connection = await _error_feed(status="open")

    for index in (0, 1):
        assert "WHERE observability.observability_error_events.last_seen_at >=" in _compiled(
            connection, index
        )


async def test_the_resolved_filter_keeps_only_what_stopped_happening_before_it() -> None:
    """Complement, not a second column: an entry is one or the other, never both."""
    _, connection = await _error_feed(status="resolved")

    for index in (0, 1):
        assert "WHERE observability.observability_error_events.last_seen_at <" in _compiled(
            connection, index
        )


async def test_unfiltered_the_feed_carries_no_status_predicate_at_all() -> None:
    _, connection = await _error_feed()

    for index in (0, 1):
        sql = _compiled(connection, index)
        assert "last_seen_at >=" not in sql
        assert "last_seen_at <" not in sql


@pytest.mark.parametrize(
    ("minutes_ago", "expected"),
    [
        (5, ALERT_STATUS_OPEN),
        (60, ALERT_STATUS_OPEN),
        (61, ALERT_STATUS_RESOLVED),
        (180, ALERT_STATUS_RESOLVED),
    ],
)
def test_a_status_is_when_the_failure_last_happened_not_who_handled_it(
    minutes_ago: int, expected: str
) -> None:
    seen = _ERROR_NOW - timedelta(minutes=minutes_ago)

    assert error_status(seen, opened_after=_ERROR_NOW - timedelta(hours=1)) == expected


def test_the_feed_speaks_the_alert_facilities_own_vocabulary() -> None:
    """Two feeds, one set of words - an operator switches between them constantly."""
    assert ERROR_STATUS_VOCABULARY == (ALERT_STATUS_OPEN, ALERT_STATUS_RESOLVED)


async def test_the_page_labels_every_entry_with_the_status_its_own_stamp_derives() -> None:
    view, _ = await _error_feed(rows=_ERROR_ROWS)

    assert [entry.status for entry in view.errors] == [
        ALERT_STATUS_OPEN,
        ALERT_STATUS_RESOLVED,
    ]
    assert view.window_minutes == DEFAULT_ERROR_WINDOW_MINUTES


async def test_the_window_decides_which_failures_read_as_open() -> None:
    """The same three-hour-old failure, still open under a wider lens."""
    view, _ = await _error_feed(rows=[_ERROR_RESOLVED], window_minutes=240)

    assert [entry.status for entry in view.errors] == [ALERT_STATUS_OPEN]


async def test_an_unrecognised_status_is_refused_rather_than_reading_as_an_empty_feed() -> None:
    """The failure mode of getting this wrong is a page that says nothing is failing."""
    with pytest.raises(ValueError, match="unknown error status"):
        await _error_feed(status="acknowledged")


async def test_the_feed_window_refuses_a_non_positive_span() -> None:
    for minutes in (0, -5):
        with pytest.raises(ValueError, match="window_minutes must be positive"):
            await _error_feed(window_minutes=minutes)


async def test_an_empty_feed_is_an_empty_page_not_a_failure() -> None:
    view, _ = await _error_feed(rows=[], totals=[{"entries": 0, "occurrences": 0}])

    assert view.errors == []
    assert (view.total_count, view.total_occurrences) == (0, 0)


async def test_the_facade_resolves_the_feed_window_against_a_pinned_clock() -> None:
    """The route owns the default; the facade owns the clock. See ``get_throughput``."""
    facade = ObservabilityFacade(_engine(_connection(_ERROR_TOTALS, [_ERROR_RESOLVED])))

    view = await facade.get_error_feed(
        page=1, page_size=25, status="open", minutes=240, now=_ERROR_NOW
    )

    assert view.window_minutes == 240
    assert [entry.status for entry in view.errors] == [ALERT_STATUS_OPEN]


async def test_the_error_feed_reads_the_observability_schema_only() -> None:
    """ADR-0003 module isolation, for the tenth read: no join, no other schema."""
    connection = _connection(_ERROR_TOTALS, _ERROR_ROWS)

    await query_error_feed(connection, page=1, page_size=25, now=_ERROR_NOW, window_minutes=60)

    for index in (0, 1):
        assert _from_target(connection, index) == ("observability.observability_error_events")


# --------------------------------------------------------------- deeplinks


def test_deeplinks_derive_each_vendor_independently() -> None:
    links = build_deeplinks(
        grafana_url="https://caresetu.grafana.net",
        sentry_dsn="https://key@o4242.ingest.us-central1.sentry.io/7654321",
        langfuse_host="https://us.cloud.langfuse.com",
        langfuse_public_key="pk-lf-1234",
    )

    assert links.grafana == "https://caresetu.grafana.net"
    assert links.sentry == "https://o4242.sentry.io/issues/?project=7654321"
    assert links.langfuse == "https://us.cloud.langfuse.com/project/pk-lf-1234"


def test_an_unconfigured_vendor_is_an_absent_link_not_a_failure() -> None:
    links = build_deeplinks(grafana_url="https://caresetu.grafana.net")

    assert links.grafana == "https://caresetu.grafana.net"
    assert links.sentry is None
    assert links.langfuse is None


def test_deeplinks_with_nothing_configured_answer_absent_everywhere() -> None:
    links = ObservabilityFacade(MagicMock()).get_deeplinks()

    assert links == build_deeplinks()


# --------------------------------------------------------------- business


def test_period_window_names_the_three_periods() -> None:
    """One read, three windows: they differ only in where they START (#717 dec. 11)."""
    # 2026-10-12 is a Monday, so the week is that one day and month-to-date the 12th.
    assert period_window(BUSINESS_PERIOD_TODAY, today=_TODAY) == (_TODAY, _TODAY)
    assert period_window(BUSINESS_PERIOD_WEEK, today=_TODAY) == (_TODAY, _TODAY)
    assert period_window(BUSINESS_PERIOD_MONTH, today=_TODAY) == (
        date(2026, 10, 1),
        _TODAY,
    )

    # Saturday: the week is Monday the 5th through today, NOT the rolling six days.
    saturday = date(2026, 10, 17)
    assert period_window(BUSINESS_PERIOD_WEEK, today=saturday) == (
        date(2026, 10, 12),
        saturday,
    )
    # The 1st: a month-to-date that has only seen one day is still a real answer.
    assert period_window(BUSINESS_PERIOD_MONTH, today=date(2026, 10, 1)) == (
        date(2026, 10, 1),
        date(2026, 10, 1),
    )


def test_period_window_defaults_to_the_current_utc_day() -> None:
    assert period_window(BUSINESS_PERIOD_TODAY)[1] == datetime.now(UTC).date()


def test_period_window_refuses_an_unknown_period() -> None:
    """An unknown period raises instead of falling back to one period's numbers.

    Falling back would answer 200 with a DIFFERENT window's spend, which is the worse
    failure a business read can have: the operator reads it as fact.
    """
    with pytest.raises(ValueError, match="unknown business period 'yesterday'"):
        period_window("yesterday", today=_TODAY)


#: The ``(provider, model, task_type)`` grain rows the one aggregation delivers, in
#: the order its ``ORDER BY provider, model, task_type`` SELECT returns them. The
#: ``draft`` row is here because #722 made the drafting leg metered, so the drafting
#: spend is produced rather than declared - a breakdown that filtered it out would
#: under-report the bill it exists to explain.
_BUSINESS_ROWS: list[dict[str, object]] = [
    {
        "provider": "anthropic",
        "model": "claude-3-5-haiku",
        "task_type": "transcribe",
        "jobs": 3,
        "input_tokens": 300_000,
        "output_tokens": 30_000,
        "cost_paise": 60_000,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "task_type": "draft",
        "jobs": 2,
        "input_tokens": 40_000,
        "output_tokens": 20_000,
        "cost_paise": 20_000,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "task_type": "structure",
        "jobs": 5,
        "input_tokens": 100_000,
        "output_tokens": 0,
        "cost_paise": 10_000,
    },
]

#: The budget snapshot rows behind the cap. Both scopes carry the SAME 150,000 cap -
#: one bill-wide figure written onto every scope - so the cap is read as ``max``, the
#: rule ``/cost`` already follows.
_BUSINESS_BUDGET_ROWS: list[dict[str, object]] = [
    {
        "provider": "anthropic",
        "model": "claude-3-5-haiku",
        "monthly_limit_paise": 150_000,
        "alert_threshold_pct": 80,
        "current_spend_paise": 60_000,
        "billing_period_start": _PERIOD_START,
        "billing_period_end": _PERIOD_END,
    },
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "monthly_limit_paise": 150_000,
        "alert_threshold_pct": 80,
        "current_spend_paise": 30_000,
        "billing_period_start": _PERIOD_START,
        "billing_period_end": _PERIOD_END,
    },
]


async def test_business_read_rolls_one_aggregation_up_into_three_breakdowns() -> None:
    """One grain read becomes the headline, the provider rows, the model rows and the
    task rows - so they reconcile by construction rather than by agreement."""
    connection = _connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert view.period == BUSINESS_PERIOD_MONTH
    assert (view.period_start, view.period_end) == (_PERIOD_START, _TODAY)
    assert view.spend_paise == 90_000
    assert view.jobs == 10
    assert view.input_tokens == 440_000
    assert view.output_tokens == 50_000
    assert [row.provider for row in view.by_provider] == ["anthropic", "openai"]
    # Two models share one provider, which is what "by model WITHIN a provider" buys.
    assert [(row.provider, row.model) for row in view.by_model] == [
        ("anthropic", "claude-3-5-haiku"),
        ("openai", "gpt-4o-mini"),
    ]
    assert [row.task_type for row in view.by_task_type] == ["draft", "structure", "transcribe"]
    # Every breakdown adds up to the headline: the same three figures, folded three
    # ways. A provider row IS the sum of its own model rows.
    for breakdown in (view.by_provider, view.by_task_type):
        assert sum(row.spend_paise for row in breakdown) == view.spend_paise
    assert sum(row.spend_paise for row in view.by_model) == view.spend_paise


async def test_business_read_reports_each_token_side_against_its_own_rate() -> None:
    """Input and output are separate volumes with separate figures, never one blend.

    A single ``cost / total_tokens`` figure absorbs a shift between the two sides into
    one moving number; two figures at their own denominators do not.

    These are RATES, not per-side prices, and the test says so: the metered tables hold
    one ``cost_paise`` per job, so both figures carry that same numerator and differ only
    in denominator. Quoting two independent prices would need per-side metering.
    """
    connection = _connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    # 90,000 paise over 440,000 input tokens is 204.5454... per thousand.
    assert view.paise_per_1k_input_tokens == Decimal("204.5455")
    assert view.paise_per_1k_output_tokens == Decimal("1800.0000")
    anthropic = view.by_provider[0]
    assert anthropic.paise_per_1k_input_tokens == Decimal("200.0000")
    assert anthropic.paise_per_1k_output_tokens == Decimal("2000.0000")
    # ``structure`` produced no output tokens at all. That is "nothing to price",
    # not "free output" - the two must stay distinguishable.
    structure = next(row for row in view.by_task_type if row.task_type == "structure")
    assert structure.output_tokens == 0
    assert structure.paise_per_1k_output_tokens is None
    assert structure.paise_per_1k_input_tokens == Decimal("100.0000")


async def test_business_read_spends_patient_rows_only_so_the_bill_is_not_doubled() -> None:
    """Every job writes a patient row AND a doctor row with identical figures.

    Summing both kinds would count each rupee twice. The kind is a filter on the
    MONEY, so it is asserted on the SQL the read issues rather than inferred from a
    fixture - this rule cannot be shown by the arithmetic above, because the doctor
    rows are not in the fixture at all.
    """
    connection = _connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)

    await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    sql = " ".join(_compiled(connection, 0).split())
    assert "observability.observability_attribution_daily" in sql
    assert "actor_kind = 'patient'" in sql
    assert "doctor" not in sql


async def test_business_read_reads_the_cap_from_the_snapshot_and_projects_the_month_end() -> None:
    """Cap, consumed and projection come back together - the "before the cap" half."""
    connection = _connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_TODAY,
        from_date=_TODAY,
        to_date=_TODAY,
        today=_TODAY,
    )

    # The cap is read ONCE, not summed across the scopes that each carry it.
    assert view.monthly_cap_paise == 150_000
    assert view.cap_consumed_paise == 90_000
    assert view.cap_consumed_pct == Decimal("60.00")
    # 90,000 over 12 of October's 31 days, straight-lined: 232,500.
    assert view.projected_month_end_paise == 232_500
    assert view.projection_basis is not None
    assert view.projection_basis.period_start == _PERIOD_START
    assert view.projection_basis.period_end == _PERIOD_END
    assert view.projection_basis.elapsed_days == 12
    assert view.projection_basis.period_days == 31
    # Sixty per cent consumed on the twelfth still lands over the cap, and that is the
    # warning: the month is not safe, the panel says so twelve days before the breach.
    assert view.projected_over_cap is True


async def test_business_read_warns_before_the_cap_not_after() -> None:
    """The whole point of the projection: over the cap on the twentieth, not the last."""
    connection = _connection(
        _BUSINESS_ROWS,
        [_BUSINESS_BUDGET_ROWS[0] | {"current_spend_paise": 140_000}],
    )

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_TODAY,
        from_date=_TODAY,
        to_date=_TODAY,
        today=_TODAY,
    )

    # 140,000 over 12 of 31 days lands at 361,667 against a 150,000 cap: still inside
    # the month, already over budget by the end of it.
    assert view.cap_consumed_pct == Decimal("93.33")
    assert view.projected_month_end_paise == 361_667
    assert view.projected_over_cap is True


async def test_business_read_clamps_a_billing_period_that_has_already_closed() -> None:
    """A stale snapshot stamped on last month projects its FINAL figure, not an
    extrapolation past a month that is over."""
    connection = _connection(
        _BUSINESS_ROWS,
        [
            _BUSINESS_BUDGET_ROWS[0]
            | {
                "billing_period_start": date(2026, 9, 1),
                "billing_period_end": date(2026, 9, 30),
            }
        ],
    )

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert view.projection_basis is not None
    assert view.projection_basis.elapsed_days == 30
    assert view.projection_basis.period_days == 30
    assert view.projected_month_end_paise == 60_000


async def test_business_read_spans_the_widest_period_its_budget_rows_carry() -> None:
    """What happens when the snapshot rows disagree about which month they are in.

    The rollup's period reset re-stamps every stale or unstamped row inside the same
    transaction it snapshots in, so a mixed set cannot survive a pass - but the read
    has to have an answer if one exists anyway, and it takes the rule ``/cost`` already
    reads these bounds by: the WIDEST span the rows carry. Two months' spend over a
    two-month basis projects lower than either month alone, which understates the burn
    rather than overstating it - the safer of the two directions to be wrong in.
    """
    connection = _connection(
        _BUSINESS_ROWS,
        [
            _BUSINESS_BUDGET_ROWS[0],
            _BUSINESS_BUDGET_ROWS[1]
            | {
                "billing_period_start": date(2026, 9, 1),
                "billing_period_end": date(2026, 9, 30),
            },
        ],
    )

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert view.cap_consumed_paise == 90_000
    assert view.projection_basis is not None
    assert view.projection_basis.period_start == date(2026, 9, 1)
    assert view.projection_basis.period_end == _PERIOD_END
    assert view.projection_basis.period_days == 61
    assert view.projection_basis.elapsed_days == 42
    # 90,000 over 42 of a 61-day window: 130,714.
    assert view.projected_month_end_paise == 130_714


async def test_business_read_clears_a_month_projected_under_the_cap() -> None:
    """The healthy verdict, which is the answer most days should give.

    Worth pinning separately from the over-cap case: a flag that is always true is a
    flag nobody reads, and this is the read whose whole purpose is a verdict.
    """
    connection = _connection(
        _BUSINESS_ROWS,
        [_BUSINESS_BUDGET_ROWS[0] | {"current_spend_paise": 10_000}],
    )

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert view.cap_consumed_pct == Decimal("6.67")
    assert view.projected_month_end_paise == 25_833
    assert view.projected_over_cap is False


async def test_business_read_answers_without_a_projection_rather_than_inventing_one() -> None:
    """An unstamped budget row has no period to spread spend across.

    It answers ``None`` - which says "nothing projected" - rather than dividing by
    zero or, worse, projecting against the period the caller happened to ask for.
    """
    connection = _connection(
        _BUSINESS_ROWS,
        [_BUSINESS_BUDGET_ROWS[0] | {"billing_period_start": None, "billing_period_end": None}],
    )

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert view.projection_basis is None
    assert view.projected_month_end_paise is None
    assert view.projected_over_cap is False
    # The spend itself is unaffected: the missing stamps cost the projection, not
    # the numbers an operator is actually here for.
    assert view.spend_paise == 90_000


async def test_business_read_answers_zeroes_for_a_period_with_no_activity() -> None:
    """A window the rollup has not written yet is an answer, not a failure - and the
    breakdown is empty rather than carrying a fabricated zero row."""
    connection = _connection([], [])

    view = await query_business(
        connection,
        period=BUSINESS_PERIOD_TODAY,
        from_date=_TODAY,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert (view.spend_paise, view.jobs, view.input_tokens, view.output_tokens) == (0, 0, 0, 0)
    assert view.paise_per_1k_input_tokens is None
    assert view.paise_per_1k_output_tokens is None
    assert view.monthly_cap_paise == 0
    assert view.cap_consumed_pct == Decimal("0.00")
    assert (view.by_provider, view.by_model, view.by_task_type) == ([], [], [])


async def test_business_read_reads_the_attribution_aggregate_and_the_budget_snapshot_only() -> None:
    """ADR-0003 module isolation, for this read: two tables, both ours, no join."""
    connection = _connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)

    await query_business(
        connection,
        period=BUSINESS_PERIOD_MONTH,
        from_date=_PERIOD_START,
        to_date=_TODAY,
        today=_TODAY,
    )

    assert _from_target(connection, 0) == "observability.observability_attribution_daily"
    assert _from_target(connection, 1) == "observability.observability_ai_cost_budget"


@pytest.mark.parametrize(
    ("period", "expected_start"),
    [
        (BUSINESS_PERIOD_TODAY, _TODAY),
        (BUSINESS_PERIOD_WEEK, _TODAY),
        (BUSINESS_PERIOD_MONTH, _PERIOD_START),
    ],
)
async def test_get_business_serves_every_period_through_one_method(
    period: str, expected_start: date
) -> None:
    """The one seam all three periods go through (#717 decision 11).

    Three methods, or three routes, or three queries would each be a second copy of
    this aggregation to keep in agreement. What this pins is that they are the SAME
    window-resolution, one call, not three tests of three near-identical functions.
    """
    facade = ObservabilityFacade(_engine(_connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)))

    view = await facade.get_business(period=period, today=_TODAY)

    assert view.period == period
    assert view.period_start == expected_start
    assert view.period_end == _TODAY


async def test_get_business_resolves_today_once_so_the_window_and_the_projection_agree() -> None:
    """Two reads of the clock could straddle midnight and put this month's spend into
    tomorrow's window while the projection counted the other day."""
    facade = ObservabilityFacade(_engine(_connection(_BUSINESS_ROWS, _BUSINESS_BUDGET_ROWS)))

    view = await facade.get_business(period=BUSINESS_PERIOD_MONTH, today=_TODAY)

    assert view.projection_basis is not None
    assert view.projection_basis.elapsed_days == (_TODAY - _PERIOD_START).days + 1
