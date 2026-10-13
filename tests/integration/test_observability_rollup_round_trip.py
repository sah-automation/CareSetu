"""B5a #704: the MOD-013 nightly rollup against real PostgreSQL.

Seeds ``observability_ai_usage_daily`` exactly as the B4a consumer leaves it
(per ``(date, provider, model, task_type)`` scopes with counters, cost and a
running mean), parks a dead-letter row in an outbox table, and runs the pass for
that date. Asserts the three writes the ticket names: ``observability_ai_provider_health``
refreshed with the recomputed percentiles and breaker state,
``observability_ai_cost_budget`` snapshotted, and the threshold alerts in
``observability_alert_events`` - plus that re-running the same date is a no-op
that neither duplicates the alerts nor stacks the aggregates.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
migrates to head and downgrades afterwards (same shape as the B4a/B4b
round-trip test).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.observability.domain.rollup import (
    ALERT_KIND_AI_BUDGET,
    ALERT_KIND_OUTBOX_DEAD_LETTER,
    ALERT_KIND_PROVIDER_HEALTH_DROP,
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
    RollupThresholds,
)
from modules.observability.facade import run_rollup

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_TARGET_DATE = date(2026, 10, 12)
_PERIOD_START = date(2026, 10, 1)
_PERIOD_END = date(2026, 10, 31)
#: A budget the seeded spend breaches past the default 80% threshold.
_THRESHOLDS = RollupThresholds(monthly_budget_paise=100_000)

_TRUNCATE = (
    "TRUNCATE TABLE observability.observability_ai_provider_health, "
    "observability.observability_ai_cost_budget, "
    "observability.observability_ai_usage_daily, "
    "observability.observability_business_daily, "
    "observability.observability_alert_events, "
    "observability.consumed_events, "
    "intake.intake_outbox CASCADE"
)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (intake + observability v9.0), restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def engine(database_url: str, migrated_schema: None) -> AsyncIterator[AsyncEngine]:
    """A clean engine: every observability aggregate truncated before each test."""
    created = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with created.begin() as connection:
            await connection.execute(text(_TRUNCATE))
    except Exception as exc:
        await created.dispose()
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield created
    await created.dispose()


async def _seed_usage(connection: AsyncConnection) -> None:
    """Three scopes across two providers on the target date, as B4a accumulates them.

    ``openai`` is 3/4 successful across two task scopes with different means, so
    the recomputed percentiles must rank the weighted sample rather than average
    the two means. ``anthropic`` is a clean 4/4. The ``openai`` rows cost 85,000
    paise month-to-date, past 80% of the seeded 100,000 paise budget.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_usage_daily "
            "(usage_date, provider, model, task_type, calls, success_count, "
            "failure_count, timeout_count, input_tokens, output_tokens, cost_paise, "
            "avg_duration_ms, p95_duration_ms) VALUES "
            "(:day, 'openai', 'gpt-4o-mini', 'structure', 3, 3, 0, 0, 10, 20, 25000, "
            " 100.00, NULL), "
            "(:day, 'openai', 'gpt-4o-mini', 'summarize', 1, 0, 1, 0, 0, 0, 60000, NULL, NULL), "
            "(:day, 'openai', 'gpt-4o-mini', 'suggest', 1, 1, 0, 0, 5, 5, 30000, "
            " 400.00, NULL), "
            "(:day, 'anthropic', 'claude-haiku', 'structure', 4, 4, 0, 0, 12, 8, 5000, "
            " 250.00, NULL)"
        ),
        {"day": _TARGET_DATE},
    )


async def _seed_dead_letter(connection: AsyncConnection) -> None:
    """One terminal dead-letter row in the intake outbox, as a poisoned event leaves."""
    await connection.execute(
        text(
            "INSERT INTO intake.intake_outbox "
            "(event_id, event_type, payload, occurred_at, status, attempts) "
            "VALUES (:event_id, 'intake.ai_job_completed', '{}'::jsonb, now(), "
            " 'dead_letter', 5)"
        ),
        {"event_id": uuid4()},
    )


