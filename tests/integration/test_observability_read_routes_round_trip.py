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

B8 (#726) folds the gateway error capture into this same round trip rather than
opening a fourth fixture: the real app raises a real 5xx, the catch-all seam
buffers it, and the module facade's drain writes the captured record - so the row
exists only if every hop of the capture path works. B9 (#727) folds the per-minute
HTTP counter into it the same way, and additionally drives ``/throughput`` over the
rows that fold produced, so the aggregate read is proven against the exact shape
the capture writes rather than a hand-written seed. B9 (#728) adds
``/providers`` over the same seeded health rows, which carry the two failure
columns and the named last error the board reads, and B8 (#730) adds ``/errors``
over the rows a real 5xx left behind - the same seam reached from the read's end.

B2 (#731) adds ``/business`` over its own fixture: the daily per-actor attribution
aggregate #725 writes, patient and doctor rows for the same job side by side, plus
the budget snapshot. It is the only read whose window follows the clock rather than a
pinned fixture date, so the assertions derive the projection ARITHMETIC instead of a
figure that would only hold on one day of the month.

B8 (#740) adds ``/product/funnel`` over the product event ledger #739 writes: two
patient journeys that run to a prescription and to a closed case, one patient who
walked away, one whose capture degraded, and one re-record. The seeded timestamps are
placed so each step's median gap has ONE arithmetic answer, and the assertions check
that arithmetic rather than a figure.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable.
The shared integration conftest migrates to head once per file, empties the
observability aggregates and every module's outbox before each test (``/health``
counts them all), and downgrades afterwards.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import unquote

import pytest
import pytest_asyncio
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.facade import (
    ObservabilityFacade,
    drain_error_buffer,
    drain_http_counter,
)
from observability.error_capture import pending_error_captures, reset_error_capture
from observability.http_counter import pending_http_counts, reset_http_counter

_SIGNING_KEY = "integration-observability-read-signing-key"
#: A client-presented trace id, so the round trip asserts the id the CALLER chose
#: survives all the way into the stored record rather than one minted in passing.
_TRACE_ID = "integration-trace-abc123"

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
PROVIDERS_PATH = "/v1/operator/observability/providers"
THROUGHPUT_PATH = "/v1/operator/observability/throughput"
HEALTH_PATH = "/v1/operator/observability/health"
ALERTS_PATH = "/v1/operator/observability/alerts"
ERRORS_PATH = "/v1/operator/observability/errors"
DEEPLINKS_PATH = "/v1/operator/observability/deeplinks"
RELIABILITY_PATH = "/v1/operator/observability/reliability"
BUSINESS_PATH = "/v1/operator/observability/business"
FUNNEL_PATH = "/v1/operator/observability/product/funnel"
ACTIVE_USERS_PATH = "/v1/operator/observability/product/active-users"
RETENTION_PATH = "/v1/operator/observability/product/retention-cohorts"


async def _seed(connection: AsyncConnection) -> None:
    """Three in-window usage scopes, one stale scope, two budgets, three health rows.

    The health rows are seeded for the board as well as ``/quality`` and ``/latency``:
    ``openai`` is quota-refused and timing out behind a CLOSED breaker (degraded),
    ``anthropic`` has an open breaker (down), and ``together-ai`` is a row the
    rollup created with no traffic behind it at all (healthy, every rate NULL).
    """
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
            "p50_duration_ms, p95_duration_ms, p99_duration_ms, breaker_state, "
            "timeout_count, rate_limit_count, last_error) VALUES "
            "('openai', :start, :end, 8, 0.8750, 1200.00, 8400.00, 15100.00, 'closed', "
            " 1, 2, 'rate_limited'), "
            "('anthropic', :start, :end, 1, 0.5000, 900.00, 1500.00, 1800.00, 'open', "
            " 3, 0, 'ConnectError'), "
            "('together-ai', NULL, NULL, 0, NULL, NULL, NULL, NULL, 'closed', 0, 0, NULL)"
        ),
        {"start": _DAY_START, "end": _TODAY},
    )


async def _seed_rollup_and_alerts(connection: AsyncConnection) -> None:
    """The B5a ledger row, two B4b business counts and three alerts."""
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
            "INSERT INTO observability.observability_business_daily "
            "(metric_key, metric_date, value) VALUES "
            "('case.consult_complete', :today, CAST(:six AS jsonb)), "
            "('consent.granted', :today, CAST(:three AS jsonb)), "
            "('case.closed', :stale, CAST(:one AS jsonb))"
        ),
        {
            "today": _TODAY,
            "stale": _STALE,
            "six": '{"count": 6}',
            "three": '{"count": 3}',
            "one": '{"count": 1}',
        },
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


def _failing_client(database_url: str) -> TestClient:
    """The real app plus routes that fail, for the B8 error-capture round trip.

    ``dispatcher_in_process_enabled=False`` so the lifespan does NOT start the
    worker: these tests drive the drain themselves, and a scheduled drain firing
    mid-test would be a race over the very buffer under assertion.

    ``raise_server_exceptions=False`` because Starlette's ``ServerErrorMiddleware``
    sends the envelope AND re-raises the exception - a real client only ever sees
    the 500, so the test client has to as well or the assertion lands on the wrong
    side of the seam.
    """
    app = create_app(
        settings=Settings(
            database_url=database_url,
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_SIGNING_KEY,
            dispatcher_in_process_enabled=False,
        )
    )

    @app.get("/v1/cases/{case_id}/entries/boom")
    def boom(case_id: str) -> None:
        raise RuntimeError(f"database unavailable for case {case_id}")

    @app.get("/v1/cases/{case_id}/entries/unavailable")
    def unavailable() -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})

    @app.get("/v1/cases/{case_id}/entries/both-ways")
    def both_ways() -> JSONResponse:
        """Raises on the first call, gives up on the second.

        One route reached by both capture seams, so a test can show ``kind``
        separating two records whose route, method and status would otherwise
        collapse them together.
        """
        both_ways.calls += 1
        if both_ways.calls == 1:
            raise RuntimeError("the dependency went away mid-request")
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})

    both_ways.calls = 0

    @app.get("/v1/cases/{case_id}/entries/fine")
    def fine() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False)


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
        # The idle provider's rate is NULL, not "0.0000": it was never asked.
        ("together-ai", None, "closed"),
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
        providers = client.get(PROVIDERS_PATH, headers=headers).json()
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
    assert overview["business_counts"] == []
    assert overview["last_rolled_date"] is None
    assert overview["open_alerts"] == 0
    assert latency["providers"] == []
    assert latency["last_rolled_date"] is None
    # #728: before the first rollup the board is EMPTY, not a list of healthy
    # providers. A fabricated row would read as a provider answering normally.
    assert providers["providers"] == []
    assert providers["last_rolled_date"] is None
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
    # Today's registry-driven business counts, by key. The 40-day-old row is
    # outside the window, so it must not appear.
    assert body["business_counts"] == [
        {"metric_key": "case.consult_complete", "count": 6},
        {"metric_key": "consent.granted", "count": 3},
    ]
    assert body["last_rolled_date"] == _YESTERDAY.isoformat()


async def test_overview_narrows_to_the_requested_window(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        body = client.get(f"{OVERVIEW_PATH}?days=1", headers=_bearer()).json()

    assert body["total_calls"] == 8
    assert body["success_rate"] == "0.8750"
    # The budget and alert figures are not windowed: the cap is a period figure
    # and an alert stays open until a pass resolves it. The business counts are.
    assert body["budget_paise"] == _BUDGET_CAP_PAISE
    assert body["open_alerts"] == 2
    assert [entry["metric_key"] for entry in body["business_counts"]] == [
        "case.consult_complete",
        "consent.granted",
    ]


async def test_overview_ignores_snapshot_rows_without_a_count(
    seeded_engine: AsyncEngine, database_url: str
) -> None:
    """A non-count row in the shared store is not coerced to a business count.

    ``observability_business_daily`` holds more than registry-driven counts: the
    #750 batch pull lands a ``langfuse.daily`` snapshot carrying no ``count``
    key, and the rollup's ``ai.*`` metrics carry other shapes. Reading every row
    as ``value->>'count'`` would cast NULL to Integer and 500 the overview, so
    the projection must ignore anything without a count.
    """
    async with seeded_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO observability.observability_business_daily "
                "(metric_key, metric_date, value) VALUES "
                "('case.consult_complete', :today, CAST(:six AS jsonb)), "
                "('langfuse.daily', :today, CAST(:snapshot AS jsonb))"
            ),
            {
                "today": _TODAY,
                "six": '{"count": 6}',
                "snapshot": (
                    '{"vendor": "langfuse", "observation_count": 42, '
                    '"total_tokens": 123456, "total_cost_usd": "0.421300", '
                    '"avg_latency_ms": "815.56"}'
                ),
            },
        )

    with _client(database_url) as client:
        response = client.get(OVERVIEW_PATH, headers=_bearer())

    assert response.status_code == 200
    assert response.json()["business_counts"] == [
        {"metric_key": "case.consult_complete", "count": 6}
    ]


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
        # The idle provider has a health row and therefore appears with NULL
        # percentiles - which is not the same as a provider that answered instantly.
        ("together-ai", 0, None, None),
    ]
    assert body["providers"][1]["p99_duration_ms"] == "15100.00"
    # The window the rollup ranked over is echoed back, so a reader can judge
    # freshness. Derived from ``_TODAY`` because that is what the health rows were
    # seeded with - a hardcoded date would fail on the day after it was written.
    assert body["providers"][1]["window_start"] == f"{_TODAY.isoformat()}T00:00:00Z"


