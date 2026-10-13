"""C1 #706/#707: the operator observability read routes against real PostgreSQL.

Seeds the ``observability`` schema the way the B4a consumer and the B5a rollup
leave it - ``observability_ai_usage_daily`` per ``(date, provider, model,
task_type)`` scope, ``observability_ai_cost_budget`` snapshotted for the current
billing period, ``observability_ai_provider_health`` per provider - plus one
usage row well outside the default window. The C1b routes additionally need the
alert rows and the rollup-ledger row the B4b consumer and B5a pass write, and
outbox rows in another module's schema for the ``/health`` backlog and
dead-letter counts. Then it drives the nine operator routes as an authenticated
operator, through the app's own ``observability_facade`` wiring, and asserts each
response against that seed: the totals are the seeded sums, the 30-day default
window excludes the stale row and a ``days=1`` window excludes yesterday, and
every rate is the seeded ratio.

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
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import create_app
from bus.bootstrap import MODULE_SCHEMAS
from bus.dispatcher import discover_outbox_tables
from bus.outbox_ddl import outbox_table
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
#: The ONE bill-wide cap, stamped onto both scope rows exactly as the B5a rollup
#: writes ``AI_MONTHLY_BUDGET_PAISE``. Summing it across the rows would double the
#: budget, so the seeded total must stay this figure.
_BUDGET_CAP_PAISE = 150_000

COST_PATH = "/v1/operator/observability/cost"
TREND_PATH = "/v1/operator/observability/cost/trend"
USAGE_PATH = "/v1/operator/observability/usage"
QUALITY_PATH = "/v1/operator/observability/quality"
OVERVIEW_PATH = "/v1/operator/observability/overview"
LATENCY_PATH = "/v1/operator/observability/latency"
HEALTH_PATH = "/v1/operator/observability/health"
ALERTS_PATH = "/v1/operator/observability/alerts"
DEEPLINKS_PATH = "/v1/operator/observability/deeplinks"

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
            # ``/health`` counts every module's outbox, so a row another suite left
            # behind would land in its totals. Emptied through the dispatcher's own
            # table contract rather than with raw SQL naming other schemas.
            for target in await discover_outbox_tables(connection, MODULE_SCHEMAS):
                await connection.execute(delete(outbox_table(target.table_name, target.schema)))
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
            "('openai', 'gpt-4o-mini', :cap, 80, 90000, :start, :end), "
            "('anthropic', 'claude-3-5-haiku', :cap, 80, 20000, :start, :end)"
        ),
        {"cap": _BUDGET_CAP_PAISE, "start": _PERIOD_START, "end": _PERIOD_END},
    )
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_provider_health "
            "(provider, window_start, window_end, sample_count, success_rate, "
            "p50_duration_ms, p95_duration_ms, p99_duration_ms, breaker_state) VALUES "
            "('openai', :start, :end, 8, 0.8750, 1200.00, 8400.00, 15100.00, 'closed'), "
            "('anthropic', :start, :end, 1, 0.5000, 900.00, 1500.00, 1800.00, 'open')"
        ),
        {"start": _DAY_START, "end": _TODAY},
    )


async def _seed_rollup_and_alerts(connection: AsyncConnection) -> None:
    """The B5a ledger row and three B4b/B5a alerts: two open, one resolved."""
    await connection.execute(
        text(
            "INSERT INTO observability.observability_rollup_runs "
            "(rollup_date, mode, billing_period_start, providers, ran_at) "
            "VALUES (:rolled, 'daily', :start, 2, now())"
        ),
        {"rolled": _YESTERDAY, "start": _PERIOD_START},
    )
    await connection.execute(
        text(
            "INSERT INTO observability.observability_alert_events "
            "(severity, kind, title, payload, status, created_at) VALUES "
            "('critical', 'breaker_open', 'AI provider breaker open for anthropic', "
            " CAST(:open_payload AS jsonb), 'open', :newest), "
            "('warning', 'ai_budget', 'AI budget past 80% of the monthly cap', "
            " CAST(:open_payload AS jsonb), 'open', :middle), "
            "('warning', 'outbox_dead_letter', 'Outbox dead-letter row in intake.intake_outbox', "
            " CAST(:resolved_payload AS jsonb), 'resolved', :oldest)"
        ),
        {
            "open_payload": '{"source": "rollup", "provider": "anthropic"}',
            "resolved_payload": '{"source": "rollup", "table": "intake.intake_outbox"}',
            "newest": datetime(2026, 10, 12, 3, 0, tzinfo=UTC),
            "middle": datetime(2026, 10, 11, 3, 0, tzinfo=UTC),
            "oldest": datetime(2026, 10, 10, 3, 0, tzinfo=UTC),
        },
    )


async def _seed_outbox(connection: AsyncConnection) -> None:
    """Two pending, one inflight and one dead-lettered intake event, as a stuck queue."""
    await connection.execute(
        text(
            "INSERT INTO intake.intake_outbox "
            "(event_id, event_type, payload, occurred_at, status, attempts) VALUES "
            "(:a, 'intake.ai_job_completed', '{}'::jsonb, now(), 'pending', 0), "
            "(:b, 'intake.ai_job_completed', '{}'::jsonb, now(), 'pending', 1), "
            "(:c, 'intake.ai_job_completed', '{}'::jsonb, now(), 'inflight', 1), "
            "(:d, 'intake.ai_job_completed', '{}'::jsonb, now(), 'dead_letter', 5)"
        ),
        {"a": uuid.uuid4(), "b": uuid.uuid4(), "c": uuid.uuid4(), "d": uuid.uuid4()},
    )


@pytest_asyncio.fixture
async def seeded_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The truncated engine with the seeded observability aggregates in it."""
    async with engine.begin() as connection:
        await _seed(connection)
    yield engine


