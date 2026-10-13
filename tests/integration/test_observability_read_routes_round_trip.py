"""C1a #706: the operator observability read routes against real PostgreSQL.

Seeds the ``observability`` schema the way the B4a consumer and the B5a rollup
leave it - ``observability_ai_usage_daily`` per ``(date, provider, model,
task_type)`` scope, ``observability_ai_cost_budget`` snapshotted for the current
billing period, ``observability_ai_provider_health`` per provider - plus one
usage row well outside the default window. Then it drives the four operator
routes as an authenticated operator, through the app's own
``observability_facade`` wiring, and asserts each response against that seed:
the totals are the seeded sums, the 30-day default window excludes the stale row
and a ``days=1`` window excludes yesterday, and every rate is the seeded ratio.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
and migrates to head and back down afterwards (same shape as the B4a/B5a
round-trip tests).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_SIGNING_KEY = "integration-observability-read-signing-key"

_TODAY = datetime.now(UTC).date()
_YESTERDAY = _TODAY - timedelta(days=1)
#: Outside the default 30-day window: every windowed read must ignore it.
_STALE = _TODAY - timedelta(days=40)
_PERIOD_START = _TODAY.replace(day=1)
_PERIOD_END = _TODAY.replace(day=28)
_DAY_START = datetime.combine(_TODAY, datetime.min.time(), tzinfo=UTC)

COST_PATH = "/v1/operator/observability/cost"
TREND_PATH = "/v1/operator/observability/cost/trend"
USAGE_PATH = "/v1/operator/observability/usage"
QUALITY_PATH = "/v1/operator/observability/quality"

_TRUNCATE = (
    "TRUNCATE TABLE observability.observability_ai_provider_health, "
    "observability.observability_ai_cost_budget, "
    "observability.observability_ai_usage_daily, "
    "observability.observability_business_daily, "
    "observability.observability_alert_events, "
    "observability.observability_rollup_runs, "
    "observability.consumed_events CASCADE"
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


async def _seed(connection: AsyncConnection) -> None:
    """Three in-window usage scopes, one stale scope, two budgets, two health rows."""
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_usage_daily "
            "(usage_date, provider, model, task_type, calls, success_count, "
            "failure_count, timeout_count, low_confidence_count, input_tokens, "
            "output_tokens, cost_paise) VALUES "
            "(:today, 'openai', 'gpt-4o-mini', 'triage', 5, 4, 1, 0, 2, 1000, 200, 250), "
            "(:today, 'openai', 'gpt-4o-mini', 'summarize', 3, 3, 0, 0, 0, 400, 90, 90), "
            "(:yesterday, 'anthropic', 'claude-3-5-haiku', 'triage', 2, 1, 0, 1, 0, 240, 0, 20), "
            "(:stale, 'openai', 'gpt-4o-mini', 'triage', 99, 99, 0, 0, 0, 9000, 9000, 999)"
        ),
        {"today": _TODAY, "yesterday": _YESTERDAY, "stale": _STALE},
    )
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_cost_budget "
            "(provider, model, monthly_limit_paise, alert_threshold_pct, "
            "current_spend_paise, billing_period_start, billing_period_end) VALUES "
            "('openai', 'gpt-4o-mini', 150000, 80, 90000, :start, :end), "
            "('anthropic', 'claude-3-5-haiku', 50000, 80, 20000, :start, :end)"
        ),
        {"start": _PERIOD_START, "end": _PERIOD_END},
    )
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_provider_health "
            "(provider, window_start, window_end, sample_count, success_rate, "
            "breaker_state) VALUES "
            "('openai', :start, :end, 8, 0.8750, 'closed'), "
            "('anthropic', :start, :end, 1, 0.5000, 'open')"
        ),
        {"start": _DAY_START, "end": _TODAY},
    )


@pytest_asyncio.fixture
async def seeded_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The truncated engine with the seeded observability aggregates in it."""
    async with engine.begin() as connection:
        await _seed(connection)
    yield engine


def _token(scope: str = "operator") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=1,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(scope: str = "operator") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(scope)}"}


def _client(database_url: str) -> TestClient:
    """The real app - including its own ``observability_facade`` wiring."""
    return TestClient(
        create_app(
            settings=Settings(
                database_url=database_url,
                gateway_jwt_verify_enabled=True,
                gateway_jwt_signing_key=_SIGNING_KEY,
            )
        )
    )


