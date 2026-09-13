"""PHASE-7 T06 (#350): NFR-001 budget meter, observe-and-warn (T11 #408).

The meter reads the authoritative monthly AI spend via a SQL aggregate over the
``intake_ai_jobs`` table (Postgres-first, standard B1) and reports spend +
remaining against the configured budget. Exhaustion is observed and reported,
never enforced: ``allows_ai_call`` is advisory (PS-10, #408) - a hard-stop was
deliberately dropped, the pipeline reads the meter and proceeds regardless. The
unit tier drives the meter through a fake engine (mirroring the
directory/consent direct-seam suite convention): no SQL plumbing, the fake
connection's ``scalar_one`` supplies the aggregate, and the tests pin the seam
shape - that the meter issues the ai_jobs month aggregate and honours it as the
authoritative spend.

Pins:

- The aggregate query targets ``intake_ai_jobs.cost_paise`` summed over the
  current month (the Postgres-first spend source).
- Under budget: ``meter()`` reports spend/remaining and ``allows_ai_call()`` is
  True - and the reported spend comes straight from the fake engine's aggregate
  (rows inserted through the fake engine are reflected).
- Over budget: ``meter()`` reports exhaustion and ``allows_ai_call()`` is False
  - the observe-and-warn signal, advisory only (never a block).
- Budget boundary and constructor guard.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.intake.budget_meter import (
    DEFAULT_MONTHLY_BUDGET_PAISE,
    BudgetMeter,
    BudgetMeterResult,
)


class _FakeResult:
    """Mimics the executed-statement result the meter reads (``scalar_one``)."""

    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one(self) -> Any:
        return self._scalar


def _engine(spend_aggregate: int) -> MagicMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(return_value=_FakeResult(spend_aggregate))
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _executed(engine: MagicMock) -> list[Any]:
    connection = engine.begin.return_value.__aenter__.return_value
    return [call.args[0] for call in connection.execute.await_args_list]


def _meter(*, budget_paise: int, spend: int) -> BudgetMeter:
    return BudgetMeter(engine=_engine(spend), monthly_budget_paise=budget_paise)


def test_default_budget_is_the_nfr001_rupee_cap_in_paise() -> None:
    # NFR-001: <= Rs 2,000 / month = 200,000 paise (project-prd NFR-001).
    assert DEFAULT_MONTHLY_BUDGET_PAISE == 200_000


def test_constructor_rejects_non_positive_budget() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError):
            BudgetMeter(engine=_engine(0), monthly_budget_paise=bad)


@pytest.mark.asyncio
async def test_spend_is_a_postgres_first_sql_aggregate_over_ai_jobs() -> None:
    """The meter issues a SUM over ``intake_ai_jobs.cost_paise`` narrowed to the
    current calendar month - a Postgres-first aggregate, not an in-memory
    counter."""
    engine = _engine(spend_aggregate=42_000)
    meter = BudgetMeter(engine=engine, monthly_budget_paise=DEFAULT_MONTHLY_BUDGET_PAISE)

    spend = await meter.read_spend_paise()

    assert spend == 42_000
    stmt = _executed(engine)[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "intake.intake_ai_jobs" in compiled
    assert "sum(intake.intake_ai_jobs.cost_paise)" in compiled
    # The current-month window comes from Postgres date_trunc, not app side.
    assert "date_trunc('month', now())" in compiled


@pytest.mark.asyncio
async def test_spend_below_budget_allows_the_call_and_reflects_the_fake_aggregate() -> None:
    """Under budget the gate opens, and the spend reported is exactly what the
    fake engine's aggregate returned - i.e. rows inserted through the fake
    engine surface in the meter."""
    meter = BudgetMeter(
        engine=_engine(spend_aggregate=50_000),
        monthly_budget_paise=DEFAULT_MONTHLY_BUDGET_PAISE,
    )

    result = await meter.meter()

    assert isinstance(result, BudgetMeterResult)
    assert result.spend_paise == 50_000  # the fake aggregate (rows) is authoritative
    assert result.budget_paise == DEFAULT_MONTHLY_BUDGET_PAISE
    assert result.remaining_paise == DEFAULT_MONTHLY_BUDGET_PAISE - 50_000
    assert result.exhausted is False
    assert result.allows_ai_call is True
    # The gate surface agrees with the meter result.
    assert await meter.allows_ai_call() is True


@pytest.mark.asyncio
async def test_spend_above_budget_reports_exhaustion_as_advisory() -> None:
    """Over budget the meter reports exhaustion and ``allows_ai_call()`` is
    False - the observe-and-warn signal (PS-10, #408), advisory only: the
    pipeline reads it and proceeds, the meter never blocks a call."""
    meter = BudgetMeter(
        engine=_engine(spend_aggregate=DEFAULT_MONTHLY_BUDGET_PAISE + 1),
        monthly_budget_paise=DEFAULT_MONTHLY_BUDGET_PAISE,
    )

    result = await meter.meter()

    assert result.exhausted is True
    # No overspend: remaining is floored at zero.
    assert result.remaining_paise == 0
    assert result.allows_ai_call is False
    assert await meter.allows_ai_call() is False


@pytest.mark.asyncio
async def test_spend_exactly_at_budget_is_exhausted_advisory() -> None:
    """A spend that reaches the budget exactly is exhausted - reported as such,
    observe-and-warn: no hard block, the meter only observes and reports."""
    meter = BudgetMeter(
        engine=_engine(spend_aggregate=DEFAULT_MONTHLY_BUDGET_PAISE),
        monthly_budget_paise=DEFAULT_MONTHLY_BUDGET_PAISE,
    )

    result = await meter.meter()

    assert result.exhausted is True
    assert result.remaining_paise == 0
    assert await meter.allows_ai_call() is False
