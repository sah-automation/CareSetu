"""C1 #706/#707: the MOD-013 operator observability read routes.

The routes are thin adapters (api-standards §1): resolve the gateway
``Principal`` through ``require_operator``, validate the query params, call the
observability read facade, and answer its typed view. The facade is stubbed
here; the aggregation SQL belongs to ``test_observability_read_facade`` and the
seeded integration round-trip.

Operator-scoped JWTs drive the gateway's admit/deny exactly like the audit and
access-history route tests: anonymous -> 401, any non-operator scope -> 403, both
through the shared gateway envelope, with the facade never reached.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.observability.facade import (
    AlertEntry,
    AlertPage,
    BreakerHealthRow,
    BusinessCountView,
    CaptureLiveness,
    CostBudgetView,
    CostSummary,
    CostTrend,
    CostTrendPoint,
    Deeplinks,
    DependencyHealth,
    LatencyReport,
    LatencyRow,
    OutboxHealthRow,
    Overview,
    ProviderBoardReport,
    ProviderBoardRow,
    ProviderQualityRow,
    QualityReport,
    RouteThroughputRow,
    SystemHealth,
    ThroughputPoint,
    ThroughputReport,
    UsageReport,
    UsageRow,
)

_SIGNING_KEY = "unit-test-observability-read-signing-key"

_TODAY = date(2026, 10, 12)
_FROM = _TODAY - timedelta(days=29)
_FROM_TS = datetime(2026, 10, 14, 11, 34, 56, tzinfo=UTC)
_TO_TS = datetime(2026, 10, 14, 12, 34, 56, tzinfo=UTC)

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
DEEPLINKS_PATH = "/v1/operator/observability/deeplinks"

_ALERT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

_SUMMARY = CostSummary(
    period_start=date(2026, 10, 1),
    period_end=date(2026, 10, 31),
    total_spend_paise=90_000,
    total_limit_paise=150_000,
    remaining_paise=60_000,
    utilization_pct=Decimal("60.00"),
    exhausted=False,
    budgets=[
        CostBudgetView(
            provider="openai",
            model="gpt-4o-mini",
            monthly_limit_paise=150_000,
            alert_threshold_pct=80,
            current_spend_paise=90_000,
            billing_period_start=date(2026, 10, 1),
            billing_period_end=date(2026, 10, 31),
            remaining_paise=60_000,
            utilization_pct=Decimal("60.00"),
            exhausted=False,
        )
    ],
)

_TREND = CostTrend(
    days=30,
    from_date=_FROM,
    to_date=_TODAY,
    points=[
        CostTrendPoint(usage_date=date(2026, 10, 11), calls=4, cost_paise=70),
        CostTrendPoint(usage_date=date(2026, 10, 12), calls=6, cost_paise=110),
    ],
)

_USAGE = UsageReport(
    days=30,
    from_date=_FROM,
    to_date=_TODAY,
    total_calls=9,
    total_input_tokens=1_520,
    total_output_tokens=290,
    total_cost_paise=350,
    rows=[
        UsageRow(
            provider="openai",
            model="gpt-4o-mini",
            task_type="triage",
            calls=5,
            success_count=4,
            failure_count=1,
            timeout_count=0,
            input_tokens=1_000,
            output_tokens=200,
            cost_paise=250,
        )
    ],
)

_QUALITY = QualityReport(
    days=30,
    from_date=_FROM,
    to_date=_TODAY,
    total_calls=9,
    success_count=7,
    failure_count=1,
    timeout_count=1,
    low_confidence_count=2,
    success_rate=Decimal("0.7778"),
    low_confidence_rate=Decimal("0.2857"),
    providers=[
        ProviderQualityRow(
            provider="openai",
            sample_count=7,
            success_rate=Decimal("0.7778"),
            breaker_state="closed",
        )
    ],
)


_OVERVIEW = Overview(
    days=30,
    from_date=_FROM,
    to_date=_TODAY,
    total_calls=9,
    success_count=7,
    success_rate=Decimal("0.7778"),
    low_confidence_count=2,
    low_confidence_rate=Decimal("0.2857"),
    p95_duration_ms=Decimal("8400.00"),
    spend_paise=90_000,
    budget_paise=150_000,
    budget_utilization_pct=Decimal("60.00"),
    budget_exhausted=False,
    open_alerts=4,
    critical_open_alerts=1,
    open_breakers=1,
    business_counts=[BusinessCountView(metric_key="case.consult_complete", count=6)],
    last_rolled_date=_TODAY,
)

_LATENCY = LatencyReport(
    last_rolled_date=_TODAY,
    providers=[
        LatencyRow(
            provider="openai",
            sample_count=8,
            p50_duration_ms=Decimal("1200.00"),
            p95_duration_ms=Decimal("8400.00"),
            p99_duration_ms=Decimal("15100.00"),
            window_start=datetime(2026, 10, 12, tzinfo=UTC),
            window_end=datetime(2026, 10, 13, tzinfo=UTC),
        )
    ],
)

#: The degraded-provider board (B9 #728). Three providers on purpose: one down, one
#: degraded by quota refusals, one idle and therefore healthy - the third is the row
#: that would silently read as an outage if "no traffic" were folded into "no data".
_PROVIDER_BOARD = ProviderBoardReport(
    last_rolled_date=_TODAY,
    providers=[
        ProviderBoardRow(
            provider="anthropic",
            status="down",
            breaker_state="open",
            success_rate=Decimal("0.0000"),
            sample_count=0,
            timeout_count=3,
            rate_limit_count=0,
            p50_duration_ms=None,
            p95_duration_ms=None,
            p99_duration_ms=None,
            last_error="ConnectError",
            window_start=datetime(2026, 10, 12, tzinfo=UTC),
            window_end=datetime(2026, 10, 13, tzinfo=UTC),
        ),
        ProviderBoardRow(
            provider="openai",
            status="degraded",
            breaker_state="closed",
            success_rate=Decimal("0.8750"),
            sample_count=8,
            timeout_count=1,
            rate_limit_count=2,
            p50_duration_ms=Decimal("1200.00"),
            p95_duration_ms=Decimal("8400.00"),
            p99_duration_ms=Decimal("15100.00"),
            last_error="rate_limited",
            window_start=datetime(2026, 10, 12, tzinfo=UTC),
            window_end=datetime(2026, 10, 13, tzinfo=UTC),
        ),
        ProviderBoardRow(
            provider="together-ai",
            status="healthy",
            breaker_state="closed",
            success_rate=None,
            sample_count=0,
            timeout_count=0,
            rate_limit_count=0,
            p50_duration_ms=None,
            p95_duration_ms=None,
            p99_duration_ms=None,
            last_error=None,
            window_start=None,
            window_end=None,
        ),
    ],
)

#: The busy case: traffic recorded, some of it failed. The EMPTY case is the one the
#: ticket exists for - see ``_NO_THROUGHPUT``.
_THROUGHPUT = ThroughputReport(
    minutes=60,
    from_ts=_FROM_TS,
    to_ts=_TO_TS,
    requests=14,
    errors=3,
    error_rate=Decimal("0.2143"),
    requests_per_minute=Decimal("0.23"),
    points=[
        ThroughputPoint(
            minute_ts=datetime(2026, 10, 14, 12, 34, tzinfo=UTC),
            requests=14,
            errors=3,
            error_rate=Decimal("0.2143"),
        )
    ],
    routes=[
        RouteThroughputRow(
            route_template="/v1/cases/{case_id}/entries",
            method="POST",
            requests=14,
            errors=3,
            error_rate=Decimal("0.2143"),
        )
    ],
    routes_total=1,
    capture=CaptureLiveness(
        capturing=True,
        requests_recorded=14,
        last_recorded_at=datetime(2026, 10, 14, 12, 34, tzinfo=UTC),
    ),
)

#: Nothing recorded in the window: every rate null rather than zero, and capture
#: reporting itself as not watching. A route that answered this with ``0.0000``
#: would be indistinguishable from a healthy hour.
_NO_THROUGHPUT = ThroughputReport(
    minutes=60,
    from_ts=_FROM_TS,
    to_ts=_TO_TS,
    requests=0,
    errors=0,
    error_rate=None,
    requests_per_minute=None,
    points=[],
    routes=[],
    routes_total=0,
    capture=CaptureLiveness(capturing=False, requests_recorded=0, last_recorded_at=None),
)

_HEALTH = SystemHealth(
    dependencies=[
        DependencyHealth(name="database", status="up", latency_ms=Decimal("1.20")),
        DependencyHealth(name="cache", status="disabled", detail="REDIS_URL is unset"),
    ],
    outbox=[
        OutboxHealthRow(
            table_schema="iam",
            table="iam_outbox",
            pending=7,
            inflight=2,
            dead_letter=1,
            backlog=9,
        )
    ],
    outbox_backlog=9,
    dead_letter_rows=1,
    breakers=[BreakerHealthRow(provider="anthropic", breaker_state="open")],
    open_breakers=1,
)

_ALERTS = AlertPage(
    total_count=1,
    alerts=[
        AlertEntry(
            id=_ALERT_ID,
            severity="critical",
            kind="breaker_open",
            title="AI provider breaker open for anthropic",
            payload={"source": "rollup", "provider": "anthropic"},
            status="open",
            created_at=datetime(2026, 10, 12, 3, 0, tzinfo=UTC),
            acked_by=None,
            acked_at=None,
        )
    ],
)


class StubObservabilityFacade:
    """Facade stand-in recording the calls each route made.

    The signatures mirror :class:`~modules.observability.facade.ObservabilityFacade`:
    the route always passes ``days`` explicitly, so no default is repeated here.
    """

    def __init__(self) -> None:
        self.summary_calls = 0
        self.trend_days: list[int] = []
        self.usage_days: list[int] = []
        self.quality_days: list[int] = []
        self.overview_days: list[int] = []
        self.latency_calls = 0
        self.provider_board_calls = 0
        self.throughput_minutes: list[int] = []
        self.throughput_empty = False
        self.health_cache_flags: list[bool] = []
        self.alert_pages: list[tuple[int, int]] = []
        self.alert_statuses: list[str | None] = []
        self.deeplink_settings: list[dict[str, Any]] = []

    async def get_cost_summary(self) -> CostSummary:
        self.summary_calls += 1
        return _SUMMARY

    async def get_cost_trend(self, *, days: int) -> CostTrend:
        self.trend_days.append(days)
        return _TREND.model_copy(update={"days": days})

    async def get_usage(self, *, days: int) -> UsageReport:
        self.usage_days.append(days)
        return _USAGE.model_copy(update={"days": days})

    async def get_quality(self, *, days: int) -> QualityReport:
        self.quality_days.append(days)
        return _QUALITY.model_copy(update={"days": days})

    async def get_overview(self, *, days: int) -> Overview:
        self.overview_days.append(days)
        return _OVERVIEW.model_copy(update={"days": days})

    async def get_latency(self) -> LatencyReport:
        self.latency_calls += 1
        return _LATENCY

    async def get_provider_board(self) -> ProviderBoardReport:
        self.provider_board_calls += 1
        return _PROVIDER_BOARD

    async def get_throughput(self, *, minutes: int) -> ThroughputReport:
        self.throughput_minutes.append(minutes)
        view = _NO_THROUGHPUT if self.throughput_empty else _THROUGHPUT
        return view.model_copy(update={"minutes": minutes})

    async def get_health(self, *, cache_configured: bool) -> SystemHealth:
        self.health_cache_flags.append(cache_configured)
        return _HEALTH

    async def get_alerts(
        self, *, page: int, page_size: int, status: str | None = None
    ) -> AlertPage:
        self.alert_pages.append((page, page_size))
        self.alert_statuses.append(status)
        return _ALERTS

    def get_deeplinks(
        self,
        *,
        grafana_url: str | None = None,
        sentry_dsn: str | None = None,
        langfuse_host: str | None = None,
        langfuse_public_key: str | None = None,
    ) -> Deeplinks:
        self.deeplink_settings.append(
            {
                "grafana_url": grafana_url,
                "sentry_dsn": sentry_dsn,
                "langfuse_host": langfuse_host,
                "langfuse_public_key": langfuse_public_key,
            }
        )
        return Deeplinks(grafana=grafana_url or None)


def _token(*, subject_id: int = 1, scope: str = "operator") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(
    facade: StubObservabilityFacade | None = None, *, settings: Settings | None = None
) -> TestClient:
    resolved = settings or Settings(
        gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY
    )
    app = create_app(settings=resolved)
    app.state.observability_facade = facade if facade is not None else StubObservabilityFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _operator() -> dict[str, str]:
    return _bearer(_token())


# ------------------------------------------------------------------ admits


def test_operator_reads_spend_against_the_budget() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(COST_PATH, headers=_operator())

    assert response.status_code == 200
    assert response.json() == _SUMMARY.model_dump(mode="json")
    assert facade.summary_calls == 1


def test_cost_trend_defaults_to_a_thirty_day_window() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(TREND_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.trend_days == [30]
    body = response.json()
    assert body["days"] == 30
    assert [point["usage_date"] for point in body["points"]] == ["2026-10-11", "2026-10-12"]


def test_cost_trend_honours_a_validated_days_param() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{TREND_PATH}?days=7", headers=_operator())

    assert response.status_code == 200
    assert facade.trend_days == [7]
    assert response.json()["days"] == 7


def test_operator_reads_usage_by_provider_and_task() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{USAGE_PATH}?days=14", headers=_operator())

    assert response.status_code == 200
    assert facade.usage_days == [14]
    body = response.json()
    assert body["total_calls"] == 9
    assert body["total_cost_paise"] == 350
    assert body["rows"][0]["provider"] == "openai"
    assert body["rows"][0]["task_type"] == "triage"


def test_operator_reads_quality_rates() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(QUALITY_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.quality_days == [30]
    body = response.json()
    assert body["success_rate"] == "0.7778"
    assert body["low_confidence_rate"] == "0.2857"
    assert body["providers"][0]["breaker_state"] == "closed"


# ------------------------------------------------- C1b (#707): the five reads


def test_operator_reads_the_headline_kpis() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(OVERVIEW_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.overview_days == [30]
    body = response.json()
    assert body["days"] == 30
    assert body["total_calls"] == 9
    assert body["success_rate"] == "0.7778"
    assert body["spend_paise"] == 90_000
    assert body["budget_paise"] == 150_000
    assert body["open_alerts"] == 4
    assert body["critical_open_alerts"] == 1
    assert body["open_breakers"] == 1
    assert body["business_counts"] == [{"metric_key": "case.consult_complete", "count": 6}]
    assert body["last_rolled_date"] == _TODAY.isoformat()


def test_overview_honours_a_validated_days_param() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{OVERVIEW_PATH}?days=7", headers=_operator())

    assert response.status_code == 200
    assert facade.overview_days == [7]


def test_operator_reads_provider_latency_percentiles() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(LATENCY_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.latency_calls == 1
    body = response.json()
    assert body["last_rolled_date"] == _TODAY.isoformat()
    row = body["providers"][0]
    assert (row["provider"], row["sample_count"]) == ("openai", 8)
    assert row["p50_duration_ms"] == "1200.00"
    assert row["p95_duration_ms"] == "8400.00"
    assert row["p99_duration_ms"] == "15100.00"


def test_the_provider_board_answers_healthy_degraded_and_down_per_provider() -> None:
    """#717 story 37: triage without reading numbers."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(PROVIDERS_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.provider_board_calls == 1
    body = response.json()
    assert body["last_rolled_date"] == _TODAY.isoformat()
    assert [(row["provider"], row["status"]) for row in body["providers"]] == [
        ("anthropic", "down"),
        ("openai", "degraded"),
        ("together-ai", "healthy"),
    ]