async def test_cost_matches_the_seeded_budgets(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(COST_PATH, headers=_bearer()).json()

    assert body["total_spend_paise"] == 110_000
    assert body["total_limit_paise"] == 200_000
    assert body["remaining_paise"] == 90_000
    assert body["utilization_pct"] == "55.00"
    assert body["exhausted"] is False
    assert body["period_start"] == _PERIOD_START.isoformat()
    assert body["period_end"] == _PERIOD_END.isoformat()
    assert [(budget["provider"], budget["model"]) for budget in body["budgets"]] == [
        ("anthropic", "claude-3-5-haiku"),
        ("openai", "gpt-4o-mini"),
    ]
    assert body["budgets"][1]["current_spend_paise"] == 90_000
    assert body["budgets"][1]["utilization_pct"] == "60.00"


async def test_cost_trend_sums_the_seeded_days_over_the_default_window(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(TREND_PATH, headers=_bearer()).json()

    assert body["days"] == 30
    assert body["from_date"] == (_TODAY - timedelta(days=29)).isoformat()
    assert body["to_date"] == _TODAY.isoformat()
    # The 40-day-old row is outside the window; yesterday and today are inside it.
    assert [
        (point["usage_date"], point["calls"], point["cost_paise"]) for point in body["points"]
    ] == [
        (_YESTERDAY.isoformat(), 2, 20),
        (_TODAY.isoformat(), 8, 340),
    ]


async def test_cost_trend_narrows_to_the_requested_window(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(f"{TREND_PATH}?days=1", headers=_bearer()).json()

    assert body["days"] == 1
    assert body["from_date"] == _TODAY.isoformat()
    assert [(point["usage_date"], point["cost_paise"]) for point in body["points"]] == [
        (_TODAY.isoformat(), 340)
    ]


async def test_usage_aggregates_the_seeded_scopes(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(USAGE_PATH, headers=_bearer()).json()

    assert body["total_calls"] == 10
    assert body["total_input_tokens"] == 1_640
    assert body["total_output_tokens"] == 290
    assert body["total_cost_paise"] == 360
    assert [
        (row["provider"], row["model"], row["task_type"], row["calls"], row["cost_paise"])
        for row in body["rows"]
    ] == [
        ("anthropic", "claude-3-5-haiku", "triage", 2, 20),
        ("openai", "gpt-4o-mini", "summarize", 3, 90),
        ("openai", "gpt-4o-mini", "triage", 5, 250),
    ]


async def test_usage_narrows_to_the_requested_window(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(f"{USAGE_PATH}?days=1", headers=_bearer()).json()

    assert body["total_calls"] == 8
    assert body["total_cost_paise"] == 340
    assert [row["provider"] for row in body["rows"]] == ["openai", "openai"]


async def test_quality_reports_the_seeded_rates_and_health(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(QUALITY_PATH, headers=_bearer()).json()

    # 8 of 10 calls succeeded; 2 of the 8 completions were low confidence.
    assert body["total_calls"] == 10
    assert body["success_count"] == 8
    assert body["failure_count"] == 1
    assert body["timeout_count"] == 1
    assert body["low_confidence_count"] == 2
    assert body["success_rate"] == "0.8000"
    assert body["low_confidence_rate"] == "0.2500"
    assert [
        (row["provider"], row["success_rate"], row["breaker_state"]) for row in body["providers"]
    ] == [
        ("anthropic", "0.5000", "open"),
        ("openai", "0.8750", "closed"),
    ]


async def test_quality_narrows_to_the_requested_window(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(f"{QUALITY_PATH}?days=1", headers=_bearer()).json()

    assert body["total_calls"] == 8
    # Today alone: 7 of 8 calls succeeded, 2 of those 7 completions unconfident.
    assert body["success_rate"] == "0.8750"
    assert body["low_confidence_rate"] == "0.2857"


async def test_reads_are_empty_before_the_first_rollup(
    engine: AsyncEngine, database_url: str
) -> None:
    """An unbudgeted module is a zeroed answer, not a 5xx or a null-everywhere body."""
    with _client(database_url) as client:
        headers = _bearer()
        cost = client.get(COST_PATH, headers=headers).json()
        trend = client.get(TREND_PATH, headers=headers).json()
        usage = client.get(USAGE_PATH, headers=headers).json()
        quality = client.get(QUALITY_PATH, headers=headers).json()

    assert cost["total_spend_paise"] == 0
    assert cost["period_start"] is None
    assert cost["budgets"] == []
    assert trend["points"] == []
    assert usage["rows"] == []
    assert quality["success_rate"] is None
    assert quality["low_confidence_rate"] is None
    assert quality["providers"] == []


async def test_windowed_reads_refuse_an_out_of_range_window(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        response = client.get(f"{TREND_PATH}?days=0", headers=_bearer())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_read_routes_refuse_anonymous_and_non_operator_callers(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        assert client.get(COST_PATH).status_code == 401
        assert client.get(TREND_PATH, headers=_bearer("patient")).status_code == 403


async def test_rates_are_exact_decimals_not_binary_floats(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(QUALITY_PATH, headers=_bearer()).json()

    assert isinstance(body["success_rate"], str)
    assert Decimal(body["success_rate"]) == Decimal("0.8000")
