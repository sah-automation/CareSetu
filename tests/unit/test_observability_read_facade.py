"""C1a #706: the MOD-013 operator read facade's aggregation SQL.

Pins the four documented read aggregates - spend against the budgeted period,
the daily cost trend, calls/tokens per provider/task scope, and the quality
rates - against a mocked connection, so the window that reaches SQL, the
aggregation, and the derived arithmetic are all covered without a live
database (coding-standards §2: DB-free unit surface).

Every SELECT is against the ``observability`` schema only: the read facade never
crosses a module boundary (ADR-0003).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.observability.facade import (
    ObservabilityFacade,
    query_cost_summary,
    query_cost_trend,
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
    """``Result.mappings()``: iterable rows, plus the aggregate ``.one()``."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def one(self) -> dict[str, object]:
        return self._rows[0]


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


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

    await query_cost_summary(cost)
    await query_cost_trend(trend, from_date=_FROM, to_date=_TODAY)
    await query_usage(usage, from_date=_FROM, to_date=_TODAY)
    await query_quality(quality, from_date=_FROM, to_date=_TODAY)

    table = "observability.observability_ai_"
    assert _from_target(cost) == f"{table}cost_budget"
    assert _from_target(trend) == f"{table}usage_daily"
    assert _from_target(usage) == f"{table}usage_daily"
    # Quality is two reads of this schema, never one joined query.
    assert _from_target(quality, 0) == f"{table}usage_daily"
    assert _from_target(quality, 1) == f"{table}provider_health"


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