async def _seed_previous_health(connection: AsyncConnection) -> None:
    """A previous pass recorded a perfect success rate, so a drop is measurable."""
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_provider_health "
            "(provider, sample_count, success_rate, breaker_state) "
            "VALUES ('openai', 10, 1.0000, 'closed')"
        )
    )


async def _health_row(connection: AsyncConnection, provider: str) -> Any:
    result = await connection.execute(
        text(
            "SELECT sample_count, success_rate, p50_duration_ms, p95_duration_ms, "
            "p99_duration_ms, breaker_state FROM "
            "observability.observability_ai_provider_health WHERE provider = :provider"
        ),
        {"provider": provider},
    )
    return result.mappings().one()


async def _budget_row(connection: AsyncConnection) -> Any:
    result = await connection.execute(
        text(
            "SELECT monthly_limit_paise, alert_threshold_pct, current_spend_paise, "
            "billing_period_start, billing_period_end FROM "
            "observability.observability_ai_cost_budget "
            "WHERE provider = 'openai' AND model = 'gpt-4o-mini'"
        )
    )
    return result.mappings().one()


async def _alert_rows(connection: AsyncConnection) -> list[Any]:
    result = await connection.execute(
        text("SELECT kind, status FROM observability.observability_alert_events ORDER BY kind")
    )
    return list(result.all())


async def _open_alert_kinds(connection: AsyncConnection) -> list[str]:
    return [row.kind for row in await _alert_rows(connection) if row.status == "open"]


async def _open_alert_count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return len(await _open_alert_kinds(connection))


async def _metric_value(
    connection: AsyncConnection, metric_key: str, day: date = _TARGET_DATE
) -> Any:
    """The generic-store JSON value for one metric, or ``None`` when unwritten."""
    result = await connection.execute(
        text(
            "SELECT value FROM observability.observability_business_daily "
            "WHERE metric_key = :metric_key AND metric_date = :day"
        ),
        {"metric_key": metric_key, "day": day},
    )
    row = result.mappings().first()
    return None if row is None else row["value"]


