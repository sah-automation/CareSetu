"""C1 #706/#707: the MOD-013 operator read facade's aggregation SQL.

Pins the documented read aggregates - spend against the budgeted period, the
daily cost trend, calls/tokens per provider/task scope, the quality rates, the
overview's headline KPIs, the rolled latency percentiles, dependency/outbox health
and the alert feed - against a mocked connection, so the window that reaches SQL,
the aggregation, and the derived arithmetic are all covered without a live
database (coding-standards §2: DB-free unit surface).

Every SELECT is against the ``observability`` schema only: the read facade never
crosses a module boundary (ADR-0003). The ``/health`` outbox counts are the one
exception and they reach another schema only through the dispatcher's own
sanctioned counting function, which is stubbed here and asserted in the round-trip
test against real outbox rows.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from bus.dispatcher import OutboxRowCounts, OutboxTable
from modules.observability.facade import (
    ObservabilityFacade,
    build_deeplinks,
    query_alerts,
    query_cost_summary,
    query_cost_trend,
    query_health,
    query_latency,
    query_overview,
    query_quality,
    query_usage,
    window_for,
)

_TODAY = date(2026, 10, 12)
#: ``window_for(30)``: 30 inclusive UTC days ending today.
_FROM = date(2026, 9, 13)
_PERIOD_START = date(2026, 10, 1)
_PERIOD_END = date(2026, 10, 31)


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

    await query_cost_summary(cost)
    await query_cost_trend(trend, from_date=_FROM, to_date=_TODAY)
    await query_usage(usage, from_date=_FROM, to_date=_TODAY)
    await query_quality(quality, from_date=_FROM, to_date=_TODAY)
    await query_overview(overview, from_date=_FROM, to_date=_TODAY)
    await query_latency(latency)

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
    assert _from_target(overview, 3) == "observability.observability_rollup_runs"
    assert _from_target(overview, 4) == f"{table}cost_budget"
    assert _from_target(latency, 0) == f"{table}provider_health"
    assert _from_target(latency, 1) == "observability.observability_rollup_runs"


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


#: The five results ``query_overview`` reads, in the order it issues them: the
#: windowed usage sums, the open-alert counts, the provider-health aggregate, the
#: rollup ledger's newest date, then the budget rows behind ``/cost``.
_OVERVIEW_ROWS: tuple[list[dict[str, object]], ...] = (
    [{"calls": 9, "success_count": 7, "low_confidence_count": 2}],
    [{"open_alerts": 4, "critical_open_alerts": 1}],
    [{"p95_duration_ms": Decimal("8400.00"), "open_breakers": 1}],
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
    )

    overview = await query_overview(_connection(*empty), from_date=_FROM, to_date=_TODAY)

    assert overview.success_rate is None
    assert overview.low_confidence_rate is None
    assert overview.p95_duration_ms is None
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
    assert cache.status == "configured"
    assert cache.detail is None


async def test_health_facade_reads_the_cache_flag_the_caller_resolved() -> None:
    facade = ObservabilityFacade(_engine(_connection([], [], _BREAKER_ROWS)))

    health = await facade.get_health(cache_configured=True)

    assert next(entry for entry in health.dependencies if entry.name == "cache").status == (
        "configured"
    )


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
    feed = await query_alerts(_connection(_ALERT_ROWS), limit=50)

    assert feed.limit == 50
    assert feed.count == 1
    entry = feed.alerts[0]
    assert entry.kind == "breaker_open"
    assert entry.severity == "critical"
    assert entry.payload == {"source": "rollup", "provider": "anthropic"}
    assert entry.acked_by is None


async def test_alerts_are_newest_first_with_a_stable_tiebreak() -> None:
    connection = _connection(_ALERT_ROWS)

    await query_alerts(connection, limit=10)

    sql = _compiled(connection)
    assert re.search(r"ORDER BY\s+observability\.observability_alert_events\.created_at DESC", sql)
    assert re.search(r"observability\.observability_alert_events\.id DESC", sql)
    assert "LIMIT" in sql


async def test_alerts_narrow_to_a_status_when_one_is_given() -> None:
    connection = _connection(_ALERT_ROWS)

    await query_alerts(connection, limit=10, status="open")

    assert "WHERE observability.observability_alert_events.status" in _compiled(connection)


async def test_alerts_are_empty_before_any_finding() -> None:
    feed = await query_alerts(_connection([]), limit=25)

    assert feed.count == 0
    assert feed.alerts == []


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