async def test_the_provider_board_derives_a_status_per_provider(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    """#728: the whole point, driven through the real operator HTTP API.

    The three seeded rows cover the three verdicts, and each one is distinguishable
    only because the read derives it: an open breaker, quota refusals behind a
    healthy breaker, and a provider the rollup never saw any traffic from.
    """
    with _client(database_url) as client:
        body = client.get(PROVIDERS_PATH, headers=_bearer()).json()

    assert body["last_rolled_date"] == _YESTERDAY.isoformat()
    assert [(row["provider"], row["status"]) for row in body["providers"]] == [
        ("anthropic", "down"),
        ("openai", "degraded"),
        ("together-ai", "healthy"),
    ]


async def test_the_provider_board_reports_the_figures_behind_each_verdict(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    """Every input to the status is on the row, as an exact wire decimal."""
    with _client(database_url) as client:
        rows = {
            row["provider"]: row
            for row in client.get(PROVIDERS_PATH, headers=_bearer()).json()["providers"]
        }

    openai = rows["openai"]
    assert openai["breaker_state"] == "closed"
    assert openai["success_rate"] == "0.8750"
    assert openai["sample_count"] == 8
    # The two counters the verdict leans on, and the reason it names.
    assert (openai["rate_limit_count"], openai["timeout_count"]) == (2, 1)
    assert openai["last_error"] == "rate_limited"
    assert (openai["p50_duration_ms"], openai["p95_duration_ms"], openai["p99_duration_ms"]) == (
        "1200.00",
        "8400.00",
        "15100.00",
    )

    anthropic = rows["anthropic"]
    assert anthropic["breaker_state"] == "open"
    assert anthropic["last_error"] == "ConnectError"

    # Idle is not broken: nulls and zero counts, never a success rate of 0.0000.
    idle = rows["together-ai"]
    assert idle["success_rate"] is None
    assert (idle["rate_limit_count"], idle["timeout_count"], idle["sample_count"]) == (0, 0, 0)
    assert idle["last_error"] is None


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
        # The idle provider has a row and a closed breaker: a provider that was
        # never called is not an open breaker, and it is not absent either.
        ("together-ai", "closed"),
    ]
    assert body["open_breakers"] == 1


async def test_health_reports_a_configured_cache(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url, redis_url="redis://localhost:6379/0") as client:
        body = client.get(HEALTH_PATH, headers=_bearer()).json()

    cache = next(e for e in body["dependencies"] if e["name"] == "cache")
    assert cache["status"] == "up"
    assert cache["detail"] is None


async def test_alerts_feed_is_newest_first(rolled_engine: AsyncEngine, database_url: str) -> None:
    with _client(database_url) as client:
        body = client.get(ALERTS_PATH, headers=_bearer()).json()

    assert body["total_count"] == 3
    assert [(entry["created_at"], entry["kind"], entry["status"]) for entry in body["alerts"]] == [
        ("2026-10-12T03:00:00Z", "breaker_open", "open"),
        ("2026-10-11T03:00:00Z", "ai_budget", "open"),
        ("2026-10-10T03:00:00Z", "outbox_dead_letter", "resolved"),
    ]
    assert body["alerts"][0]["payload"] == {"source": "rollup", "provider": "anthropic"}
    assert body["alerts"][0]["acked_by"] is None


async def test_alerts_narrow_to_status_and_page(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        first_page = client.get(f"{ALERTS_PATH}?page_size=1", headers=_bearer()).json()
        second_page = client.get(f"{ALERTS_PATH}?page=2&page_size=1", headers=_bearer()).json()
        resolved = client.get(f"{ALERTS_PATH}?status=resolved", headers=_bearer()).json()

    # One row per page, with the count of everything behind them.
    assert [entry["kind"] for entry in first_page["alerts"]] == ["breaker_open"]
    assert first_page["total_count"] == 3
    assert [entry["kind"] for entry in second_page["alerts"]] == ["ai_budget"]
    assert second_page["total_count"] == 3
    # total_count counts the FILTER, not the whole table.
    assert resolved["total_count"] == 1
    assert [entry["kind"] for entry in resolved["alerts"]] == ["outbox_dead_letter"]


# ------------------------------------------------------- B5 #735: acknowledgement
#
# The one WRITE in the operator observability surface, against the real table the
# reads already sit on. It reuses this file's rolled fixture rather than opening a
# fifth one (spec #717 decision 46): the alert rows it acts on are the three the
# feed assertions above already prove are there, and an acknowledgement that cannot
# be seen moving those rows between the open and acknowledged filters is not proven.


async def _alert_row(engine: AsyncEngine, kind: str) -> dict[str, Any]:
    """The stored acknowledgement columns for one seeded alert, as Postgres holds them."""
    async with engine.begin() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT status, acked_by, acked_at FROM "
                        "observability.observability_alert_events WHERE kind = :kind"
                    ),
                    {"kind": kind},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def test_acknowledging_an_alert_writes_the_operator_and_the_time(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        open_alerts = client.get(f"{ALERTS_PATH}?status=open", headers=_bearer()).json()
        alert_id = open_alerts["alerts"][0]["id"]
        response = client.post(f"{ALERTS_PATH}/{alert_id}/acknowledge", headers=_bearer())

    assert response.status_code == 200
    body = response.json()
    assert body["already_acknowledged"] is False
    assert body["alert"]["id"] == alert_id
    assert body["alert"]["status"] == "acknowledged"
    assert body["alert"]["acked_by"] == 1

    row = await _alert_row(rolled_engine, "breaker_open")
    assert row["status"] == "acknowledged"
    assert row["acked_by"] == 1
    assert row["acked_at"] is not None


async def test_an_acknowledged_alert_leaves_the_open_filter_for_its_own(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    """The point of the acknowledgement: the open list is what an operator works."""
    with _client(database_url) as client:
        alert_id = client.get(f"{ALERTS_PATH}?status=open", headers=_bearer()).json()["alerts"][0][
            "id"
        ]
        client.post(f"{ALERTS_PATH}/{alert_id}/acknowledge", headers=_bearer())

        still_open = client.get(f"{ALERTS_PATH}?status=open", headers=_bearer()).json()
        acknowledged = client.get(f"{ALERTS_PATH}?status=acknowledged", headers=_bearer()).json()
        every = client.get(ALERTS_PATH, headers=_bearer()).json()

    assert [(entry["kind"], entry["status"]) for entry in still_open["alerts"]] == [
        ("ai_budget", "open")
    ]
    assert still_open["total_count"] == 1
    assert [entry["id"] for entry in acknowledged["alerts"]] == [alert_id]
    assert acknowledged["total_count"] == 1
    # The acknowledged row is still in the feed, and nothing was lost.
    assert every["total_count"] == 3


async def test_acknowledging_twice_leaves_the_first_acknowledgement_standing(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        alert_id = client.get(ALERTS_PATH, headers=_bearer()).json()["alerts"][0]["id"]
        first = client.post(f"{ALERTS_PATH}/{alert_id}/acknowledge", headers=_bearer()).json()
        second = client.post(f"{ALERTS_PATH}/{alert_id}/acknowledge", headers=_bearer()).json()

    assert first["already_acknowledged"] is False
    assert second["already_acknowledged"] is True
    assert second["alert"]["acked_at"] == first["alert"]["acked_at"]
    row = await _alert_row(rolled_engine, "breaker_open")
    # And the row still carries the FIRST acknowledgement's instant, not the
    # second call's: the guarded write is what makes that true, not a
    # read-then-write that happened not to race.
    assert row["acked_at"] == datetime.fromisoformat(
        first["alert"]["acked_at"].replace("Z", "+00:00")
    )


async def test_two_operators_acknowledging_at_once_leave_exactly_one_claim(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    """The guard is the engine's, so it holds when the two calls actually overlap.

    The serial case above proves the second call is refused; this proves the refusal
    is not merely a property of arriving one after the other. Two facade calls are
    driven concurrently against the real engine, so both UPDATEs are in flight at
    once and the engine - not the caller - is what decides the order. Drop the
    ``status = 'open'`` guard and both claims are written, which is the outcome this
    test exists to rule out.
    """
    with _client(database_url) as client:
        alert_id = client.get(ALERTS_PATH, headers=_bearer()).json()["alerts"][0]["id"]

    facade = ObservabilityFacade(engine=rolled_engine)
    first, second = await asyncio.gather(
        facade.acknowledge_alert(alert_id=uuid.UUID(alert_id), acked_by=7),
        facade.acknowledge_alert(alert_id=uuid.UUID(alert_id), acked_by=9),
    )

    assert [first.already_acknowledged, second.already_acknowledged].count(False) == 1
    winner = first if not first.already_acknowledged else second
    row = await _alert_row(rolled_engine, "breaker_open")
    # The row carries the WINNER's operator, whichever coroutine that happened to be,
    # and both callers were handed the same standing claim.
    assert row["acked_by"] == winner.alert.acked_by
    assert {first.alert.acked_by, second.alert.acked_by} == {row["acked_by"]}


async def test_acknowledging_an_alert_that_does_not_exist_answers_not_found(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        response = client.post(f"{ALERTS_PATH}/{uuid.uuid4()}/acknowledge", headers=_bearer())

    assert response.status_code == 404
    assert response.json()["code"] == "ALERT_NOT_FOUND"


async def test_acknowledging_a_resolved_alert_is_refused_and_leaves_it_resolved(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        resolved = client.get(f"{ALERTS_PATH}?status=resolved", headers=_bearer()).json()
        response = client.post(
            f"{ALERTS_PATH}/{resolved['alerts'][0]['id']}/acknowledge", headers=_bearer()
        )

    assert response.status_code == 422
    assert response.json()["code"] == "ALERT_ALREADY_RESOLVED"
    assert (await _alert_row(rolled_engine, "outbox_dead_letter"))["status"] == "resolved"


async def test_the_acknowledgement_endpoint_refuses_anonymous_and_non_operator_callers(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        alert_id = client.get(ALERTS_PATH, headers=_bearer()).json()["alerts"][0]["id"]
        path = f"{ALERTS_PATH}/{alert_id}/acknowledge"

        assert client.post(path).status_code == 401
        assert client.post(path, headers=_bearer("patient")).status_code == 403

    # A refused call writes nothing: the row is exactly as it was seeded.
    assert await _alert_row(rolled_engine, "breaker_open") == {
        "status": "open",
        "acked_by": None,
        "acked_at": None,
    }


async def test_deeplinks_answer_the_configured_vendors(database_url: str) -> None:
    """The whole wire shape, against a real app and a real configured deployment."""
    with _client(
        database_url,
        grafana_url="https://caresetu.grafana.net",
        sentry_dsn="https://key@o4242.ingest.us-central1.sentry.io/7654321",
        langfuse_public_key="pk-lf-1234",
        langfuse_secret_key="sk-lf-1234",
        app_environment="staging",
    ) as client:
        body = client.get(DEEPLINKS_PATH, headers=_bearer()).json()

    assert body["grafana"]["dashboard_uid"] == "caresetu-observability"
    assert "var-env=staging" in body["grafana"]["dashboard_url"]
    assert "from=now-6h" in body["grafana"]["dashboard_url"]
    assert "explore_url" not in body["grafana"]
    assert body["sentry"] == {
        "project_id": "7654321",
        "issues_url": (
            "https://o4242.sentry.io/issues/?project=7654321&query=service%3A%22caresetu-api%22"
        ),
    }
    # Langfuse needs context to filter on, and this deployment supplied none.
    assert "langfuse" not in body


async def test_deeplinks_carry_the_platforms_own_trace_id_to_every_vendor(
    database_url: str,
) -> None:
    """One trace, three tools: the join key has to survive the whole round trip.

    The id is the one the error feed hands an operator, so the links below are the
    ones a click on that row produces.
    """
    with _client(
        database_url,
        grafana_url="https://caresetu.grafana.net",
        sentry_dsn="https://key@o4242.ingest.us-central1.sentry.io/7654321",
        langfuse_public_key="pk-lf-1234",
        langfuse_secret_key="sk-lf-1234",
    ) as client:
        body = client.get(
            DEEPLINKS_PATH,
            params={
                "trace_id": "c7f2a1b0d3e4f5061728394a5b6c7d8e",
                "model": "gpt-4o",
                "task_type": "draft",
                "error_type": "ValueError",
                "actor_key": "a" * 64,
                "session_key": "b" * 64,
            },
            headers=_bearer(),
        ).json()

    trace = "c7f2a1b0d3e4f5061728394a5b6c7d8e"
    assert body["trace_id"] == trace
    assert trace in body["grafana"]["explore_url"]
    assert trace in body["sentry"]["trace_url"]
    assert body["sentry"]["issues_url"].endswith(
        "query=service%3A%22caresetu-api%22%20error.type%3A%22ValueError%22"
    )
    assert body["langfuse"]["trace_url"].endswith(f"/trace/{trace}")
    assert "model=gpt-4o" in body["langfuse"]["traces_url"]
    assert "name=ai_draft_rx" in body["langfuse"]["traces_url"]
    assert body["langfuse"]["actor_url"].endswith(f"users?userId={'a' * 64}")
    assert body["langfuse"]["session_url"].endswith(f"sessions?sessionId={'b' * 64}")


async def test_deeplinks_with_no_vendor_configured_answer_absent_links(
    database_url: str,
) -> None:
    """No vendor configured is the default deployment; it must never be a 5xx.

    And it answers with nothing at all: the wire carries no ``grafana``/``sentry``/
    ``langfuse`` key, so a client cannot read "switched off" as "broken link".
    """
    with _client(database_url) as client:
        response = client.get(DEEPLINKS_PATH, headers=_bearer())

    assert response.status_code == 200
    assert response.json() == {}


async def test_c1b_routes_refuse_anonymous_and_non_operator_callers(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    with _client(database_url) as client:
        for path in (
            OVERVIEW_PATH,
            LATENCY_PATH,
            PROVIDERS_PATH,
            HEALTH_PATH,
            ALERTS_PATH,
            DEEPLINKS_PATH,
        ):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=_bearer("patient")).status_code == 403


# ------------------------------------------------------- B8 #726: the error stream
#
# The gateway error capture folds into THIS round trip rather than getting its own
# fixture (spec #717 Testing Decisions): driving a real 5xx through the real ASGI
# application, then draining the buffer, is the same seam reached through a
# different door - real migrations, real Postgres, the real module facade.


async def _captured_error_rows(engine: AsyncEngine) -> list[dict[str, object]]:
    """Every row the error stream holds, as plain dicts for assertion."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT fingerprint, route_template, method, status_code, status_class, "
                "kind, code, trace_id, occurrences, first_seen_at, last_seen_at "
                "FROM observability.observability_error_events "
                "ORDER BY route_template"
            )
        )
        return [dict(row) for row in result.mappings()]


async def test_a_real_server_error_drains_into_exactly_one_captured_record(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: one real 5xx through the real app, one row carrying the trace id.

    Driven end to end - the request raises inside a route, the catch-all seam
    answers 500 AND buffers, the worker's drain writes through the module facade -
    so the row exists only if every hop of the capture path works. Nothing here
    inserts a row directly.
    """
    reset_error_capture()

    with _failing_client(database_url) as client:
        response = client.get("/v1/cases/912/entries/boom", headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"

    report = await drain_error_buffer(engine)

    assert report.written == 1
    assert report.frequencies == 1
    (row,) = await _captured_error_rows(engine)
    assert row["route_template"] == "/v1/cases/{case_id}/entries/boom"
    # The concrete id the request carried never reaches telemetry.
    assert "912" not in str(row["route_template"])
    assert row["method"] == "GET"
    assert row["status_code"] == 500
    assert row["status_class"] == "5xx"
    assert row["kind"] == "unhandled_exception"
    assert row["code"] == "INTERNAL_SERVER_ERROR"
    assert row["trace_id"] == _TRACE_ID
    assert row["occurrences"] == 1
    assert row["first_seen_at"] == row["last_seen_at"]


async def test_the_buffer_is_empty_once_the_drain_has_persisted_it(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: what the drain wrote, the drain released - never twice."""
    reset_error_capture()

    with _failing_client(database_url) as client:
        client.get("/v1/cases/912/entries/boom")
    await drain_error_buffer(engine)

    assert pending_error_captures() == ()

    second = await drain_error_buffer(engine)

    assert second.written == 0
    assert len(await _captured_error_rows(engine)) == 1


async def test_repeated_identical_failures_collapse_onto_one_row_with_a_count(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: a loop is one entry with a count, not a wall burying every other error."""
    reset_error_capture()

    with _failing_client(database_url) as client:
        for _ in range(3):
            client.get("/v1/cases/912/entries/boom", headers={"X-Request-Id": _TRACE_ID})

    report = await drain_error_buffer(engine)

    assert (report.written, report.frequencies) == (3, 1)
    (row,) = await _captured_error_rows(engine)
    assert row["occurrences"] == 3


async def test_two_different_failures_stay_two_separate_entries(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: a fingerprint that merged everything would hide the failure it merged."""
    reset_error_capture()

    with _failing_client(database_url) as client:
        client.get("/v1/cases/912/entries/boom")
        client.get("/v1/cases/913/entries/boom")

    await drain_error_buffer(engine)

    rows = await _captured_error_rows(engine)
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 2

    reset_error_capture()
    with _failing_client(database_url) as client:
        client.get("/v1/cases/912/entries/unavailable")

    await drain_error_buffer(engine)

    rows = await _captured_error_rows(engine)
    assert sorted(row["route_template"] for row in rows) == [
        "/v1/cases/{case_id}/entries/boom",
        "/v1/cases/{case_id}/entries/unavailable",
    ]


async def test_a_handled_5xx_drains_under_its_own_kind(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: a 5xx a handler produced ITSELF reaches Postgres too.

    The trace seam is the half the exception seam cannot see - the handler caught
    nothing because nothing escaped - and it is the half with no envelope code to
    read. This drives that seam all the way to a row, because the capture being
    correct in memory says nothing about the upsert accepting a record whose
    ``code`` is empty and whose ``kind`` differs from the exception seam's.
    """
    reset_error_capture()

    with _failing_client(database_url) as client:
        response = client.get(
            "/v1/cases/912/entries/unavailable", headers={"X-Request-Id": _TRACE_ID}
        )

    assert response.status_code == 503
    report = await drain_error_buffer(engine)

    assert (report.written, report.frequencies) == (1, 1)
    (row,) = await _captured_error_rows(engine)
    assert row["kind"] == "server_error_response"
    assert row["status_code"] == 503
    assert row["status_class"] == "5xx"
    assert row["route_template"] == "/v1/cases/{case_id}/entries/unavailable"
    assert "912" not in str(row["route_template"])
    assert row["trace_id"] == _TRACE_ID
    # No envelope is read from the response body - the middleware exists to hand
    # that stream back untouched - so the code column carries the seam's fixed
    # empty default rather than a guess.
    assert row["code"] == ""


async def test_the_two_seams_produce_two_distinct_entries_for_one_failure(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: the seam is part of the fingerprint, or the two collapse into one.

    Both requests hit the SAME route and the same method and the same status, so the
    only thing separating the two records is ``kind`` - which is the point. An
    escaped exception and a handler-produced 5xx are different operational problems;
    without ``kind`` in the collapse key the operator gets one row whose count mixes
    them, and cannot tell whether the service raised or the handler gave up.
    """
    reset_error_capture()

    with _failing_client(database_url) as client:
        # First call: the handler raises, the catch-all seam captures it. Second:
        # the handler gives up by itself, the trace seam captures that.
        assert client.get("/v1/cases/912/entries/both-ways").status_code == 500
        assert client.get("/v1/cases/912/entries/both-ways").status_code == 503

    report = await drain_error_buffer(engine)

    assert (report.written, report.frequencies) == (2, 2)
    rows = await _captured_error_rows(engine)
    assert sorted(row["kind"] for row in rows) == [
        "server_error_response",
        "unhandled_exception",
    ]
    # Same route, same method - so kind is demonstrably what separated them.
    assert {str(row["route_template"]) for row in rows} == {"/v1/cases/{case_id}/entries/both-ways"}
    assert [row["status_code"] for row in rows] == [500, 503]


async def test_a_healthy_request_starts_no_record_and_no_drain_writes_nothing(
    engine: AsyncEngine, database_url: str
) -> None:
    """B8 #726: capture fires on failure only - otherwise the buffer is a request log."""
    reset_error_capture()

    with _failing_client(database_url) as client:
        assert client.get("/v1/cases/912/entries/fine").status_code == 200

    assert pending_error_captures() == ()
    report = await drain_error_buffer(engine)

    assert (report.written, report.frequencies) == (0, 0)
    assert await _captured_error_rows(engine) == []


# ------------------------------------------------- B9 #727: the per-minute counter
#
# The request counter folds into THIS round trip for the reason the error capture
# does (spec #717 Testing Decisions): drive real traffic through the real ASGI
# application, fold it through the module facade, then read ``/throughput`` back
# over the rows the capture actually produced. Nothing here inserts a counter row
# directly, so the row's shape, its unique key and the aggregate the read computes
# over it are all proven against each other.


def _counter_client(database_url: str) -> TestClient:
    """The real app plus routes that succeed and routes that fail, for the B9 fold.

    ``dispatcher_in_process_enabled=False`` so the lifespan does NOT start the
    worker: these tests drive the fold themselves, and a scheduled fold firing
    mid-test would be a race over the very map under assertion.

    ``raise_server_exceptions=False`` because Starlette's ``ServerErrorMiddleware``
    sends the envelope AND re-raises - a real client only sees the 500.
    """
    app = create_app(
        settings=Settings(
            database_url=database_url,
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_SIGNING_KEY,
            dispatcher_in_process_enabled=False,
        )
    )

    @app.get("/v1/cases/{case_id}/entries/fine")
    def fine() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/cases/{case_id}/entries/unavailable")
    def unavailable() -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})

    @app.get("/v1/cases/{case_id}/entries/boom")
    def boom(case_id: str) -> None:
        raise RuntimeError(f"database unavailable for case {case_id}")

    return TestClient(app, raise_server_exceptions=False)


async def _counter_rows(engine: AsyncEngine) -> list[dict[str, object]]:
    """Every row the per-minute counter holds, as plain dicts for assertion."""
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT minute_ts, route_template, method, status_class, requests, errors "
                "FROM observability.observability_http_minute "
                "ORDER BY route_template, status_class"
            )
        )
        return [dict(row) for row in result.mappings()]


async def test_a_burst_of_real_requests_folds_into_one_row_per_route_per_minute(
    engine: AsyncEngine, database_url: str
) -> None:
    """B9 #727: the grain, proven against Postgres rather than against a dict.

    Ten requests to one route inside one minute are ONE row. The obvious
    implementation - a record per request, as the error capture does - would write
    ten rows or ten upserts here and only show the difference under load; this
    assertion is about the row count, so it fails on the design.
    """
    reset_http_counter()

    with _counter_client(database_url) as client:
        for _ in range(10):
            assert client.get("/v1/cases/912/entries/fine").status_code == 200

    assert len(pending_http_counts()) == 1
    report = await drain_http_counter(engine)

    assert (report.series, report.requests) == (1, 10)
    (row,) = await _counter_rows(engine)
    assert row["route_template"] == "/v1/cases/{case_id}/entries/fine"
    # The concrete id the request carried never reaches telemetry.
    assert "912" not in str(row["route_template"])
    assert row["method"] == "GET"
    assert row["status_class"] == "2xx"
    assert row["requests"] == 10
    assert row["errors"] == 0
    assert row["minute_ts"].second == 0


async def test_the_stored_error_numerator_is_the_server_error_subset(
    engine: AsyncEngine, database_url: str
) -> None:
    """B9 #727: 500 and 503 on one route are one ``5xx`` series, and it carries the errors.

    Three failures of two different codes and one success, so the rate the read
    reports can only be ``3 of 4`` if the numerator really is the stored 5xx subset
    rather than a second scan - or the raw codes leaking into the series.
    """
    reset_http_counter()

    with _counter_client(database_url) as client:
        assert client.get("/v1/cases/912/entries/unavailable").status_code == 503
        assert client.get("/v1/cases/912/entries/boom").status_code == 500
        assert client.get("/v1/cases/912/entries/fine").status_code == 200

    await drain_http_counter(engine)

    rows = {
        (str(row["route_template"]), str(row["status_class"])): row
        for row in await _counter_rows(engine)
    }
    success = rows[("/v1/cases/{case_id}/entries/fine", "2xx")]
    produced = rows[("/v1/cases/{case_id}/entries/unavailable", "5xx")]
    escaped = rows[("/v1/cases/{case_id}/entries/boom", "5xx")]
    assert (success["requests"], success["errors"]) == (1, 0)
    assert (produced["requests"], produced["errors"]) == (1, 1)
    assert (escaped["requests"], escaped["errors"]) == (1, 1)


async def test_throughput_reports_the_folded_traffic_over_the_recent_past(
    engine: AsyncEngine, database_url: str
) -> None:
    """B9 #727: the whole path - real requests, real fold, real aggregate read.

    Nothing is inserted by hand, so the numbers the operator would see can only
    exist if the capture, the fold and the read agree.
    """
    reset_http_counter()
    reset_error_capture()

    with _counter_client(database_url) as client:
        for _ in range(9):
            client.get("/v1/cases/912/entries/fine")
        assert client.get("/v1/cases/912/entries/unavailable").status_code == 503
        assert client.get("/v1/cases/912/entries/boom").status_code == 500

    await drain_http_counter(engine)

    with _client(database_url) as client:
        body = client.get(THROUGHPUT_PATH, headers=_bearer()).json()

    assert body["minutes"] == 60
    assert body["requests"] == 11
    assert body["errors"] == 2
    assert body["error_rate"] == "0.1818"
    assert len(body["points"]) == 1
    (point,) = body["points"]
    assert (point["requests"], point["errors"], point["error_rate"]) == (11, 2, "0.1818")
    assert body["routes_total"] == 3
    assert [
        (row["route_template"], row["method"], row["requests"], row["errors"])
        for row in body["routes"]
    ] == [
        ("/v1/cases/{case_id}/entries/fine", "GET", 9, 0),
        ("/v1/cases/{case_id}/entries/boom", "GET", 1, 1),
        ("/v1/cases/{case_id}/entries/unavailable", "GET", 1, 1),
    ]
    assert body["capture"] == {
        "capturing": True,
        "requests_recorded": 11,
        "last_recorded_at": point["minute_ts"],
    }


async def test_throughput_reports_no_capture_when_nothing_was_recorded(
    engine: AsyncEngine, database_url: str
) -> None:
    """B9 #727: the interesting case is NO requests, and it must not read as healthy.

    Every rate is ``null`` and ``capturing`` is false. A body of ``0`` and
    ``"0.0000"`` would be the same numbers as a clean hour and would say nothing
    about whether anything was watching - which is the failure the whole
    capture-liveness block exists to prevent (#717 story 35).
    """
    reset_http_counter()

    with _client(database_url) as client:
        body = client.get(THROUGHPUT_PATH, headers=_bearer()).json()

    assert body["requests"] == 0
    assert body["errors"] == 0
    assert body["error_rate"] is None
    assert body["requests_per_minute"] is None
    assert body["points"] == []
    assert body["routes"] == []
    assert body["routes_total"] == 0
    assert body["capture"] == {
        "capturing": False,
        "requests_recorded": 0,
        "last_recorded_at": None,
    }


async def test_throughput_narrows_to_the_requested_minute_window(
    engine: AsyncEngine, database_url: str
) -> None:
    """A minute-grain read honours a minute param, and a shorter one still counts.

    Seeded at minutes the READ will resolve against, computed here rather than at
    import: a module-level stamp would drift a minute as the file runs and the
    narrow window would become a coin flip.
    """
    reset_http_counter()
    current_minute = datetime.now(UTC).replace(second=0, microsecond=0)
    async with engine.begin() as connection:
        for offset, count in ((-5, 4), (0, 7)):
            await connection.execute(
                text(
                    "INSERT INTO observability.observability_http_minute "
                    "(minute_ts, route_template, method, status_class, requests, errors) "
                    "VALUES (:minute_ts, '/v1/cases/{case_id}/entries/fine', 'GET', '2xx', "
                    ":requests, 0)"
                ),
                {"minute_ts": current_minute + timedelta(minutes=offset), "requests": count},
            )

    with _client(database_url) as client:
        wide = client.get(THROUGHPUT_PATH, headers=_bearer()).json()
        narrow = client.get(f"{THROUGHPUT_PATH}?minutes=2", headers=_bearer()).json()

    assert wide["requests"] == 11
    assert len(wide["points"]) == 2
    assert narrow["minutes"] == 2
    assert narrow["requests"] == 7
    assert len(narrow["points"]) == 1


async def test_a_folded_minute_is_not_written_twice(engine: AsyncEngine, database_url: str) -> None:
    """B9 #727: the counter is released after the commit, so a second fold adds nothing.

    The release is what makes the retry exact. A counter whose deltas were
    double-released would inflate throughput permanently and invisibly, which is the
    opposite of the error stream's re-count - and this row's count would be 6 instead
    of 3.
    """
    reset_http_counter()

    with _counter_client(database_url) as client:
        for _ in range(3):
            client.get("/v1/cases/912/entries/fine")

    await drain_http_counter(engine)
    assert pending_http_counts() == ()
    second = await drain_http_counter(engine)

    assert (second.series, second.requests) == (0, 0)
    (row,) = await _counter_rows(engine)
    assert row["requests"] == 3


async def test_the_throughput_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    assert _client(database_url).get(THROUGHPUT_PATH).status_code == 401
    assert _client(database_url).get(THROUGHPUT_PATH, headers=_bearer("patient")).status_code == 403


# --------------------------------------------------- B5 #729: the reliability board


async def _seed_queue(connection: AsyncConnection) -> None:
    """Two open AI jobs across two queues, as a stalled leg leaves them.

    Rows are inserted exactly as the ``ai_job.queued`` handler writes them, so the
    read is exercised against what the consumer really persists rather than a
    hand-shaped stand-in. ``structure`` holds the OLD job - the one an operator has
    to find - and ``draft`` holds a fresh one, so the board has to report the age of
    the worst queue and not the average of the two.
    """
    await connection.execute(
        text(
            "INSERT INTO observability.observability_ai_queue_open "
            "(ai_job_ref, queue, enqueued_at) VALUES "
            "(9001, 'structure', now() - interval '40 minutes'), "
            "(9002, 'structure', now() - interval '3 minutes'), "
            "(9003, 'draft', now() - interval '2 minutes')"
        )
    )


async def _seed_activity(connection: AsyncConnection) -> None:
    """Three consumed events: two actors inside the window, one well before it."""
    recent = datetime.now(UTC)
    rows = [
        (
            uuid.uuid4(),
            "ai_job.queued",
            recent - timedelta(minutes=5),
            actor_key(ACTOR_KIND_PATIENT, 101),
        ),
        (
            uuid.uuid4(),
            "ai_job.completed",
            recent - timedelta(minutes=1),
            actor_key(ACTOR_KIND_PATIENT, 101),
        ),
        (
            uuid.uuid4(),
            "ai_job.queued",
            recent - timedelta(minutes=2),
            actor_key(ACTOR_KIND_PATIENT, 202),
        ),
        # A patient the operator saw an hour ago and again yesterday: the window is
        # the only thing separating them from the two active patients above.
        (
            uuid.uuid4(),
            "ai_job.queued",
            recent - timedelta(hours=20),
            actor_key(ACTOR_KIND_PATIENT, 303),
        ),
        # Same actor twice in the window, on two different events - one actor, once.
        (
            uuid.uuid4(),
            "ai_job.queued",
            recent - timedelta(minutes=3),
            actor_key(ACTOR_KIND_PATIENT, 202),
        ),
    ]
    for event_id, event_type, processed_at, hashed in rows:
        await connection.execute(
            text(
                "INSERT INTO observability.consumed_events "
                "(event_id, event_type, processed_at, handler_result) VALUES "
                "(:event_id, :event_type, :processed_at, CAST(:result AS jsonb))"
            ),
            {
                "event_id": event_id,
                "event_type": event_type,
                "processed_at": processed_at,
                "result": json.dumps({"handler": "record", "actor_key": hashed}),
            },
        )


@pytest_asyncio.fixture
async def reliable_engine(rolled_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The rolled engine plus the queue rows and the actor-keyed activity ledger."""
    async with rolled_engine.begin() as connection:
        await _seed_queue(connection)
        await _seed_activity(connection)
    yield rolled_engine


async def test_reliability_reports_queue_depth_oldest_age_and_the_seeded_outbox(
    reliable_engine: AsyncEngine, database_url: str
) -> None:
    """Depth and age come from the open-job rows; backlog from every module's outbox.

    The ``structure`` queue is the one that matters and the depth number alone hides
    it - two rows is nothing - so the oldest age has to be reported alongside it, and
    the outbox figures have to match ``/health`` rather than tell a second story.
    """
    with _client(database_url) as client:
        body = client.get(RELIABILITY_PATH, headers=_bearer()).json()

    queues = {row["queue"]: row for row in body["queues"]}
    assert set(queues) == {"structure", "draft"}
    assert queues["structure"]["depth"] == 2
    assert queues["draft"]["depth"] == 1
    # The worst queue's age drives the headline figure, in whole seconds.
    assert 2_300 <= body["oldest_queued_age_s"] <= 2_430
    assert body["oldest_queued_age_s"] == max(row["oldest_age_s"] for row in body["queues"])

    # Every module's outbox is listed, exactly as ``/health`` serves it, and only
    # intake is stuck.
    intake = next(row for row in body["outbox"] if row["table"] == "intake_outbox")
    assert (intake["pending"], intake["inflight"], intake["dead_letter"]) == (2, 1, 1)
    assert all(row["backlog"] == 0 for row in body["outbox"] if row["table"] != "intake_outbox")
    assert (body["outbox_backlog"], body["dead_letter_rows"]) == (3, 1)


async def test_reliability_counts_distinct_actors_inside_the_requested_window(
    reliable_engine: AsyncEngine, database_url: str
) -> None:
    """Activity is counted from MOD-013's own ledger, deduplicated per actor.

    Five consumed events were seeded, but they belong to three patients and the
    60-minute window only reaches two of them - patient 101 (twice) and patient 202
    (twice). A row event count would say five; a per-event count would say four.
    """
    with _client(database_url) as client:
        body = client.get(RELIABILITY_PATH, headers=_bearer()).json()

    assert body["recent_active_actors"] == 2
    assert body["activity_window_minutes"] == 60

    # Patient 303's only event is 20 hours old, so a longer window finds them.
    with _client(database_url) as client:
        wide = client.get(f"{RELIABILITY_PATH}?minutes=1440", headers=_bearer()).json()

    assert wide["recent_active_actors"] == 3
    assert wide["activity_window_minutes"] == 1440
    # Widening the window cannot move the queue figures; they are not windowed.
    assert wide["queues"] == body["queues"]


async def test_reliability_links_to_the_tracing_backend_and_stores_no_concurrency(
    reliable_engine: AsyncEngine, database_url: str
) -> None:
    """Concurrency is a LINK, not a number - and never a column.

    The in-flight gauge lives in the tracing backend, which cannot be read from
    Postgres. The board therefore hands the operator a deep link with the metric
    expression in it, and the response itself carries no concurrency figure at all
    rather than a stale or invented one.
    """
    with _client(database_url, grafana_url="http://grafana.internal:3000") as client:
        body = client.get(RELIABILITY_PATH, headers=_bearer()).json()

    link = body["concurrency_grafana_link"]
    assert link is not None and link.startswith("http://grafana.internal:3000/explore?left=")
    explore = json.loads(unquote(link.split("left=", 1)[1]))
    assert explore["queries"][0]["expr"] == "caresetu.http.server.inflight"
    assert "concurrency" not in body


async def test_reliability_without_a_configured_tracing_backend_answers_no_link(
    reliable_engine: AsyncEngine, database_url: str
) -> None:
    """No configured Grafana is a missing affordance, not a broken read."""
    with _client(database_url) as client:
        body = client.get(RELIABILITY_PATH, headers=_bearer()).json()

    assert body["concurrency_grafana_link"] is None


async def test_reliability_is_empty_before_any_job_is_queued(
    rolled_engine: AsyncEngine, database_url: str
) -> None:
    """A fresh deployment reads zero everywhere rather than erroring.

    No open job means no queue rows at all - the board must report an empty queue
    list, zero activity, and no oldest age rather than inventing a queue or raising
    on the missing minimum.
    """
    with _client(database_url) as client:
        body = client.get(RELIABILITY_PATH, headers=_bearer()).json()

    assert (body["queues"], body["oldest_queued_age_s"]) == ([], None)
    assert body["recent_active_actors"] == 0
    assert body["outbox_backlog"] == 3


async def test_the_reliability_route_refuses_a_window_outside_its_bounds(
    database_url: str,
) -> None:
    """The window is clamped by the contract: 1..1440 minutes, 422 outside."""
    with _client(database_url) as client:
        assert client.get(f"{RELIABILITY_PATH}?minutes=0", headers=_bearer()).status_code == 422
        assert client.get(f"{RELIABILITY_PATH}?minutes=1441", headers=_bearer()).status_code == 422


async def test_the_reliability_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    assert _client(database_url).get(RELIABILITY_PATH).status_code == 401
    forbidden = _client(database_url).get(RELIABILITY_PATH, headers=_bearer("patient"))
    assert forbidden.status_code == 403


# ------------------------------------------------------- B8 #730: the error feed
#
# Served from Postgres because Postgres is the system of record: Sentry stays a crash
# tracker and a deep-link target, and nothing here queries it (spec #717 Out of
# Scope). Every row is produced by driving a REAL 5xx through the real ASGI
# application and draining through the module facade, then read back through the
# operator HTTP API - so the aggregate is proven over the exact shape the capture
# writes rather than a hand-written seed.


async def _fail_and_drain(database_url: str, engine: AsyncEngine, *paths: str) -> None:
    """Drive each failing path through the real app, then drain the real buffer."""
    with _failing_client(database_url) as client:
        for path in paths:
            client.get(path, headers={"X-Request-Id": _TRACE_ID})
    await drain_error_buffer(engine)


async def _age_the_entry_named(engine: AsyncEngine, route_template: str, *, hours: int) -> None:
    """Move one captured failure's last sighting back, standing in for elapsed time.

    There is no clock a test can wait on, and the capture seam stamps every record
    with the moment it happened. Aging the stored sighting is the only way to put a
    failure OUTSIDE the read's window without faking the capture itself - and it is
    precisely what three passing hours would have done to that column.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE observability.observability_error_events "
                "SET last_seen_at = last_seen_at - make_interval(hours => :hours) "
                "WHERE route_template = :route"
            ),
            {"hours": hours, "route": route_template},
        )


async def test_the_error_feed_serves_what_the_capture_actually_collapsed(
    engine: AsyncEngine, database_url: str
) -> None:
    """Four failures of two kinds are two entries, and the counts say four.

    The point of the read is that the count is not lost: three identical failures and
    one different one produce four occurrences over two entries, and a client has to
    be able to say which number it is looking at.
    """
    reset_error_capture()

    await _fail_and_drain(
        database_url,
        engine,
        "/v1/cases/912/entries/boom",
        "/v1/cases/912/entries/boom",
        "/v1/cases/913/entries/boom",
        "/v1/cases/912/entries/unavailable",
    )

    with _client(database_url) as client:
        body = client.get(ERRORS_PATH, headers=_bearer()).json()

    assert (body["total_count"], body["total_occurrences"]) == (2, 4)
    assert body["window_minutes"] == 60
    # Newest sighting first, so the failure still happening leads the feed.
    newest, oldest = body["errors"]
    assert (newest["occurrences"], oldest["occurrences"]) == (1, 3)
    assert newest["route_template"] == "/v1/cases/{case_id}/entries/unavailable"
    assert newest["status_code"] == 503
    assert oldest["route_template"] == "/v1/cases/{case_id}/entries/boom"
    assert oldest["method"] == "GET"
    assert oldest["status_class"] == "5xx"
    assert oldest["kind"] == "unhandled_exception"
    assert oldest["code"] == "INTERNAL_SERVER_ERROR"
    # The caller-presented trace survives capture AND the read.
    assert {entry["trace_id"] for entry in body["errors"]} == {_TRACE_ID}


async def test_the_error_feed_never_carries_a_concrete_request_path(
    engine: AsyncEngine, database_url: str
) -> None:
    """The identifiers the two failing requests differed by are nowhere on the wire."""
    reset_error_capture()

    await _fail_and_drain(
        database_url,
        engine,
        "/v1/cases/912/entries/boom",
        "/v1/cases/913/entries/boom",
    )

    with _client(database_url) as client:
        body = client.get(ERRORS_PATH, headers=_bearer()).json()

    # Two different case ids, one entry - collapsed, and carrying neither.
    assert body["total_count"] == 1
    (entry,) = body["errors"]
    assert entry["route_template"] == "/v1/cases/{case_id}/entries/boom"
    assert "912" not in json.dumps(body)
    assert "913" not in json.dumps(body)


async def test_the_error_feed_pages_a_long_failure_run(
    engine: AsyncEngine, database_url: str
) -> None:
    """Navigable, and the totals describe the whole filter rather than the page."""
    reset_error_capture()

    await _fail_and_drain(
        database_url,
        engine,
        "/v1/cases/912/entries/boom",
        "/v1/cases/912/entries/unavailable",
        "/v1/cases/912/entries/both-ways",
        "/v1/cases/912/entries/both-ways",
    )

    with _client(database_url) as client:
        first = client.get(f"{ERRORS_PATH}?page_size=2", headers=_bearer()).json()
        second = client.get(f"{ERRORS_PATH}?page=2&page_size=2", headers=_bearer()).json()

    assert len(first["errors"]) == 2
    assert len(second["errors"]) == 2
    # Four calls, four DISTINCT failures: ``both-ways`` raised on one call and gave
    # up on the next, and ``kind`` is what keeps those two apart rather than merging
    # them into one entry whose count cannot say which happened.
    assert first["total_count"] == second["total_count"] == 4
    assert first["total_occurrences"] == second["total_occurrences"] == 4
    # The two pages do not overlap.
    assert not {e["fingerprint"] for e in first["errors"]} & {
        e["fingerprint"] for e in second["errors"]
    }


async def test_the_error_feed_separates_a_live_failure_from_one_that_stopped(
    engine: AsyncEngine, database_url: str
) -> None:
    """The open/resolved split, which is what makes a live problem separable.

    Nothing marks a captured error handled, so the split is recency: a failure seen
    three hours ago is history, one seen moments ago is not. Both filters are asked
    for explicitly, because an unfiltered page that mixes the two is the thing an
    operator has to page through to get around.
    """
    reset_error_capture()

    await _fail_and_drain(
        database_url,
        engine,
        "/v1/cases/912/entries/boom",
        "/v1/cases/912/entries/unavailable",
    )
    await _age_the_entry_named(engine, "/v1/cases/{case_id}/entries/unavailable", hours=3)

    with _client(database_url) as client:
        unfiltered = client.get(ERRORS_PATH, headers=_bearer()).json()
        live = client.get(f"{ERRORS_PATH}?status=open", headers=_bearer()).json()
        handled = client.get(f"{ERRORS_PATH}?status=resolved", headers=_bearer()).json()

    assert unfiltered["total_count"] == 2
    assert live["total_count"] == 1
    assert handled["total_count"] == 1
    assert live["errors"][0]["route_template"] == "/v1/cases/{case_id}/entries/boom"
    assert live["errors"][0]["status"] == "open"
    assert handled["errors"][0]["route_template"] == "/v1/cases/{case_id}/entries/unavailable"
    assert handled["errors"][0]["status"] == "resolved"
    # Each page's own entries agree with the filter that selected them.
    assert {e["status"] for e in live["errors"]} == {"open"}
    assert {e["status"] for e in handled["errors"]} == {"resolved"}


async def test_widening_the_error_feed_window_reopens_an_aged_failure(
    engine: AsyncEngine, database_url: str
) -> None:
    """The window is the read's whole notion of live, so it has to be a parameter.

    A nightly batch's failure is still yesterday's problem at lunchtime; a fixed
    one-hour default would hide it exactly when someone is looking for it.
    """
    reset_error_capture()

    await _fail_and_drain(database_url, engine, "/v1/cases/912/entries/boom")
    await _age_the_entry_named(engine, "/v1/cases/{case_id}/entries/boom", hours=3)

    with _client(database_url) as client:
        narrow = client.get(f"{ERRORS_PATH}?status=open", headers=_bearer()).json()
        wide = client.get(f"{ERRORS_PATH}?status=open&minutes=240", headers=_bearer()).json()

    assert narrow["total_count"] == 0
    assert narrow["errors"] == []
    assert wide["total_count"] == 1
    assert wide["window_minutes"] == 240
    assert wide["errors"][0]["status"] == "open"


async def test_the_error_feed_is_empty_before_anything_has_failed(
    engine: AsyncEngine, database_url: str
) -> None:
    """A fresh deployment reads an empty page rather than erroring.

    Empty is NOT the same as healthy - only ``/throughput``'s capture block says
    which - so the page carries no verdict of its own to get wrong. ``engine`` is
    requested for its truncation, not for anything it does: "before anything has
    failed" has to mean an emptied table, not an ordering accident.
    """
    del engine
    with _client(database_url) as client:
        body = client.get(ERRORS_PATH, headers=_bearer()).json()

    assert body == {
        "errors": [],
        "total_count": 0,
        "total_occurrences": 0,
        "window_minutes": 60,
    }


async def test_the_error_feed_route_refuses_a_window_outside_its_bounds(
    database_url: str,
) -> None:
    """The window is clamped by the contract: 1..1440 minutes, 422 outside."""
    with _client(database_url) as client:
        assert client.get(f"{ERRORS_PATH}?minutes=0", headers=_bearer()).status_code == 422
        assert client.get(f"{ERRORS_PATH}?minutes=1441", headers=_bearer()).status_code == 422


async def test_the_error_feed_route_refuses_an_unrecognised_status(
    database_url: str,
) -> None:
    """A typo must not 200 with an empty page, which reads as "nothing is failing"."""
    with _client(database_url) as client:
        response = client.get(f"{ERRORS_PATH}?status=acknowledged", headers=_bearer())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_the_error_feed_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    """The tenth read, behind the same flat operator requirement as the other nine."""
    assert _client(database_url).get(ERRORS_PATH).status_code == 401
    forbidden = _client(database_url).get(ERRORS_PATH, headers=_bearer("patient"))
    assert forbidden.status_code == 403


# ------------------------------------------------------------------ business
#
# ``/business`` resolves its own clock - the facade owns it, as it does for every
# windowed read - so this fixture is anchored to the day the test RUNS rather than to
# a pinned date. A pinned date would fall outside the window on every run but one,
# and a suite that only passes on a Tuesday is not a suite.


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return start, end


#: One month of spend per PATIENT, as the #725 rollup writes it: today carries three
#: scopes, the first of the month carries a fourth. The doctor row at the bottom
#: mirrors the ``draft`` patient's figures EXACTLY, because that is what the rollup
#: writes for a job whose doctor is known - one rupee recorded against the two actors
#: the business reads need it against, not two halves of the bill.
_ATTRIBUTION_SEED = """
    INSERT INTO observability.observability_attribution_daily
    (usage_date, actor_kind, actor_key, provider, model, task_type, jobs,
     completed_jobs, failed_jobs, input_tokens, output_tokens, cost_paise) VALUES
    (:today, :patient, :p1, 'openai', 'gpt-4o-mini', 'transcribe', 3, 3, 0, 300000, 30000, 60000),
    (:today, :patient, :p2, 'openai', 'gpt-4o-mini', 'draft',       2, 2, 0,  40000, 20000, 20000),
    (:today, :patient, :p3, 'anthropic', 'claude-3-5-haiku', 'structure',
     5, 4, 1, 100000, 0, 10000),
    (:today, :doctor, :d1, 'openai', 'gpt-4o-mini', 'draft', 2, 2, 0, 40000, 20000, 20000),
    (:month_start, :patient, :p4, 'anthropic', 'claude-3-5-haiku', 'transcribe',
     1, 1, 0, 10000, 1000, 2000)
"""

_TODAY_SPEND_PAISE = 90_000
_MONTH_SPEND_PAISE = 2_000
_BUSINESS_CAP_PAISE = 150_000

#: The recorded care-attribution edges (#724) that let the business read answer "which
#: doctor was this patient's cost attributed to". ``patient_key(ACTOR_KIND_PATIENT,
#: 102)`` is exactly the actor ``p2`` above, and ``doctor-a`` is the doctor whose row
#: mirrors p2's figures - which is what makes this the reconciliation fixture rather
#: than decoration: if the rollup stopped mirroring, the per-patient and per-doctor
#: figures would stop agreeing and the test that says so would fail.
_BUSINESS_EDGE_SEED = """
    INSERT INTO observability.observability_care_attribution_edges
    (intake_ref, patient_key, doctor_key, event_id, assigned_at) VALUES
    (9001, :p2, :d1, gen_random_uuid(), now())
"""
#: The snapshot's month-to-date figure. Set to the aggregate's own month-to-date sum
#: because that is what the rollup writes - one ``_load_period_spend`` feeding the
#: snapshot, one ``build_attribution_daily`` feeding the aggregate, both off the same
#: per-job rows - so a fixture where the two disagree would be testing a state the
#: rollup cannot produce.
_BUSINESS_CONSUMED_PAISE = _TODAY_SPEND_PAISE + _MONTH_SPEND_PAISE


@pytest_asyncio.fixture
async def attributed_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The daily per-actor aggregate and the budget snapshot the business read reads."""
    today = _utc_today()
    month_start, month_end = _month_bounds(today)
    keys = {
        "today": today,
        "month_start": month_start,
        "patient": ACTOR_KIND_PATIENT,
        "doctor": ACTOR_KIND_DOCTOR,
        "p1": actor_key(ACTOR_KIND_PATIENT, 101),
        "p2": actor_key(ACTOR_KIND_PATIENT, 102),
        "p3": actor_key(ACTOR_KIND_PATIENT, 103),
        "p4": actor_key(ACTOR_KIND_PATIENT, 104),
        "d1": actor_key(ACTOR_KIND_DOCTOR, 201),
    }
    async with engine.begin() as connection:
        await connection.execute(text(_ATTRIBUTION_SEED), keys)
        await connection.execute(text(_BUSINESS_EDGE_SEED), keys)
        await connection.execute(
            text(
                "INSERT INTO observability.observability_ai_cost_budget "
                "(provider, model, monthly_limit_paise, alert_threshold_pct, "
                "current_spend_paise, billing_period_start, billing_period_end) "
                "VALUES ('openai', 'gpt-4o-mini', :cap, 80, :spent, :start, :end)"
            ),
            {
                "cap": _BUSINESS_CAP_PAISE,
                "spent": _BUSINESS_CONSUMED_PAISE,
                "start": month_start,
                "end": month_end,
            },
        )
    yield engine


def _business_body(database_url: str, period: str | None = None) -> dict[str, Any]:
    path = BUSINESS_PATH if period is None else f"{BUSINESS_PATH}?period={period}"
    with _client(database_url) as client:
        return client.get(path, headers=_bearer()).json()


def _expected_projection(today: date) -> tuple[int, int, int]:
    """The straight-line month-end burn this read should report, and its day counts.

    Derived here rather than pinned: the seed's billing period is the REAL current
    month, so the elapsed-day count moves with the calendar and a hard-coded paise
    figure would only hold on one day of it. What is pinned is the ARITHMETIC - the
    projection must be the consumed figure scaled by period/elapsed days - which is
    the part that could actually be wrong.
    """
    month_start, month_end = _month_bounds(today)
    elapsed = (today - month_start).days + 1
    period_days = (month_end - month_start).days + 1
    projected = (
        Decimal(_BUSINESS_CONSUMED_PAISE) * Decimal(period_days) / Decimal(elapsed)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(projected), elapsed, period_days


async def test_the_business_read_reports_todays_spend_and_its_breakdown(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """The headline is the seeded sum over the PERIOD, and the breakdowns reconcile.

    Wire decimals arrive as strings at their stated scale (api-standards §3), which is
    what the frontend already parses for the other reads.
    """
    del attributed_engine
    today = _utc_today()
    body = _business_body(database_url, "today")

    assert body["period"] == "today"
    assert (body["period_start"], body["period_end"]) == (today.isoformat(), today.isoformat())
    assert body["spend_paise"] == _TODAY_SPEND_PAISE
    assert body["jobs"] == 10
    assert body["input_tokens"] == 440_000
    assert body["output_tokens"] == 50_000
    # Each side at its own denominator: 90,000 over 440,000 and over 50,000.
    assert body["paise_per_1k_input_tokens"] == "204.5455"
    assert body["paise_per_1k_output_tokens"] == "1800.0000"
    assert [(row["provider"], row["jobs"], row["spend_paise"]) for row in body["by_provider"]] == [
        ("anthropic", 5, 10_000),
        ("openai", 5, 80_000),
    ]
    # Two models under one provider: "by model WITHIN a provider", not a flat model list.
    assert [(row["provider"], row["model"]) for row in body["by_model"]] == [
        ("anthropic", "claude-3-5-haiku"),
        ("openai", "gpt-4o-mini"),
    ]
    assert [row["task_type"] for row in body["by_task_type"]] == [
        "draft",
        "structure",
        "transcribe",
    ]
    for breakdown in ("by_provider", "by_model", "by_task_type"):
        assert sum(row["spend_paise"] for row in body[breakdown]) == _TODAY_SPEND_PAISE
    # ``structure`` recorded no output tokens: nothing to price, not "free output".
    structure = next(row for row in body["by_task_type"] if row["task_type"] == "structure")
    assert structure["output_tokens"] == 0
    assert structure["paise_per_1k_output_tokens"] is None


async def test_the_business_read_does_not_count_a_doctor_row_twice(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """The seed carries a doctor row mirroring the ``draft`` patient's figures.

    The rollup writes one row per ACTOR, so the same rupee appears under both the
    patient and the doctor who served the case. Summing both kinds would double the
    bill this read exists to explain, which is why the actor kind is a filter on the
    money rather than a grouping dimension.
    """
    del attributed_engine
    body = _business_body(database_url, "today")

    draft = next(row for row in body["by_task_type"] if row["task_type"] == "draft")
    # 2 jobs and 20,000 paise - the patient's figures, not 4 jobs and 40,000.
    assert (draft["jobs"], draft["spend_paise"]) == (2, 20_000)


async def test_one_business_endpoint_serves_the_three_period_windows(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """Today, week-to-date and month-to-date are three WINDOWS of one read.

    This is the acceptance criterion three separate reads would fail: one route, one
    response, three windows - each ending today and differing only in where it
    starts. The seeded first-of-the-month spend is what makes the wider windows
    visibly wider than ``today``.
    """
    del attributed_engine
    today = _utc_today()
    month_start, _ = _month_bounds(today)
    week_start = today - timedelta(days=today.weekday())

    today_body = _business_body(database_url, "today")
    week_body = _business_body(database_url, "week_to_date")
    month_body = _business_body(database_url, "month_to_date")

    assert (today_body["period_start"], today_body["period_end"]) == (
        today.isoformat(),
        today.isoformat(),
    )
    assert (week_body["period_start"], week_body["period_end"]) == (
        week_start.isoformat(),
        today.isoformat(),
    )
    assert (month_body["period_start"], month_body["period_end"]) == (
        month_start.isoformat(),
        today.isoformat(),
    )
    assert today_body["spend_paise"] == _TODAY_SPEND_PAISE
    assert month_body["spend_paise"] == _TODAY_SPEND_PAISE + _MONTH_SPEND_PAISE
    # The week reaches the 1st only when the 1st falls on or after this Monday; on a
    # Monday - and on a month whose first day sits in the previous ISO week - the week
    # window is today's alone, which is the correct answer rather than a missing row.
    week_covers_month_start = week_start <= month_start <= today
    assert week_body["spend_paise"] == _TODAY_SPEND_PAISE + (
        _MONTH_SPEND_PAISE if week_covers_month_start else 0
    )


async def test_the_business_read_reports_the_cap_and_the_projected_burn_together(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """Cap, consumed and projection arrive in the SAME response - the warning shape.

    The point is that a panel asking for ``today`` still learns where the MONTH lands:
    an operator who only sees today's rupee figure finds out about the cap on the last
    day of the month, which is the outcome the projection exists to prevent.
    """
    del attributed_engine
    today = _utc_today()
    projected, elapsed, period_days = _expected_projection(today)

    body = _business_body(database_url, "today")

    assert body["monthly_cap_paise"] == _BUSINESS_CAP_PAISE
    # The consumed figure is READ off the budget snapshot, not recomputed from the
    # aggregate - it is the same number ``/cost`` and the ``ai_budget`` alert use, and
    # the rollup writes it from the same per-job rows the aggregate is built from, so
    # one bill reaches the operator however they ask for it.
    assert body["cap_consumed_paise"] == _BUSINESS_CONSUMED_PAISE
    assert body["cap_consumed_pct"] == "61.33"
    assert body["projected_month_end_paise"] == projected
    assert body["projection_basis"] == {
        "period_start": _month_bounds(today)[0].isoformat(),
        "period_end": _month_bounds(today)[1].isoformat(),
        "elapsed_days": elapsed,
        "period_days": period_days,
    }
    # The flag is asserted as TRACKING the two figures beside it, not as a fixed
    # value: a straight line from 92,000 consumed is over a 150,000 cap for most of a
    # month and back under it on the last day, so the only claim that holds whatever
    # day this runs is that the flag is derived from the projection and the cap and
    # from nothing else. The two fixed-date cases in the facade unit tests pin the
    # healthy and over-cap verdicts themselves.
    assert body["projected_over_cap"] is (projected > _BUSINESS_CAP_PAISE)


async def test_the_business_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    """This read sits behind the same flat operator requirement as the other reads."""
    assert _client(database_url).get(BUSINESS_PATH).status_code == 401
    forbidden = _client(database_url).get(BUSINESS_PATH, headers=_bearer("patient"))
    assert forbidden.status_code == 403


async def test_the_business_read_divides_the_bill_by_each_unit_of_value(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """What one unit of value costs, derived per request rather than stored.

    The seeded month carries 90,000 paise over 10 jobs of which 9 completed, and every
    figure below is that division and no other: 9,000 paise per request over ALL ten
    (the bill pays for the failure too), 10,000 per completed task over the nine that
    finished, 30,000 per patient over the three in the window, and cost-of-pass at
    10,000 - spend per successful outcome, which is the named metric and NOT the
    per-request figure.

    Cost per doctor is the odd one out at 20,000 rather than 90,000, and the difference
    is the point: only the 20,000 the recorded edge attributes reaches a doctor, so
    dividing the whole bill by the doctor count would quote a figure larger than any
    doctor's own row. The unattributed 70,000 stays visible as the gap between
    ``patient_spend.total_spend_paise`` and ``doctor_spend.total_spend_paise``.

    Quoted decimals arrive as strings at the rate scale the other ratios use.
    """
    del attributed_engine
    body = _business_body(database_url, "today")

    assert (body["completed_jobs"], body["failed_jobs"]) == (9, 1)
    assert body["cost_per_request_paise"] == "9000.0000"
    assert body["cost_per_completed_task_paise"] == "10000.0000"
    assert body["cost_per_patient_paise"] == "30000.0000"
    assert body["cost_per_doctor_paise"] == "20000.0000"
    assert body["cost_of_pass_paise"] == "10000.0000"


async def test_the_business_read_reports_where_per_patient_spend_actually_sits(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """Median, ninety-fifth percentile and maximum, because one outlier is not an average.

    Three patients at 60,000 / 20,000 / 10,000 paise. Their mean is 30,000, which
    describes nobody: it is the 60,000 patient pulling the 10,000 one up, and an
    operator quoting it as "what a patient costs us" is quoting a number about an actor
    who does not exist. The median is the 20,000 patient who does, and the maximum is
    the outlier stated as its own figure so it cannot leak into an average.

    The percentiles are over the whole population, which the seeded month proves twice
    over: widening to ``month_to_date`` adds a FOURTH, far lighter patient and the
    median moves, while the population total moves with it. A sample taken from the
    capped list beside them would not move at all.
    """
    del attributed_engine
    today = _business_body(database_url, "today")
    month = _business_body(database_url, "month_to_date")

    assert today["patient_spend"]["actors"] == 3
    assert today["patient_spend"]["median_spend_paise"] == "20000"
    assert today["patient_spend"]["p95_spend_paise"] == "56000"
    assert today["patient_spend"]["max_spend_paise"] == _TODAY_SPEND_PAISE - 30_000
    # The population total is the headline, so the capped list can be checked against
    # the whole without a second query.
    assert today["patient_spend"]["total_spend_paise"] == _TODAY_SPEND_PAISE

    # The extra 2,000-paise patient pulls the median off the 20,000 figure and moves
    # the total - which a median sampled from the top ten could not do. Rank-interpolated
    # between the 10,000 and 20,000 patients, because that is the estimator the rest of
    # the observability surface reports percentiles with.
    assert month["patient_spend"]["actors"] == 4
    assert month["patient_spend"]["median_spend_paise"] == "15000"
    assert month["patient_spend"]["total_spend_paise"] == _TODAY_SPEND_PAISE + _MONTH_SPEND_PAISE


async def test_the_business_read_names_the_doctor_each_patients_cost_was_attributed_to(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """The recorded edge is what ties a patient's spend to a doctor.

    Not a join across to the care schema - forbidden by the module isolation rule - but
    the edge #724 wrote when the doctor was picked. Two of the three seeded patients
    have no edge and answer ``None`` rather than being dropped: "nobody has picked a
    doctor yet" is the ordinary state of most patients, and the row is still spend.

    The keys are the one-way hashes, so what an operator gets is a pseudonym they can
    correlate across panels and nothing they can identify a human from.
    """
    del attributed_engine
    body = _business_body(database_url, "today")
    rows = {row["patient_key"]: row for row in body["top_patients"]}

    # Heaviest first, and p1 is unattributed because the seed records no edge for them.
    assert [row["patient_key"] for row in body["top_patients"]] == [
        actor_key(ACTOR_KIND_PATIENT, 101),
        actor_key(ACTOR_KIND_PATIENT, 102),
        actor_key(ACTOR_KIND_PATIENT, 103),
    ]
    assert rows[actor_key(ACTOR_KIND_PATIENT, 102)]["attributed_doctor_key"] == actor_key(
        ACTOR_KIND_DOCTOR, 201
    )
    assert rows[actor_key(ACTOR_KIND_PATIENT, 101)]["attributed_doctor_key"] is None
    assert [row["doctor_key"] for row in body["top_doctors"]] == [actor_key(ACTOR_KIND_DOCTOR, 201)]


async def test_per_patient_and_per_doctor_totals_reconcile_through_the_attribution_edge(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """The reconciliation criterion, proved against real Postgres.

    This is the deliverable of the attribution model, not the lists beside it. The
    rollup writes one row per ACTOR, so a doctor row MIRRORS the patient row of the
    same job rather than splitting it, which gives the law asserted here: every doctor
    rupee is also a patient rupee. So the doctor total is at most the patient total,
    the difference is exactly the spend whose doctor is not yet known, and the pair the
    edge names agrees to the rupee.

    If the rollup ever stopped mirroring - or the read started attributing by joining
    across to the care schema - this is the test that fails.
    """
    del attributed_engine
    body = _business_body(database_url, "today")

    patients = {row["patient_key"]: row for row in body["top_patients"]}
    attributed = patients[actor_key(ACTOR_KIND_PATIENT, 102)]
    doctor = body["top_doctors"][0]
    assert doctor["doctor_key"] == actor_key(ACTOR_KIND_DOCTOR, 201)
    assert attributed["attributed_doctor_key"] == doctor["doctor_key"]
    assert (doctor["spend_paise"], doctor["jobs"], doctor["completed_jobs"]) == (
        attributed["spend_paise"],
        attributed["jobs"],
        attributed["completed_jobs"],
    )
    assert doctor["patients"] == 1
    # The conservation law over the whole period, not just this pair.
    assert body["patient_spend"]["total_spend_paise"] == body["spend_paise"]
    assert body["doctor_spend"]["total_spend_paise"] == 20_000
    assert body["doctor_spend"]["total_spend_paise"] < body["patient_spend"]["total_spend_paise"]


async def test_the_business_read_reports_margin_as_null_with_a_reason_and_never_a_zero(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """No revenue captured, so every margin percentage is null AND says why.

    The distinction this test exists for is the difference between ``null`` and
    ``0.00`` on the wire. A zero margin is a claim - "the margin is zero" - that
    nothing measured, it is indistinguishable from a genuinely free month, and a
    finance lead will put it in a deck. So both percentages arrive absent, each
    carrying a machine-readable reason, and the dimensions they would have come from
    are reported as present-and-empty rather than omitted - which is what makes
    "turning monetization on is a data write, not a migration" checkable.
    """
    del attributed_engine
    body = _business_body(database_url, "month_to_date")

    margin = body["margin"]
    assert margin["revenue_captured"] is False
    assert margin["revenue_paise"] == 0
    assert margin["tiers_captured"] is False
    assert margin["tier_keys"] == []
    for figure in (margin["gross_margin"], margin["ai_cost_pct_of_revenue"]):
        # Asserted against BOTH the zero it must not be and the null it must be: a
        # fixture that only checked ``is None`` would also pass on a missing key.
        assert figure["value"] is None
        assert figure["value"] != 0
        assert figure["reason"] == "revenue_not_captured"
        assert figure["detail"]


async def test_the_business_read_reports_the_headline_month_cost_of_goods(
    attributed_engine: AsyncEngine, database_url: str
) -> None:
    """One figure a finance lead can put in front of the board, for the month.

    It is the SAME integer the read reports as the cap's consumed figure and the same
    one the ``ai_budget`` alert is evaluated against - carried under this name because
    it answers a different question ("what did AI cost us this month") from "how much
    of the cap is gone". Two names for one figure is only safe while they are the same
    figure, which is what this asserts on the wire.

    It is the MONTH's figure even when the period asked for is a day, because a board
    number does not shrink when an operator opens the panel on "today".
    """
    del attributed_engine
    month = _business_body(database_url, "month_to_date")

    assert month["margin"]["headline_month_cost_of_goods_paise"] == _BUSINESS_CONSUMED_PAISE
    assert month["margin"]["headline_month_cost_of_goods_paise"] == month["cap_consumed_paise"]
    assert month["margin"]["cost_of_goods_paise"] == month["spend_paise"]


# ------------------------------------------------------------- the funnel read (#740)

#: Two patients walk the funnel end to end, one walks away at the entry step, one has
#: a capture that degrades, and one corrects a round. The timestamps are seconds before
#: the seed ran, so every row is inside the default thirty-day window whatever day the
#: suite runs on - and each step's median gap has exactly one arithmetic answer:
#:
#:   intake_captured     60s and 300s apart from the composer  -> median 180
#:   pre_summary_ready    30s after the capture                  -> median 30
#:   consult_complete     none - the handoff shares no key       -> median null
#:   prescription_drafted 600s and 300s after the consult        -> median 450
#:   prescription_approved 120s after the draft                  -> median 120
#:   case_closed          600s after the draft                   -> median 600
#:
#: The stamps are named rather than written inline in the SQL so the table above and
#: the rows below cannot drift apart.
_FUNNEL_STAMPS: dict[str, int] = {
    "at100000": 100_000,
    "at99940": 99_940,
    "at99910": 99_910,
    "at99900": 99_900,
    "at50000": 50_000,
    "at49900": 49_900,
    "at49700": 49_700,
    "at40000": 40_000,
    "at39400": 39_400,
    "at39280": 39_280,
    "at20000": 20_000,
    "at19700": 19_700,
    "at19100": 19_100,
    "at3000000": 3_000_000,
}

_FUNNEL_SEED = """
INSERT INTO observability.observability_product_events
(event_id, occurred_at, actor_kind, actor_key, session_key, trace_id, funnel, step,
 outcome, duration_ms) VALUES
-- One patient opens, records and leaves: the funnel's head, abandoned.
(:e1, :at100000, 'patient', :p1, 'sess-p1-open', 'trace-p1-open', 'intake',
 'composer_opened', 'completed', NULL),
(:e2, :at100000, 'patient', :p3, 'sess-p3-open', 'trace-p3-open', 'intake',
 'composer_opened', 'abandoned', NULL),
-- One patient completes a round and then asks to redo it: a correction, not a failure.
(:e3, :at99900, NULL, NULL, 'sess-p1-retry', 'trace-p1-retry', 'intake',
 're_recorded', 're_recorded', NULL),
-- The second patient's capture degraded: scored errored, never as a quiet drop-off.
(:e4, :at49900, 'patient', :p4, 'sess-p4-cap', 'trace-p4-cap', 'intake',
 'intake_captured', 'errored', NULL),
-- Patient one, in order.
(:e5, :at99940, 'patient', :p1, 'sess-p1-cap', 'trace-p1-cap', 'intake',
 'intake_captured', 'completed', NULL),
(:e6, :at99910, 'patient', :p1, 'sess-p1-sum', 'trace-p1-sum', 'intake',
 'pre_summary_ready', 'completed', 4200),
(:e7, :at40000, 'doctor', :d1, 'sess-d1-consult-1', 'trace-d1-consult-1', 'intake',
 'consult_complete', 'completed', 1500000),
(:e8, :at39400, 'doctor', :d1, 'sess-d1-draft-1', 'trace-d1-draft-1', 'intake',
 'prescription_drafted', 'completed', 22000),
(:e9, :at39280, 'doctor', :d1, 'sess-d1-approve', 'trace-d1-approve', 'intake',
 'prescription_approved', 'completed', NULL),
-- Patient two, whose case ends closed without a prescription.
(:e10, :at50000, 'patient', :p2, 'sess-p2-open', 'trace-p2-open', 'intake',
 'composer_opened', 'completed', NULL),
(:e11, :at49700, 'patient', :p2, 'sess-p2-cap', 'trace-p2-cap', 'intake',
 'intake_captured', 'completed', NULL),
(:e12, :at20000, 'doctor', :d1, 'sess-d1-consult-2', 'trace-d1-consult-2', 'intake',
 'consult_complete', 'completed', 900000),
(:e13, :at19700, 'doctor', :d1, 'sess-d1-draft-2', 'trace-d1-draft-2', 'intake',
 'prescription_drafted', 'completed', 19000),
(:e14, :at19100, 'doctor', :d1, 'sess-d1-close', 'trace-d1-close', 'intake',
 'case_closed', 'completed', NULL),
-- A step recorded before the window opened: every read must ignore it.
(:e15, :at3000000, 'patient', :p1, 'sess-old', 'trace-old', 'intake',
 'composer_opened', 'completed', NULL)
"""


@pytest_asyncio.fixture
async def funnel_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The product event ledger as #739's consumer writes it, over two journeys."""
    now = datetime.now(UTC)
    keys: dict[str, Any] = {
        "p1": actor_key(ACTOR_KIND_PATIENT, 101),
        "p2": actor_key(ACTOR_KIND_PATIENT, 102),
        "p3": actor_key(ACTOR_KIND_PATIENT, 103),
        "p4": actor_key(ACTOR_KIND_PATIENT, 104),
        "d1": actor_key(ACTOR_KIND_DOCTOR, 201),
    }
    keys.update(
        {name: now - timedelta(seconds=seconds) for name, seconds in _FUNNEL_STAMPS.items()}
    )
    # One distinct ``event_id`` per row, as the consumer writes: the ledger is keyed on
    # it and a replay of any one of them changes nothing.
    keys.update({f"e{index}": uuid.uuid4() for index in range(1, 16)})
    async with engine.begin() as connection:
        await connection.execute(text(_FUNNEL_SEED), keys)
    yield engine


def _funnel_body(database_url: str, query: str = "") -> dict[str, Any]:
    path = FUNNEL_PATH if not query else f"{FUNNEL_PATH}?{query}"
    with _client(database_url) as client:
        return client.get(path, headers=_bearer()).json()


def _steps_by_name(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["step"]: row for row in body["steps"]}


async def test_the_funnel_read_runs_the_walk_from_the_composer_to_both_ends(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """The whole question in one call: which step, how many, and how they left.

    Without it, a workflow that dies silently at transcription and one that runs to a
    completed prescription look identical - and the counts below are the ledger's own
    rows, so the step that loses the patient is visible rather than inferred.
    """
    del funnel_engine
    body = _funnel_body(database_url)

    assert [row["step"] for row in body["steps"]] == [
        "composer_opened",
        "intake_captured",
        "pre_summary_ready",
        "consult_complete",
        "prescription_drafted",
        "prescription_approved",
        "case_closed",
    ]
    # The re-record is registered and written, but it is not a stage of the walk.
    assert "re_recorded" not in [row["step"] for row in body["steps"]]
    assert body["outcomes"]["re_recorded"] == 1


async def test_each_step_is_counted_completed_and_abandoned(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """Step-to-step conversion is only computable if both figures are on the row."""
    del funnel_engine
    steps = _steps_by_name(_funnel_body(database_url))

    assert (steps["composer_opened"]["entered"], steps["composer_opened"]["abandoned"]) == (
        3,
        1,
    )
    # The degraded capture is errored, so it is never counted as a walk-away.
    assert (steps["intake_captured"]["entered"], steps["intake_captured"]["errored"]) == (3, 1)
    assert steps["intake_captured"]["abandoned"] == 0
    assert steps["intake_captured"]["completed"] == 2


async def test_the_degraded_step_and_the_reattempt_are_scored_as_what_they_are(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """Decision 24 scores a fallback as an error; decision 25 makes a re-record its own.

    Together they are what stops a broken path reading as a quiet drop-off and a
    corrected attempt reading as a failure of the attempt it replaces.
    """
    del funnel_engine
    body = _funnel_body(database_url)
    steps = _steps_by_name(body)

    assert steps["intake_captured"]["errored"] == 1
    assert body["outcomes"]["errored"] == 1
    assert body["outcomes"]["re_recorded"] == 1
    # Neither is folded into the other: the abandoned figure counts the walk-away only.
    assert body["outcomes"]["abandoned"] == 1


async def test_the_median_gap_between_two_steps_is_the_thinking_time_between_them(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """The seeded gaps: 60s and 300s from the composer, 600s and 300s from the consult.

    Reported as strings at the gap scale (api-standards §3), the same shape the other
    reads' decimals already take on the wire.
    """
    del funnel_engine
    steps = _steps_by_name(_funnel_body(database_url))

    assert steps["intake_captured"]["median_gap_from_previous_s"] == "180.0"
    assert steps["intake_captured"]["gap_samples"] == 2
    assert steps["pre_summary_ready"]["median_gap_from_previous_s"] == "30.0"
    assert steps["prescription_drafted"]["median_gap_from_previous_s"] == "450.0"
    assert steps["prescription_approved"]["median_gap_from_previous_s"] == "120.0"
    assert steps["case_closed"]["median_gap_from_previous_s"] == "600.0"


async def test_the_gap_that_the_ledger_cannot_measure_is_reported_as_unmeasured(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """The handoff from the patient to the doctor shares no key the ledger stores.

    Reported as ``null`` with its basis named, because a zero would read as an instant
    handoff and an absent figure with no reason is the thing operators stop trusting.
    """
    del funnel_engine
    steps = _steps_by_name(_funnel_body(database_url))

    consult = steps["consult_complete"]
    assert consult["median_gap_from_previous_s"] is None
    assert consult["gap_samples"] == 0
    assert consult["gap_basis"] == "unavailable"
    # Every other pair says what it was measured on, and the entry step says it has no
    # predecessor at all - a different fact from the ledger failing to join one.
    assert steps["intake_captured"]["gap_basis"] == "actor_key"
    assert steps["composer_opened"]["gap_basis"] == "no_predecessor"


async def test_the_conventions_the_figures_rest_on_ride_the_response(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """A panel drawing this has to be able to say what its numbers mean."""
    del funnel_engine
    body = _funnel_body(database_url)

    assert "non-terminal" in body["denominator_convention"]
    assert "started" in body["rate_convention"]
    assert "unavailable" in body["gap_convention"]


async def test_a_step_reached_without_its_predecessor_is_not_clamped_to_one(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """Two consults against one pre-summary is what the ledger recorded, so it is said.

    Clamping would make a broken step look like a perfect one and hide the very thing
    the funnel exists to surface.
    """
    del funnel_engine
    steps = _steps_by_name(_funnel_body(database_url))

    assert (steps["pre_summary_ready"]["entered"], steps["consult_complete"]["entered"]) == (
        1,
        2,
    )
    assert steps["consult_complete"]["conversion_from_previous"] == "2.0000"
    # And the entry step has no denominator at all rather than a division by zero.
    assert steps["composer_opened"]["previous_step"] is None
    assert steps["composer_opened"]["conversion_from_previous"] is None


async def test_both_terminal_outcomes_are_successes_and_are_told_apart(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """An issued prescription and a closed case are both ends, and neither is a failure."""
    del funnel_engine
    body = _funnel_body(database_url)
    steps = _steps_by_name(body)

    assert steps["prescription_approved"]["terminal"] is True
    assert steps["case_closed"]["terminal"] is True
    # Both take their denominator from the last non-terminal step, so a case closed
    # without a prescription is not a step after an issued one.
    assert steps["prescription_approved"]["previous_step"] == "prescription_drafted"
    assert steps["case_closed"]["previous_step"] == "prescription_drafted"
    assert body["outcomes"]["issued_e_prescriptions"] == 1
    assert body["outcomes"]["cases_closed"] == 1
    assert body["outcomes"]["task_success_rate"] == "0.6667"


async def test_success_and_abandonment_come_back_over_one_denominator(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """Two of three journeys finished and one was abandoned - and both are said.

    The two rates share ``started`` so they can be read against each other, and they
    are one object so a client cannot be handed one without the other.
    """
    del funnel_engine
    outcomes = _funnel_body(database_url)["outcomes"]

    assert outcomes["started"] == 3
    assert outcomes["task_success_rate"] == "0.6667"
    assert outcomes["abandonment_rate"] == "0.3333"


async def test_the_funnel_is_filterable_to_the_steps_that_can_end_abandoned(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """Isolating the abandoned path is the filter's job: nothing else is on the row."""
    del funnel_engine
    body = _funnel_body(database_url, "outcome=abandoned")

    assert body["outcome"] == "abandoned"
    assert [row["step"] for row in body["steps"]] == [
        "composer_opened",
        "consult_complete",
        "case_closed",
    ]
    # Only the abandoned arrivals are counted, so there is no completed figure beside
    # them to quote instead.
    assert body["steps"][0]["entered"] == 1
    assert body["steps"][0]["abandoned"] == 1
    assert body["steps"][0]["completed"] == 0
    # The headline rates stay the window's verdict and are not narrowed with the filter.
    assert body["outcomes"]["started"] == 3
    assert body["outcomes"]["task_success_rate"] == "0.6667"


async def test_each_step_carries_the_trace_behind_its_own_figures(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """Story 81: every count here is backed by a journey an operator can open."""
    del funnel_engine
    steps = _steps_by_name(_funnel_body(database_url))

    assert steps["composer_opened"]["latest_trace_id"] == "trace-p2-open"
    assert steps["consult_complete"]["latest_trace_id"] == "trace-d1-consult-2"
    assert steps["prescription_approved"]["latest_trace_id"] == "trace-d1-approve"


async def test_the_funnel_window_excludes_rows_older_than_it(
    funnel_engine: AsyncEngine, database_url: str
) -> None:
    """The seed holds one entry step 34 days back, and no window may count it."""
    del funnel_engine

    assert _funnel_body(database_url)["outcomes"]["started"] == 3
    # A one-day window sees only the most recent entry, and still never the stale row.
    assert _funnel_body(database_url, "days=1")["outcomes"]["started"] == 1


async def test_the_funnel_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    """This read sits behind the same flat operator requirement as the other reads."""
    assert _client(database_url).get(FUNNEL_PATH).status_code == 401
    forbidden = _client(database_url).get(FUNNEL_PATH, headers=_bearer("patient"))
    assert forbidden.status_code == 403


# --------------------------------------------------------- the active users read (#741)

#: The ledger rows, as days before today. Each entry is
#: ``(actor reference, actor kind, step)`` and the arithmetic every assertion below
#: rests on is written out rather than left to be derived by eye:
#:
#:   today       p1 + p2 + d1                              -> DAU  2 patients, 1 doctor
#:   3 days ago  p3 + p2 + d2                              -> adds p3 and d2 to the week
#:   5 days ago  p1                                         -> p1 again, still one actor
#:   10 days ago p4 + d1                                    -> adds p4 to the month
#:   20 days ago p5                                         -> adds p5 to the month
#:   45 days ago p6                                         -> outside every rolling window
#:   2 days ago  a re-record, which records NO actor         -> counts nobody
#:
#: So daily is 3, weekly is 5 (3 patients + 2 doctors), monthly is 7 (5 + 2), and a
#: sixty-day window is 8 once p6 is inside it. None of the three is a multiple of
#: another, which is the whole point: a read that multiplied the daily figure by
#: thirty would report 90 monthly users from this seed.
#:
#: Each entry is ``(days ago, patient reference, doctor reference, step)`` - one
#: reference per row because the ledger's actor pair is nullable TOGETHER, and both
#: NULL is the machine-finished re-record. ``p``/``d`` are the identity references the
#: producer publishes; the keys the row stores are their pseudonymous hashes.
_ACTIVE_ACTOR_ROWS: tuple[tuple[int, int | None, int | None, str], ...] = (
    (0, 301, None, "composer_opened"),
    (0, 302, None, "composer_opened"),
    (0, None, 401, "consult_complete"),
    (3, 303, None, "intake_captured"),
    (3, 302, None, "composer_opened"),
    (3, None, 402, "case_closed"),
    (5, 301, None, "intake_captured"),
    (10, 304, None, "composer_opened"),
    (10, None, 401, "consult_complete"),
    (20, 305, None, "composer_opened"),
    (45, 306, None, "composer_opened"),
    (2, None, None, "re_recorded"),
)

_ACTIVE_ACTOR_INSERT = text(
    "INSERT INTO observability.observability_product_events "
    "(event_id, occurred_at, actor_kind, actor_key, session_key, trace_id, funnel, "
    "step, outcome, duration_ms) VALUES "
    "(:event_id, :occurred_at, :actor_kind, :actor_key, :session_key, :trace_id, "
    ":funnel, :step, :outcome, :duration_ms)"
)

#: The per-minute counter rows that same seed makes: midday UTC on the named day. The
#: thirty-day total is 10 + 5 + 8 = 23, and the sixty-day total adds the 99 from the
#: stale route, giving 122.
#:
#: Each entry is ``(days ago, route template, method, requests, errors)``.
_THROUGHPUT_ROWS: tuple[tuple[int, str, str, int, int], ...] = (
    (0, "/v1/patients", "GET", 10, 0),
    (1, "/v1/patients", "GET", 5, 0),
    (3, "/v1/cases", "POST", 8, 1),
    (45, "/v1/legacy", "GET", 99, 0),
)

_THROUGHPUT_INSERT = text(
    "INSERT INTO observability.observability_http_minute "
    "(minute_ts, route_template, method, status_class, requests, errors) VALUES "
    "(:minute_ts, :route_template, :method, '2xx', :requests, :errors)"
)


@pytest_asyncio.fixture
async def active_users_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The ledger and the request counter as #739 and #727 write them.

    The rows are stamped at midday UTC on their day, which matters: the read buckets
    by the UTC calendar day, so a row at 00:30 would be testing the bucket rather than
    the adoption.
    """
    today = datetime.now(UTC).date()

    def at(days_ago: int) -> datetime:
        return datetime.combine(today - timedelta(days=days_ago), time(12, 0), tzinfo=UTC)

    ledger: list[dict[str, Any]] = []
    for index, (days_ago, patient_ref, doctor_ref, step) in enumerate(_ACTIVE_ACTOR_ROWS):
        machine_finished = patient_ref is None and doctor_ref is None
        ledger.append(
            {
                "event_id": uuid.uuid4(),
                "occurred_at": at(days_ago),
                "actor_kind": None
                if machine_finished
                else (ACTOR_KIND_PATIENT if patient_ref is not None else ACTOR_KIND_DOCTOR),
                "actor_key": None
                if machine_finished
                else actor_key(
                    ACTOR_KIND_PATIENT if patient_ref is not None else ACTOR_KIND_DOCTOR,
                    patient_ref if patient_ref is not None else doctor_ref,  # type: ignore[arg-type]
                ),
                "session_key": f"sess-{index}",
                "trace_id": f"trace-{index}",
                "funnel": "intake",
                "step": step,
                "outcome": "re_recorded" if machine_finished else "completed",
                "duration_ms": 900000 if step == "consult_complete" else None,
            }
        )
    counter = [
        {
            "minute_ts": at(days_ago),
            "route_template": route_template,
            "method": method,
            "requests": requests,
            "errors": errors,
        }
        for days_ago, route_template, method, requests, errors in _THROUGHPUT_ROWS
    ]
    async with engine.begin() as connection:
        await connection.execute(_ACTIVE_ACTOR_INSERT, ledger)
        await connection.execute(_THROUGHPUT_INSERT, counter)
    yield engine


def _active_users_body(database_url: str, query: str = "") -> dict[str, Any]:
    path = ACTIVE_USERS_PATH if not query else f"{ACTIVE_USERS_PATH}?{query}"
    with _client(database_url) as client:
        return client.get(path, headers=_bearer()).json()


async def test_the_three_active_user_counts_are_three_different_actor_sets(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC1: daily, weekly and monthly are distinct actors over their own windows.

    The seed is built so the shortcut a careless implementation would take - the daily
    figure times seven and times thirty - lands on 21 and 90, against the real 5 and 7.
    """
    del active_users_engine
    body = _active_users_body(database_url)

    daily, weekly, monthly = (
        body["daily_active_users"],
        body["weekly_active_users"],
        body["monthly_active_users"],
    )
    assert (daily["patients"], daily["doctors"], daily["total"]) == (2, 1, 3)
    assert (weekly["patients"], weekly["doctors"], weekly["total"]) == (3, 2, 5)
    assert (monthly["patients"], monthly["doctors"], monthly["total"]) == (5, 2, 7)
    # The shortcut this read must not take: seven times the daily figure, or thirty
    # times it, against a weekly base of 5 and a monthly base of 7.
    assert weekly["total"] not in {daily["total"] * 7, daily["total"] * 2}
    assert monthly["total"] not in {daily["total"] * 30, weekly["total"] * 4}


async def test_each_active_user_count_travels_with_its_own_window(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """A count quoted without the days it covers is how a fortnight becomes a month."""
    del active_users_engine
    body = _active_users_body(database_url)
    today = datetime.now(UTC).date()

    assert body["daily_active_users"]["window_days"] == 1
    assert body["daily_active_users"]["from_date"] == str(today)
    assert body["weekly_active_users"]["from_date"] == str(today - timedelta(days=6))
    assert body["monthly_active_users"]["from_date"] == str(today - timedelta(days=29))
    assert body["monthly_active_users"]["to_date"] == str(today)
    assert body["from_date"] == str(today - timedelta(days=29))


async def test_stickiness_is_the_daily_base_over_the_monthly_base(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC1: the ratio, with the definition it is measured by, on the response."""
    del active_users_engine
    body = _active_users_body(database_url)

    assert body["daily_active_users"]["total"] == 3
    assert body["monthly_active_users"]["total"] == 7
    assert body["stickiness"] == "0.4286"
    assert (
        "daily_active_users.total over monthly_active_users.total"
        in (body["stickiness_convention"])
    )


async def test_a_month_is_answered_over_thirty_days_not_the_vendors_fourteen(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC4: the figure is computed in Postgres, so widening past 14 days still answers.

    p6 is 45 days back - outside the free tier's retention by three weeks and outside
    the rolling month. A sixty-day request must find them, and the monthly count must
    stay at 7 because the rolling month did not move: the wide window widens the
    THROUGHPUT figures and the window's own actor count, not the headline trio.
    """
    del active_users_engine

    narrow = _active_users_body(database_url, "days=30")
    wide = _active_users_body(database_url, "days=60")

    assert wide["days"] == 60
    assert wide["monthly_active_users"]["total"] == 7
    assert wide["daily_active_users"]["total"] == 3
    # The window's OWN actor count follows ``days`` and does find the older actor.
    assert narrow["window_active_users"]["total"] == 7
    assert wide["window_active_users"]["total"] == 8
    assert wide["window_active_users"]["patients"] == 6


async def test_the_counts_hold_across_a_month_boundary(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC1 with the window the brief names: one that CROSSES a calendar month.

    A rolling thirty-day window only straddles a month boundary for part of the month,
    so the fixture would not reliably be exercising the case. The window requested here
    is sized off the day of the month, which puts its opening day in the previous
    calendar month whatever day the suite runs on - and that is the arrangement that
    catches the "monthly = thirty times today" shortcut, because a month edge is
    exactly where a calendar-month and a rolling-month read disagree.
    """
    del active_users_engine
    today = datetime.now(UTC).date()
    crossing = today.day + 5

    body = _active_users_body(database_url, f"days={crossing}")

    assert body["from_date"][:7] != body["to_date"][:7]
    assert body["monthly_active_users"]["total"] == 7
    assert body["weekly_active_users"]["total"] == 5
    assert body["daily_active_users"]["total"] == 3
    # The rolling windows are anchored on today, not on the requested window's start.
    assert body["monthly_active_users"]["to_date"] == body["to_date"]
    assert body["monthly_active_users"]["from_date"] == str(today - timedelta(days=29))


async def test_requests_and_requests_per_active_user_cover_the_same_window(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC3: total load and load per head, over the days the window names."""
    del active_users_engine
    body = _active_users_body(database_url, "days=30")

    assert body["requests"] == 23
    assert body["window_active_users"]["total"] == 7
    # 23 requests over the 7 people who were there, at the module's 2dp count scale.
    assert body["requests_per_active_user"] == "3.29"
    assert "over the window's own" in body["requests_per_active_user_convention"]


async def test_the_throughput_trend_is_a_day_series_of_load_and_people(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC3: a trend an operator can read a climb out of, at day grain.

    Day grain rather than the counter's minute grain because a thirty-day window at
    minute grain is forty-three thousand points and no chart draws them.
    """
    del active_users_engine
    today = datetime.now(UTC).date()
    trend = {point["day"]: point for point in _active_users_body(database_url)["trend"]}

    assert trend[str(today)]["requests"] == 10
    assert trend[str(today)]["active_users"] == 3
    assert trend[str(today)]["requests_per_active_user"] == "3.33"
    assert trend[str(today - timedelta(days=3))]["requests_per_active_user"] == "2.67"
    # A day with clinical work but no traffic, and a day with traffic but no clinical
    # work: both are present, and neither gets a division by zero.
    assert trend[str(today - timedelta(days=20))]["requests"] == 0
    assert trend[str(today - timedelta(days=20))]["requests_per_active_user"] is None
    assert trend[str(today - timedelta(days=1))]["active_users"] == 0
    assert trend[str(today - timedelta(days=1))]["requests_per_active_user"] is None
    # Nothing was recorded on these days at all, so they are absent rather than zero.
    assert str(today - timedelta(days=15)) not in trend
    assert str(today - timedelta(days=45)) not in trend


async def test_a_machine_finished_step_counts_nobody(
    active_users_engine: AsyncEngine, database_url: str
) -> None:
    """AC2: the re-record records no actor, so it cannot inflate any of the figures."""
    del active_users_engine
    body = _active_users_body(database_url, "days=30")

    # Two days ago the only ledger row is the re-record, which carries no actor pair.
    assert body["daily_active_users"]["total"] == 3
    assert body["weekly_active_users"]["patients"] == 3
    assert "never from a login" in body["source_convention"]


async def test_the_active_users_read_is_empty_before_anything_is_recorded(
    engine: AsyncEngine, database_url: str
) -> None:
    """No activity is an answer with no measurement in it, never an error or a zero rate."""
    del engine
    body = _active_users_body(database_url)

    assert body["daily_active_users"]["total"] == 0
    assert body["monthly_active_users"]["total"] == 0
    # Nothing to divide by, which is not the same as measured absence of stickiness.
    assert body["stickiness"] is None
    assert body["requests"] == 0
    assert body["requests_per_active_user"] is None
    assert body["trend"] == []


async def test_the_active_users_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    """AC5: the same flat operator requirement as every other read in the module."""
    assert _client(database_url).get(ACTIVE_USERS_PATH).status_code == 401
    forbidden = _client(database_url).get(ACTIVE_USERS_PATH, headers=_bearer("patient"))
    assert forbidden.status_code == 403


@pytest.mark.parametrize("days", [0, 366])
async def test_the_active_users_route_refuses_a_window_outside_its_bounds(
    database_url: str, days: int
) -> None:
    """The window is bounded in the query parameter, so an over-wide read is a 422."""
    with _client(database_url) as client:
        response = client.get(f"{ACTIVE_USERS_PATH}?days={days}", headers=_bearer())
    assert response.status_code == 422


# ---------------------------------------------------- the retention cohorts read (#742)

#: The daily per-actor aggregate, seeded as the nightly rollup writes it, as days
#: before today. Each entry is ``(days ago, patient reference, doctor reference)`` and
#: the arithmetic every assertion rests on is written out rather than left to be
#: derived by eye. An actor's cohort is its EARLIEST seeded day, so a return visit
#: never opens a second cohort:
#:
#:   45 days ago  p1 + p2 + d1   -> cohort A of 3, the only one with BOTH horizons
#:   38 days ago  p1 + p2 + d1   -> A at A+7: 3 of 3, perfect
#:   15 days ago  p1 + p2 + d1   -> A at A+30: 3 of 3, perfect
#:   31 days ago  p3 + d2        -> cohort B of 2; 31+7 is inside, 31+30 is too
#:   24 days ago  p3            -> B at B+7: one of two, so 0.5000
#:                                  nobody at B+30, so 0.0000 - a ZERO, measured
#:   3 days ago   p4            -> cohort C of 1, past neither horizon: null, null
#:
#: So this seed holds all three states a cohort table can be in - fully retained, half
#: retained then lost, and too young to measure - and the third is the one that would be
#: silently corrupted by writing zero. Cohort A's perfect retention is also the figure a
#: product that has lost everybody would report if null and zero collapsed.
_RETENTION_ACTOR_ROWS: tuple[tuple[int, int | None, int | None], ...] = (
    (45, 501, None),
    (45, 502, None),
    (45, None, 601),
    (38, 501, None),
    (38, 502, None),
    (38, None, 601),
    (15, 501, None),
    (15, 502, None),
    (15, None, 601),
    (31, 503, None),
    (31, None, 602),
    (24, 503, None),
    (3, 504, None),
)

_RETENTION_ACTOR_INSERT = text(
    "INSERT INTO observability.observability_product_actor_daily "
    "(event_date, actor_kind, actor_key, events) VALUES (:event_date, :actor_kind, "
    ":actor_key, :events)"
)

#: Truncating the RAW LEDGER, on purpose. This is the criterion, not a cleanup: a
#: thirty-day retention answer that still works with the event ledger emptied is an
#: answer that was computed from the daily aggregate. The ``clean_tables`` fixture
#: already empties the ledger before every test, so the truncation here only makes the
#: starting state explicit - the PROOF that the ledger is unread is
#: :func:`test_the_cohorts_do_not_move_when_the_raw_ledger_is_filled`, which puts
#: decoy events in and asserts the answer is byte-for-byte the same.
_RETENTION_EMPTY_LEDGER = text("TRUNCATE observability.observability_product_events")

#: Decoy ledger rows, shaped so that a read which DID consult the ledger would answer
#: differently and obviously: eight brand-new arrivals on today with perfect retention
#: at both horizons, none of whom exists in the daily aggregate above. ``#742``'s
#: headline criterion is that filling the ledger changes nothing, and this is the only
#: shape of that assertion that cannot be satisfied by accident.
_RETENTION_DECOY_EVENTS: tuple[tuple[int, int, str], ...] = tuple(
    (days_ago, 700_000 + index, "composer_opened") for days_ago in (30, 7, 0) for index in range(8)
)

_RETENTION_DECOY_INSERT = text(
    "INSERT INTO observability.observability_product_events "
    "(event_id, occurred_at, actor_kind, actor_key, session_key, trace_id, funnel, "
    "step, outcome, duration_ms) VALUES "
    "(:event_id, :occurred_at, :actor_kind, :actor_key, :session_key, :trace_id, "
    "'intake', :step, 'completed', NULL)"
)


@pytest_asyncio.fixture
async def retention_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Forty-five days of the daily actor aggregate, and an EMPTY raw ledger.

    The aggregate is seeded directly rather than through forty-five rollup passes,
    because the question here is what the READ does with long stretches of stored daily
    aggregates - and forty-five real rollup passes would test the rollup, which
    :mod:`test_observability_rollup_round_trip` already owns.
    """
    today = datetime.now(UTC).date()

    rows: list[dict[str, Any]] = []
    for days_ago, patient_ref, doctor_ref in _RETENTION_ACTOR_ROWS:
        kind = ACTOR_KIND_PATIENT if patient_ref is not None else ACTOR_KIND_DOCTOR
        rows.append(
            {
                "event_date": today - timedelta(days=days_ago),
                "actor_kind": kind,
                "actor_key": actor_key(
                    kind,
                    patient_ref if patient_ref is not None else doctor_ref,  # type: ignore[arg-type]
                ),
                "events": 1,
            }
        )
    async with engine.begin() as connection:
        await connection.execute(_RETENTION_ACTOR_INSERT, rows)
        await connection.execute(_RETENTION_EMPTY_LEDGER)
    yield engine


def _retention_body(database_url: str, query: str = "") -> dict[str, Any]:
    path = RETENTION_PATH if not query else f"{RETENTION_PATH}?{query}"
    with _client(database_url) as client:
        return client.get(path, headers=_bearer()).json()


def _cohort_rows(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["cohort_date"]: row for row in body["cohorts"]}


async def test_cohorts_are_read_from_the_daily_aggregate_with_the_ledger_empty(
    retention_engine: AsyncEngine, database_url: str, db_engine: AsyncEngine
) -> None:
    """AC1 + AC3: the figures, computed from stored daily aggregates alone.

    Forty-five days of the daily aggregate are in place and
    ``observability_product_events`` has been TRUNCATED. Every figure below is
    therefore computed from stored daily aggregates, and it outlives the free vendor
    tier's fourteen-day retention because the system of record is what still holds it.
    That the ledger is never CONSULTED is proved separately, by filling it and showing
    the answer does not move.
    """
    del retention_engine
    async with db_engine.connect() as db:
        ledger_rows = int(
            await db.scalar(text("SELECT COUNT(*) FROM observability.observability_product_events"))
        )
    assert ledger_rows == 0, "the ledger must be empty for this test to mean anything"

    body = _retention_body(database_url)
    rows = _cohort_rows(body)
    today = datetime.now(UTC).date()

    arrived = rows[str(today - timedelta(days=45))]
    assert arrived["cohort_size"] == 3
    assert arrived["retained_7d"] == 3
    assert arrived["retained_30d"] == 3
    assert arrived["retention_7d"] == "1.0000"
    assert arrived["retention_30d"] == "1.0000"


async def test_the_cohorts_do_not_move_when_the_raw_ledger_is_filled(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """AC2: the headline criterion, stated so that it cannot be satisfied by accident.

    Twenty-four decoy ledger events land - eight people arriving today, thirty days
    ago and seven days ago, each with perfect retention at both horizons. A read that
    consulted the ledger would show them: today's cohort would jump from 0 to 8, the
    31-day-old cohort from 2 to 10, and the 45-day-old one - the only figure the
    response holds at thirty days with real arrivals in it - would not move at all,
    which is exactly the kind of partial agreement a field-by-field check would miss.
    The response is compared WHOLE instead.

    This is the assertion that actually proves AC2. Asserting "the ledger is empty and
    the answer is right" cannot prove it - the fixture empties the ledger for every
    test, so an implementation that scanned the ledger would pass that too.
    """
    before = _retention_body(database_url)
    today = datetime.now(UTC).date()
    assert _cohort_rows(before)[str(today)]["cohort_size"] == 0
    assert _cohort_rows(before)[str(today - timedelta(days=3))]["cohort_size"] == 1

    rows = [
        {
            "event_id": uuid.uuid4(),
            "occurred_at": datetime.combine(
                today - timedelta(days=days_ago), time(12, 0), tzinfo=UTC
            ),
            "actor_kind": ACTOR_KIND_PATIENT,
            "actor_key": actor_key(ACTOR_KIND_PATIENT, patient_ref),
            "session_key": f"decoy-{days_ago}-{patient_ref}",
            "trace_id": f"decoy-{days_ago}-{patient_ref}",
            "step": step,
        }
        for days_ago, patient_ref, step in _RETENTION_DECOY_EVENTS
    ]
    async with retention_engine.begin() as connection:
        await connection.execute(_RETENTION_DECOY_INSERT, rows)

    after = _retention_body(database_url)

    assert after == before


async def test_a_cohort_that_came_back_for_a_week_and_then_left_reads_as_zero_at_thirty(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """AC4: each rate is its OWN cohort's retained over its OWN cohort's size.

    Cohort B is two people, one of whom came back at seven days and neither of whom
    came back at thirty. A denominator borrowed from the window, or from a neighbouring
    cohort, would turn the half that returned into a different number - and a zero at
    thirty days is a measurement, which is why it must not be confused with a horizon
    that has not arrived.
    """
    del retention_engine
    body = _retention_body(database_url)
    rows = _cohort_rows(body)
    today = datetime.now(UTC).date()

    cohort_b = rows[str(today - timedelta(days=31))]
    assert cohort_b["cohort_size"] == 2
    assert cohort_b["retained_7d"] == 1
    assert cohort_b["retention_7d"] == "0.5000"
    assert cohort_b["retained_30d"] == 0
    assert cohort_b["retention_30d"] == "0.0000"


async def test_a_cohort_that_has_not_reached_its_horizon_reports_null_not_zero(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """AC1: ``null`` is a horizon nobody has lived through; zero is a lost cohort.

    Both are in this seed. Writing zero into cohort C would put a fabricated 100% drop
    at the right-hand end of the chart, where a real decline would have to compete with
    it - and it is the one error on this read that no downstream consumer can detect.
    """
    del retention_engine
    body = _retention_body(database_url)
    rows = _cohort_rows(body)
    today = datetime.now(UTC).date()

    young = rows[str(today - timedelta(days=3))]
    assert young["cohort_size"] == 1
    assert young["retained_7d"] is None
    assert young["retention_7d"] is None
    assert young["retained_30d"] is None
    assert young["retention_30d"] is None


async def test_a_return_visit_does_not_open_a_second_cohort(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """AC4: a cohort is an arrival date, so coming back is not arriving again.

    The seed returns every one of cohort A's members twice inside its own lifetime. A
    read that counted each actor-day as an arrival would report three fresh cohorts of
    three at the 38- and 15-day marks and describe a product acquiring nine people who
    never existed.
    """
    del retention_engine
    body = _retention_body(database_url)
    rows = _cohort_rows(body)
    today = datetime.now(UTC).date()

    assert rows[str(today - timedelta(days=38))]["cohort_size"] == 0
    assert rows[str(today - timedelta(days=15))]["cohort_size"] == 0
    assert rows[str(today - timedelta(days=24))]["cohort_size"] == 0


async def test_a_short_window_still_measures_the_full_thirty_day_horizon(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """AC4: ``days`` counts arrival dates and never truncates either horizon.

    Forty dates end today. Cohort B arrived thirty-one days ago, so its thirty-day
    horizon is YESTERDAY - a date that is itself nobody's arrival day, three weeks
    after the cohort it belongs to. A query that read only the arrival dates it
    returns would find no cohort there and report nothing at all; a query that did find
    one would report zero, because nobody arrived then either. The figure belongs to the
    cohort thirty-one days back.
    """
    del retention_engine
    body = _retention_body(database_url, "days=40")
    rows = _cohort_rows(body)
    today = datetime.now(UTC).date()

    assert len(body["cohorts"]) == 40
    assert rows[str(today - timedelta(days=31))]["retention_30d"] == "0.0000"
    # The horizon date is inside the window and is nobody's arrival day.
    assert rows[str(today - timedelta(days=1))]["cohort_size"] == 0
    # And the newest cohort in the same window has not reached thirty days at all.
    assert rows[str(today - timedelta(days=9))]["retention_30d"] is None


async def test_every_arrival_date_in_the_window_gets_a_row(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """A gap in arrivals is a row with nothing in it, not a date missing from the table."""
    del retention_engine
    body = _retention_body(database_url, "days=40")
    today = datetime.now(UTC).date()

    assert body["from_date"] == str(today - timedelta(days=39))
    assert body["to_date"] == str(today)
    assert [row["cohort_date"] for row in body["cohorts"]] == [
        str(today - timedelta(days=39 - index)) for index in range(40)
    ]
    empty = _cohort_rows(body)[str(today - timedelta(days=20))]
    assert empty["cohort_size"] == 0
    assert empty["retained_7d"] is None
    assert empty["retention_7d"] is None


async def test_the_retention_response_says_what_it_measured(
    retention_engine: AsyncEngine, database_url: str
) -> None:
    """AC4/AC5: the horizons, and the four conventions a quoted rate needs."""
    del retention_engine
    body = _retention_body(database_url)

    assert body["horizons"] == [7, 30]
    assert body["days"] == 60
    assert "cohort_size" in body["window_convention"]
    assert "not zero" in body["maturity_convention"].lower()
    assert "observability_product_actor_daily" in body["source_convention"]
    assert "raw ledger is never scanned" in body["source_convention"]
    assert "login" in body["actor_convention"]


async def test_the_retention_route_refuses_anonymous_and_non_operator_callers(
    database_url: str,
) -> None:
    """AC5: the same flat operator requirement as every other read in the module."""
    assert _client(database_url).get(RETENTION_PATH).status_code == 401
    forbidden = _client(database_url).get(RETENTION_PATH, headers=_bearer("patient"))
    assert forbidden.status_code == 403


@pytest.mark.parametrize("days", [0, 366])
async def test_the_retention_route_refuses_a_window_outside_its_bounds(
    database_url: str, days: int
) -> None:
    with _client(database_url) as client:
        response = client.get(f"{RETENTION_PATH}?days={days}", headers=_bearer())
    assert response.status_code == 422