@pytest_asyncio.fixture
async def rolled_engine(seeded_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The seeded engine plus the rollup ledger, the alerts and the outbox rows."""
    async with seeded_engine.begin() as connection:
        await _seed_rollup_and_alerts(connection)
        await _seed_outbox(connection)
    yield seeded_engine


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


def _client(database_url: str, **overrides: object) -> TestClient:
    """The real app - including its own ``observability_facade`` wiring."""
    return TestClient(
        create_app(
            settings=Settings(
                database_url=database_url,
                gateway_jwt_verify_enabled=True,
                gateway_jwt_signing_key=_SIGNING_KEY,
                **overrides,  # type: ignore[arg-type]
            )
        )
    )


async def test_cost_matches_the_seeded_budgets(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(COST_PATH, headers=_bearer()).json()

    assert body["total_spend_paise"] == 110_000
    # The cap is read once, not summed: both scope rows carry the same 150_000.
    assert body["total_limit_paise"] == _BUDGET_CAP_PAISE
    assert body["remaining_paise"] == 40_000
    assert body["utilization_pct"] == "73.33"
    assert body["exhausted"] is False
    assert body["period_start"] == _PERIOD_START.isoformat()
    assert body["period_end"] == _PERIOD_END.isoformat()
    assert [(budget["provider"], budget["model"]) for budget in body["budgets"]] == [
        ("anthropic", "claude-3-5-haiku"),
        ("openai", "gpt-4o-mini"),
    ]
    # Each scope's own share of that one cap: 20000/150000 and 90000/150000.
    assert body["budgets"][0]["utilization_pct"] == "13.33"
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
        overview = client.get(OVERVIEW_PATH, headers=headers).json()
        latency = client.get(LATENCY_PATH, headers=headers).json()
        alerts = client.get(ALERTS_PATH, headers=headers).json()

    assert cost["total_spend_paise"] == 0
    assert cost["period_start"] is None
    assert cost["budgets"] == []
    assert trend["points"] == []
    assert usage["rows"] == []
    assert quality["success_rate"] is None
    assert quality["low_confidence_rate"] is None
    assert quality["providers"] == []
    assert overview["spend_paise"] == 0
    assert overview["budget_paise"] == 0
    assert overview["budget_utilization_pct"] == "0.00"
    assert overview["p95_duration_ms"] is None
    assert overview["last_rolled_date"] is None
    assert overview["open_alerts"] == 0
    assert latency["providers"] == []
    assert latency["last_rolled_date"] is None
    assert alerts["alerts"] == []


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


# ------------------------------------------------- C1b (#707): the five reads


async def test_overview_matches_the_seeded_aggregates(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(OVERVIEW_PATH, headers=_bearer()).json()

    assert body["days"] == 30
    assert body["to_date"] == _TODAY.isoformat()
    assert body["total_calls"] == 10
    assert body["success_count"] == 8
    assert body["success_rate"] == "0.8000"
    assert body["low_confidence_count"] == 2
    assert body["low_confidence_rate"] == "0.2500"
    # The slowest provider's p95 across the seeded health rows, not a sum.
    assert body["p95_duration_ms"] == "8400.00"
    assert body["spend_paise"] == 110_000
    assert body["budget_paise"] == _BUDGET_CAP_PAISE
    assert body["budget_utilization_pct"] == "73.33"
    assert body["budget_exhausted"] is False
    # Two open alerts (one critical) and one provider with an open breaker.
    assert body["open_alerts"] == 2
    assert body["critical_open_alerts"] == 1
    assert body["open_breakers"] == 1
    assert body["last_rolled_date"] == _YESTERDAY.isoformat()


async def test_overview_narrows_to_the_requested_window(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(f"{OVERVIEW_PATH}?days=1", headers=_bearer()).json()

    assert body["total_calls"] == 8
    assert body["success_rate"] == "0.8750"
    # The budget and alert figures are not windowed: the cap is a period figure
    # and an alert stays open until a pass resolves it.
    assert body["budget_paise"] == _BUDGET_CAP_PAISE
    assert body["open_alerts"] == 2


async def test_latency_reports_the_rolled_percentiles(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(LATENCY_PATH, headers=_bearer()).json()

    assert body["last_rolled_date"] == _YESTERDAY.isoformat()
    assert [
        (row["provider"], row["sample_count"], row["p50_duration_ms"], row["p95_duration_ms"])
        for row in body["providers"]
    ] == [
        ("anthropic", 1, "900.00", "1500.00"),
        ("openai", 8, "1200.00", "8400.00"),
    ]
    assert body["providers"][1]["p99_duration_ms"] == "15100.00"
    # The window the rollup ranked over is echoed back, so a reader can judge freshness.
    assert body["providers"][1]["window_start"] == "2026-10-13T00:00:00Z"


async def test_health_counts_the_seeded_outbox_and_breakers(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(HEALTH_PATH, headers=_bearer()).json()

    database = next(e for e in body["dependencies"] if e["name"] == "database")
    assert database["status"] == "up"
    # No REDIS_URL in this deployment: a configuration choice, not a failed store.
    cache = next(e for e in body["dependencies"] if e["name"] == "cache")
    assert cache["status"] == "disabled"

    intake = next(row for row in body["outbox"] if row["table"] == "intake_outbox")
    assert (intake["pending"], intake["inflight"], intake["dead_letter"]) == (2, 1, 1)
    assert intake["backlog"] == 3
    # The totals sum every module's outbox; the fixture emptied them all.
    assert body["outbox_backlog"] == 3
    assert body["dead_letter_rows"] == 1
    assert [(row["provider"], row["breaker_state"]) for row in body["breakers"]] == [
        ("anthropic", "open"),
        ("openai", "closed"),
    ]
    assert body["open_breakers"] == 1


async def test_health_reports_a_configured_cache(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url, redis_url="redis://localhost:6379/0") as client:
        body = client.get(HEALTH_PATH, headers=_bearer()).json()

    cache = next(e for e in body["dependencies"] if e["name"] == "cache")
    assert cache["status"] == "configured"


async def test_alerts_feed_is_newest_first(rolled_engine: AsyncEngine, database_url: str) -> None:
    with _client(database_url) as client:
        body = client.get(ALERTS_PATH, headers=_bearer()).json()

    assert body["limit"] == 50
    assert body["count"] == 3
    assert [(entry["created_at"], entry["kind"], entry["status"]) for entry in body["alerts"]] == [
        ("2026-10-12T03:00:00Z", "breaker_open", "open"),
        ("2026-10-11T03:00:00Z", "ai_budget", "open"),
        ("2026-10-10T03:00:00Z", "outbox_dead_letter", "resolved"),
    ]
    assert body["alerts"][0]["payload"] == {"source": "rollup", "provider": "anthropic"}
    assert body["alerts"][0]["acked_by"] is None


async def test_alerts_narrow_to_status_and_limit(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        open_feed = client.get(f"{ALERTS_PATH}?status=open&limit=1", headers=_bearer()).json()
        resolved = client.get(f"{ALERTS_PATH}?status=resolved", headers=_bearer()).json()

    assert open_feed["count"] == 1
    assert open_feed["alerts"][0]["kind"] == "breaker_open"
    assert [entry["kind"] for entry in resolved["alerts"]] == ["outbox_dead_letter"]


async def test_deeplinks_answer_the_configured_vendors(database_url: str) -> None:
    with _client(
        database_url,
        grafana_url="https://caresetu.grafana.net",
        sentry_dsn="https://key@o4242.ingest.us-central1.sentry.io/7654321",
        langfuse_public_key="pk-lf-1234",
        langfuse_secret_key="sk-lf-1234",
    ) as client:
        body = client.get(DEEPLINKS_PATH, headers=_bearer()).json()

    assert body == {
        "grafana": "https://caresetu.grafana.net",
        "sentry": "https://o4242.sentry.io/issues/?project=7654321",
        "langfuse": "https://us.cloud.langfuse.com/project/pk-lf-1234",
    }


async def test_deeplinks_with_no_vendor_configured_answer_absent_links(
    database_url: str,
) -> None:
    """No vendor configured is the default deployment; it must never be a 5xx."""
    with _client(database_url) as client:
        response = client.get(DEEPLINKS_PATH, headers=_bearer())

    assert response.status_code == 200
    assert response.json() == {"grafana": None, "sentry": None, "langfuse": None}


async def test_c1b_routes_refuse_anonymous_and_non_operator_callers(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        for path in (OVERVIEW_PATH, LATENCY_PATH, HEALTH_PATH, ALERTS_PATH, DEEPLINKS_PATH):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=_bearer("patient")).status_code == 403