def test_the_provider_board_carries_the_figures_and_quoted_decimals() -> None:
    """Every input to the verdict is on the row, and rates travel as exact strings."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    row = client.get(PROVIDERS_PATH, headers=_operator()).json()["providers"][1]

    assert row["breaker_state"] == "closed"
    assert row["success_rate"] == "0.8750"
    assert (row["timeout_count"], row["rate_limit_count"]) == (1, 2)
    assert (row["p50_duration_ms"], row["p95_duration_ms"], row["p99_duration_ms"]) == (
        "1200.00",
        "8400.00",
        "15100.00",
    )
    # The named failure, so the operator reads it rather than inferring it.
    assert row["last_error"] == "rate_limited"


def test_the_provider_board_distinguishes_idle_from_broken() -> None:
    """A provider with no traffic reads healthy, with nulls - never as an outage.

    The nulls are the load-bearing part: ``0.0000`` here would say the provider was
    asked and refused, which is the opposite fact.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    row = client.get(PROVIDERS_PATH, headers=_operator()).json()["providers"][2]

    assert row["success_rate"] is None
    assert (row["p50_duration_ms"], row["p95_duration_ms"], row["p99_duration_ms"]) == (
        None,
        None,
        None,
    )
    assert row["last_error"] is None


def test_throughput_defaults_to_the_last_hour_in_minutes() -> None:
    """Minutes, not days: the counter's grain is a minute and the read asks at it."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(THROUGHPUT_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.throughput_minutes == [60]
    body = response.json()
    assert body["minutes"] == 60
    assert body["requests"] == 14
    assert body["errors"] == 3
    assert body["error_rate"] == "0.2143"
    assert body["requests_per_minute"] == "0.23"
    assert body["routes"][0]["route_template"] == "/v1/cases/{case_id}/entries"
    assert body["capture"]["capturing"] is True


def test_throughput_honours_a_validated_minutes_param() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{THROUGHPUT_PATH}?minutes=15", headers=_operator())

    assert response.status_code == 200
    assert facade.throughput_minutes == [15]


@pytest.mark.parametrize("minutes", ["0", "-1", "1441", "abc"])
def test_an_out_of_range_throughput_window_is_rejected_at_the_edge(minutes: str) -> None:
    """A wide window is a table scan, so it is refused before the facade is reached."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{THROUGHPUT_PATH}?minutes={minutes}", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.throughput_minutes == []