@pytest.mark.asyncio
async def test_rollup_refreshes_health_snapshots_budget_and_raises_alerts(
    engine: AsyncEngine,
) -> None:
    """The acceptance criterion: one pass writes all three surfaces."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_previous_health(connection)
        await _seed_dead_letter(connection)

    report = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert report.providers == 2
    assert report.health_rows == 2
    assert report.metric_rows == 4
    assert report.budget_snapshots == 2

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        anthropic = await _health_row(connection, "anthropic")
        budget = await _budget_row(connection)

        # openai: 3 completions at 100 ms + 1 at 400 ms, 4 of 5 calls successful.
        assert openai["sample_count"] == 4
        assert openai["success_rate"] == Decimal("0.8000")
        assert openai["p50_duration_ms"] == Decimal("100.00")
        assert openai["p95_duration_ms"] == Decimal("355.00")
        assert openai["p99_duration_ms"] == Decimal("391.00")
        assert openai["breaker_state"] == "closed"

        # anthropic: 4 completions at 250 ms, no failures.
        assert anthropic["sample_count"] == 4
        assert anthropic["success_rate"] == Decimal("1.0000")
        assert anthropic["p95_duration_ms"] == Decimal("250.00")

        # Budget: month-to-date spend snapshot over the configured period.
        assert budget["monthly_limit_paise"] == 100_000
        assert budget["alert_threshold_pct"] == 80
        assert budget["current_spend_paise"] == 115_000
        assert budget["billing_period_start"] == _PERIOD_START
        assert budget["billing_period_end"] == _PERIOD_END

        # Alerts: budget past 80%, a 20-point health drop, and the dead-letter row.
        assert await _open_alert_kinds(connection) == [
            ALERT_KIND_AI_BUDGET,
            ALERT_KIND_OUTBOX_DEAD_LETTER,
            ALERT_KIND_PROVIDER_HEALTH_DROP,
        ]

        # Generic store: one row per registered metric, provider-scoped.
        health_value = await _metric_value(connection, f"{METRIC_KEY_AI_PROVIDER_HEALTH}.openai")
        spend_value = await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai")
        assert health_value["success_rate"] == "0.8000"
        assert health_value["p95_duration_ms"] == "355.00"
        assert health_value["breaker_state"] == "closed"
        assert spend_value == {
            "provider": "openai",
            "calls": 5,
            "success_count": 4,
            "failure_count": 1,
            "timeout_count": 0,
            "cost_paise": 115_000,
        }


@pytest.mark.asyncio
async def test_rollup_is_idempotent_for_the_same_date(engine: AsyncEngine) -> None:
    """A retried nightly job converges: no stacked aggregates, no duplicate alerts."""
    async with engine.begin() as connection:
        await _seed_usage(connection)
        await _seed_previous_health(connection)

    first = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    second = await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    assert first.alerts_raised == 2
    # Nothing is re-raised and nothing is closed: the budget and the health drop
    # are both still true, and a transition alert is never resolved by a pass.
    assert (second.alerts_raised, second.alerts_resolved) == (0, 0)

    async with engine.connect() as connection:
        openai = await _health_row(connection, "openai")
        assert openai["sample_count"] == 4
        assert await _open_alert_kinds(connection) == [
            ALERT_KIND_AI_BUDGET,
            ALERT_KIND_PROVIDER_HEALTH_DROP,
        ]
        assert (await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai"))["calls"] == 5


@pytest.mark.asyncio
async def test_rollup_resolves_a_standing_alert_once_its_threshold_clears(
    engine: AsyncEngine,
) -> None:
    """An alert that stops being true must not stay open in the operator feed."""
    async with engine.begin() as connection:
        await _seed_usage(connection)

    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)
    assert await _open_alert_count(engine) == 1

    # The operator raises the configured cap; the next pass stops breaching it.
    generous = RollupThresholds(monthly_budget_paise=10_000_000)
    report = await run_rollup(engine, _TARGET_DATE, thresholds=generous)

    assert report.alerts_raised == 0
    assert report.alerts_resolved == 1

    async with engine.connect() as connection:
        assert await _open_alert_kinds(connection) == []
        assert [(row.kind, row.status) for row in await _alert_rows(connection)] == [
            (ALERT_KIND_AI_BUDGET, "resolved")
        ]
        # A limit already stored on a scope row is the operator's, not the pass's.
        assert (await _budget_row(connection))["monthly_limit_paise"] == 100_000
        assert (await _budget_row(connection))["current_spend_paise"] == 115_000


@pytest.mark.asyncio
async def test_rollup_on_an_idle_day_invents_no_rows_and_closes_nothing(
    engine: AsyncEngine,
) -> None:
    """An idle day is not an error: nothing is invented and no standing alert closes."""
    quiet_day = date(2026, 10, 13)
    async with engine.begin() as connection:
        await _seed_usage(connection)
    await run_rollup(engine, _TARGET_DATE, thresholds=_THRESHOLDS)

    report = await run_rollup(engine, quiet_day, thresholds=_THRESHOLDS)

    assert (report.providers, report.health_rows, report.metric_rows) == (0, 0, 0)
    assert report.budget_snapshots == 2
    assert (report.alerts_raised, report.alerts_resolved) == (0, 0)

    async with engine.connect() as connection:
        # Month-to-date spend carries forward; the idle day adds no metric row.
        assert (await _budget_row(connection))["current_spend_paise"] == 115_000
        assert await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai", quiet_day) is None
        # The budget is still breached, so it stays open.
        assert await _open_alert_kinds(connection) == [ALERT_KIND_AI_BUDGET]
        assert await _metric_value(connection, f"{METRIC_KEY_AI_SPEND}.openai", quiet_day) is None