def test_throughput_says_no_requests_were_recorded_rather_than_nothing_failed() -> None:
    """#727: the answer that stops an empty feed reading as a healthy system.

    The wire shape is the whole point - null rates plus ``capturing: false`` - and a
    zeroed body would be indistinguishable from a clean hour.
    """
    facade = StubObservabilityFacade()
    facade.throughput_empty = True
    client = _client(facade)

    body = client.get(THROUGHPUT_PATH, headers=_operator()).json()

    assert body["requests"] == 0
    assert body["error_rate"] is None
    assert body["requests_per_minute"] is None
    assert body["points"] == []
    assert body["capture"] == {
        "capturing": False,
        "requests_recorded": 0,
        "last_recorded_at": None,
    }


def test_throughput_rates_are_exact_decimals_not_binary_floats() -> None:
    """api-standards: derived ratios keep their scale on the wire, as strings."""
    client = _client()

    body = client.get(THROUGHPUT_PATH, headers=_operator()).json()

    assert isinstance(body["error_rate"], str)
    assert Decimal(body["error_rate"]) == Decimal("0.2143")
    assert isinstance(body["requests_per_minute"], str)
    assert Decimal(body["requests_per_minute"]) == Decimal("0.23")


def test_health_reports_dependencies_outbox_and_breakers() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(HEALTH_PATH, headers=_operator())

    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body["dependencies"]] == ["database", "cache"]
    assert body["outbox_backlog"] == 9
    assert body["dead_letter_rows"] == 1
    assert body["open_breakers"] == 1
    assert body["outbox"][0]["table_schema"] == "iam"


def test_health_reports_an_unconfigured_cache_as_disabled() -> None:
    """An unset ``REDIS_URL`` is a configuration choice, never a dialled store."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(HEALTH_PATH, headers=_operator())

    assert facade.health_cache_flags == [False]
    cache = next(e for e in response.json()["dependencies"] if e["name"] == "cache")
    assert cache["status"] == "disabled"


def test_health_resolves_a_configured_cache_from_settings() -> None:
    facade = StubObservabilityFacade()
    client = _client(
        facade,
        settings=Settings(
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_SIGNING_KEY,
            redis_url="redis://localhost:6379/0",
        ),
    )

    response = client.get(HEALTH_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.health_cache_flags == [True]


def test_alerts_default_to_the_first_page_of_twenty_five() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(ALERTS_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.alert_pages == [(1, 25)]
    assert facade.alert_statuses == [None]
    body = response.json()
    assert body["total_count"] == 1
    assert body["alerts"][0]["kind"] == "breaker_open"
    assert body["alerts"][0]["payload"] == {"source": "rollup", "provider": "anthropic"}


@pytest.mark.parametrize("status", ["open", "resolved"])
def test_alerts_narrow_to_a_recognised_status(status: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{ALERTS_PATH}?status={status}&page=3&page_size=5", headers=_operator())

    assert response.status_code == 200
    assert facade.alert_statuses == [status]
    assert facade.alert_pages == [(3, 5)]


def test_deeplinks_answer_the_configured_vendors() -> None:
    facade = StubObservabilityFacade()
    client = _client(
        facade,
        settings=Settings(
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_SIGNING_KEY,
            grafana_url="https://caresetu.grafana.net",
        ),
    )

    response = client.get(DEEPLINKS_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.deeplink_settings == [
        {
            "grafana_url": "https://caresetu.grafana.net",
            "sentry_dsn": "",
            "langfuse_host": Settings().langfuse_host,
            "langfuse_public_key": "",
        }
    ]
    assert response.json() == {
        "grafana": "https://caresetu.grafana.net",
        "sentry": None,
        "langfuse": None,
    }


def test_no_configured_vendor_answers_absent_links_not_an_error() -> None:
    """The plan's vendors are env-gated; an unconfigured one is a null link, not a 5xx."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(DEEPLINKS_PATH, headers=_operator())

    assert response.status_code == 200
    assert response.json() == {"grafana": None, "sentry": None, "langfuse": None}


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    "path",
    [TREND_PATH, USAGE_PATH, QUALITY_PATH, OVERVIEW_PATH],
)
@pytest.mark.parametrize("days", ["0", "-1", "366", "abc", "1.5"])
def test_out_of_range_window_is_rejected_at_the_edge(path: str, days: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{path}?days={days}", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    # Rejected before the facade: no query ran for an invalid window.
    assert facade.trend_days == []
    assert facade.usage_days == []
    assert facade.quality_days == []
    assert facade.overview_days == []


@pytest.mark.parametrize(
    "query",
    ["page_size=0", "page_size=101", "page=0", "page=abc", "page_size=abc"],
)
def test_out_of_range_alert_paging_is_rejected_at_the_edge(query: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{ALERTS_PATH}?{query}", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.alert_pages == []


@pytest.mark.parametrize("status", ["acked", "OPEN", "all"])
def test_an_unrecognised_alert_status_is_rejected_at_the_edge(status: str) -> None:
    """A typo must not read as an empty feed, which would say "nothing is wrong"."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{ALERTS_PATH}?status={status}", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.alert_statuses == []


# ------------------------------------------------------------------ refuses


_ALL_PATHS = [
    COST_PATH,
    TREND_PATH,
    USAGE_PATH,
    QUALITY_PATH,
    OVERVIEW_PATH,
    LATENCY_PATH,
    PROVIDERS_PATH,
    THROUGHPUT_PATH,
    HEALTH_PATH,
    ALERTS_PATH,
    DEEPLINKS_PATH,
]


@pytest.mark.parametrize("path", _ALL_PATHS)
def test_anonymous_read_denied_with_401(path: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(path)

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"
    assert _facade_untouched(facade)


@pytest.mark.parametrize("path", _ALL_PATHS)
@pytest.mark.parametrize("scope", ["patient", "partner"])
def test_non_operator_scope_denied_with_403(path: str, scope: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(path, headers=_bearer(_token(scope=scope)))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert _facade_untouched(facade)


def _facade_untouched(facade: StubObservabilityFacade) -> bool:
    return (
        facade.summary_calls == 0
        and facade.trend_days == []
        and facade.usage_days == []
        and facade.quality_days == []
        and facade.overview_days == []
        and facade.latency_calls == 0
        and facade.provider_board_calls == 0
        and facade.throughput_minutes == []
        and facade.health_cache_flags == []
        and facade.alert_pages == []
        and facade.deeplink_settings == []
    )


# ------------------------------------------------------------------ wiring


@pytest.mark.parametrize("path", _ALL_PATHS)
def test_every_read_route_is_registered(path: str) -> None:
    app = create_app()

    assert path in app.openapi()["paths"]


def test_read_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    assert JWTVerifyMiddleware in {middleware.cls for middleware in app.user_middleware}
