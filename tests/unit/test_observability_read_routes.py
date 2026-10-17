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
    BUSINESS_PERIODS,
    ERROR_STATUS_VOCABULARY,
    ActorSpendDistribution,
    AlertEntry,
    AlertPage,
    BreakerHealthRow,
    BusinessCountView,
    BusinessRead,
    CaptureLiveness,
    CostBudgetView,
    CostSummary,
    CostTrend,
    CostTrendPoint,
    Deeplinks,
    DependencyHealth,
    DoctorSpend,
    ErrorFeedEntry,
    ErrorFeedPage,
    LatencyReport,
    LatencyRow,
    MarginPercent,
    MarginRead,
    ModelSpend,
    OutboxHealthRow,
    Overview,
    PatientSpend,
    ProjectionBasis,
    ProviderBoardReport,
    ProviderBoardRow,
    ProviderQualityRow,
    ProviderSpend,
    QualityReport,
    QueueDepthRow,
    ReliabilityReport,
    RouteThroughputRow,
    SystemHealth,
    TaskTypeSpend,
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
RELIABILITY_PATH = "/v1/operator/observability/reliability"
ALERTS_PATH = "/v1/operator/observability/alerts"
ERRORS_PATH = "/v1/operator/observability/errors"
DEEPLINKS_PATH = "/v1/operator/observability/deeplinks"
BUSINESS_PATH = "/v1/operator/observability/business"

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

_RELIABILITY = ReliabilityReport(
    queues=[
        QueueDepthRow(
            queue="structure",
            depth=2,
            oldest_enqueued_at=datetime(2026, 10, 16, 11, 20, tzinfo=UTC),
            oldest_age_s=2400,
        )
    ],
    queue_depth=2,
    oldest_queued_age_s=2400,
    outbox=[
        OutboxHealthRow(
            table_schema="intake",
            table="intake_outbox",
            pending=2,
            inflight=1,
            dead_letter=1,
            backlog=3,
        )
    ],
    outbox_backlog=3,
    dead_letter_rows=1,
    # Named for what it is: RECENT activity, never simultaneous concurrency.
    recent_active_actors=7,
    activity_window_minutes=60,
    concurrency_grafana_link="https://caresetu.grafana.net/explore?left=%7B%7D",
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

_ERRORS = ErrorFeedPage(
    total_count=1,
    total_occurrences=412,
    window_minutes=60,
    errors=[
        ErrorFeedEntry(
            fingerprint="a" * 64,
            # The TEMPLATE: the shape below is what keeps a concrete request path -
            # and the identifier in it - out of the response.
            route_template="/v1/cases/{case_id}/entries",
            method="POST",
            status_code=500,
            status_class="5xx",
            kind="unhandled_exception",
            code="INTERNAL_SERVER_ERROR",
            trace_id="trace-abc123",
            occurrences=412,
            first_seen_at=datetime(2026, 10, 14, 11, 30, tzinfo=UTC),
            last_seen_at=datetime(2026, 10, 14, 12, 30, tzinfo=UTC),
            status="open",
        )
    ],
)


_BUSINESS = BusinessRead(
    period="month_to_date",
    period_start=date(2026, 10, 1),
    period_end=date(2026, 10, 12),
    spend_paise=90_000,
    jobs=10,
    input_tokens=440_000,
    output_tokens=50_000,
    paise_per_1k_input_tokens=Decimal("204.5455"),
    paise_per_1k_output_tokens=Decimal("1800.0000"),
    monthly_cap_paise=150_000,
    cap_consumed_paise=90_000,
    cap_consumed_pct=Decimal("60.00"),
    projected_month_end_paise=232_500,
    projected_over_cap=True,
    projection_basis=ProjectionBasis(
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        elapsed_days=12,
        period_days=31,
    ),
    by_provider=[
        ProviderSpend(
            provider="openai",
            jobs=7,
            spend_paise=30_000,
            input_tokens=140_000,
            output_tokens=20_000,
            paise_per_1k_input_tokens=Decimal("214.2857"),
            paise_per_1k_output_tokens=Decimal("1500.0000"),
        )
    ],
    by_model=[
        ModelSpend(
            provider="openai",
            model="gpt-4o-mini",
            jobs=7,
            spend_paise=30_000,
            input_tokens=140_000,
            output_tokens=20_000,
            paise_per_1k_input_tokens=Decimal("214.2857"),
            paise_per_1k_output_tokens=Decimal("1500.0000"),
        )
    ],
    by_task_type=[
        TaskTypeSpend(
            task_type="draft",
            jobs=2,
            spend_paise=20_000,
            input_tokens=40_000,
            output_tokens=20_000,
            paise_per_1k_input_tokens=Decimal("500.0000"),
            paise_per_1k_output_tokens=Decimal("1000.0000"),
        )
    ],
    # ---- #732: the unit figures, the actor attribution and the margin reason. The
    # stub is what the route serialises, so these carry figures a real read could
    # produce rather than placeholders: an operator-facing shape tested only with nulls
    # would pass even if the fields were wired to the wrong thing.
    completed_jobs=9,
    failed_jobs=1,
    cost_per_request_paise=Decimal("3000.0000"),
    cost_per_completed_task_paise=Decimal("3333.3333"),
    cost_per_patient_paise=Decimal("22500.0000"),
    cost_per_doctor_paise=Decimal("10000.0000"),
    cost_of_pass_paise=Decimal("3333.3333"),
    patient_spend=ActorSpendDistribution(
        actors=4,
        total_spend_paise=30_000,
        median_spend_paise=Decimal("5000"),
        p95_spend_paise=Decimal("20000"),
        max_spend_paise=20_000,
    ),
    doctor_spend=ActorSpendDistribution(
        actors=2,
        total_spend_paise=20_000,
        median_spend_paise=Decimal("10000"),
        p95_spend_paise=Decimal("15000"),
        max_spend_paise=15_000,
    ),
    top_patients=[
        PatientSpend(
            patient_key="patient-hash-1",
            attributed_doctor_key="doctor-hash-1",
            jobs=2,
            completed_jobs=2,
            failed_jobs=0,
            spend_paise=20_000,
        ),
        PatientSpend(
            patient_key="patient-hash-2",
            attributed_doctor_key=None,
            jobs=1,
            completed_jobs=1,
            failed_jobs=0,
            spend_paise=7_000,
        ),
    ],
    top_doctors=[
        DoctorSpend(
            doctor_key="doctor-hash-1",
            patients=2,
            jobs=2,
            completed_jobs=2,
            failed_jobs=0,
            spend_paise=15_000,
        )
    ],
    margin=MarginRead(
        revenue_paise=0,
        cost_of_goods_paise=30_000,
        headline_month_cost_of_goods_paise=90_000,
        revenue_captured=False,
        tiers_captured=False,
        tier_keys=[],
        # No revenue captured, so BOTH percentages are absent WITH the reason - never a
        # zero, which would be indistinguishable from a genuinely free month.
        gross_margin=MarginPercent(
            value=None, reason="revenue_not_captured", detail="Revenue is not captured yet."
        ),
        ai_cost_pct_of_revenue=MarginPercent(
            value=None, reason="revenue_not_captured", detail="Revenue is not captured yet."
        ),
    ),
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
        self.reliability_calls: list[tuple[int, str | None]] = []
        self.alert_pages: list[tuple[int, int]] = []
        self.alert_statuses: list[str | None] = []
        self.error_feed_calls: list[tuple[int, int, str | None, int]] = []
        self.deeplink_settings: list[dict[str, Any]] = []
        self.business_periods: list[str] = []

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

    async def get_reliability(
        self, *, minutes: int, grafana_url: str | None = None, now: datetime | None = None
    ) -> ReliabilityReport:
        self.reliability_calls.append((minutes, grafana_url))
        return _RELIABILITY.model_copy(update={"activity_window_minutes": minutes})

    async def get_alerts(
        self, *, page: int, page_size: int, status: str | None = None
    ) -> AlertPage:
        self.alert_pages.append((page, page_size))
        self.alert_statuses.append(status)
        return _ALERTS

    async def get_error_feed(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        minutes: int,
        now: datetime | None = None,
    ) -> ErrorFeedPage:
        self.error_feed_calls.append((page, page_size, status, minutes))
        return _ERRORS.model_copy(update={"window_minutes": minutes})

    async def get_business(self, *, period: str) -> BusinessRead:
        self.business_periods.append(period)
        return _BUSINESS.model_copy(update={"period": period})

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


def test_reliability_reports_queue_depth_age_activity_and_the_concurrency_link() -> None:
    """The wire names must say RECENT ACTIVITY, and concurrency must be a link.

    Both are named acceptance criteria (#729): the field an operator reads has to
    be labelled for what it measures, and the one figure that is genuinely
    simultaneous must arrive as a link rather than as a stored number.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(RELIABILITY_PATH, headers=_operator())

    assert response.status_code == 200
    body = response.json()
    assert facade.reliability_calls == [(60, "")]
    assert [(row["queue"], row["depth"], row["oldest_age_s"]) for row in body["queues"]] == [
        ("structure", 2, 2400)
    ]
    assert body["queue_depth"] == 2
    assert body["oldest_queued_age_s"] == 2400
    # The per-outbox BREAKDOWN, with the dead-letter total beside it: a stuck module
    # has to be identifiable rather than averaged into one number.
    assert [(row["table_schema"], row["backlog"]) for row in body["outbox"]] == [("intake", 3)]
    assert body["outbox_backlog"] == 3
    assert body["dead_letter_rows"] == 1
    assert body["recent_active_actors"] == 7
    assert body["activity_window_minutes"] == 60
    assert "concurrency" not in body
    assert body["concurrency_grafana_link"].startswith("https://caresetu.grafana.net/explore")


def test_reliability_honours_the_requested_activity_window_and_refuses_a_non_positive_one() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{RELIABILITY_PATH}?minutes=15", headers=_operator())

    assert response.status_code == 200
    assert facade.reliability_calls == [(15, "")]
    assert response.json()["activity_window_minutes"] == 15

    refused = client.get(f"{RELIABILITY_PATH}?minutes=0", headers=_operator())
    assert refused.status_code == 422
    # The ceiling is a response bound, not a system limit, so it is refused at the
    # edge rather than by the read discovering it mid-query.
    assert client.get(f"{RELIABILITY_PATH}?minutes=100000", headers=_operator()).status_code == 422


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


# ------------------------------------------------------------------ errors


def test_the_error_feed_defaults_to_the_first_page_over_the_last_hour() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(ERRORS_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.error_feed_calls == [(1, 25, None, 60)]
    body = response.json()
    # Two counts, because "one failure 412 times" and "412 failures" are different
    # pages and a client labelling it has to know which it is holding.
    assert (body["total_count"], body["total_occurrences"]) == (1, 412)
    assert body["window_minutes"] == 60
    entry = body["errors"][0]
    assert entry["route_template"] == "/v1/cases/{case_id}/entries"
    assert (entry["method"], entry["status_code"], entry["status_class"]) == ("POST", 500, "5xx")
    # The join key that reaches the trace, and the collapse count behind the entry.
    assert entry["trace_id"] == "trace-abc123"
    assert entry["occurrences"] == 412
    assert entry["status"] == "open"


@pytest.mark.parametrize("status", ["open", "resolved"])
def test_the_error_feed_narrows_to_a_recognised_status(status: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(
        f"{ERRORS_PATH}?status={status}&page=3&page_size=5&minutes=240", headers=_operator()
    )

    assert response.status_code == 200
    assert facade.error_feed_calls == [(3, 5, status, 240)]


def test_the_error_feed_carries_no_capture_verdict_of_its_own() -> None:
    """An empty page is ambiguous; ``/throughput``'s ``capture`` is what says which.

    Answering it here too would make two places to keep honest for one verdict, and
    two that could disagree is worse than one the operator has to look beside.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    body = client.get(ERRORS_PATH, headers=_operator()).json()

    assert "capture" not in body


@pytest.mark.parametrize(
    "query",
    ["page_size=0", "page_size=101", "page=0", "page=abc", "minutes=0", "minutes=1441"],
)
def test_out_of_range_error_feed_paging_is_rejected_at_the_edge(query: str) -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{ERRORS_PATH}?{query}", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.error_feed_calls == []


@pytest.mark.parametrize("status", ["acked", "OPEN", "all"])
def test_an_unrecognised_error_status_is_rejected_at_the_edge(status: str) -> None:
    """A typo must not read as an empty feed, which would say "nothing is failing"."""
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{ERRORS_PATH}?status={status}", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.error_feed_calls == []


def test_an_error_status_no_writer_can_produce_is_not_offered_as_a_filter() -> None:
    """``acknowledged`` is 422 today, and that is a fact about the DATA, not a cap.

    Acknowledgement is an action against ``observability_alert_events``; nothing
    writes one to a captured error, so accepting the filter would hand an operator a
    button that can only ever return nothing. Kept as its own named assertion - rather
    than folded into the typo list above - so that whoever makes acknowledgement reach
    captured errors has exactly one line to change, and so the change is a deliberate
    one rather than something the set happens to allow.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{ERRORS_PATH}?status=acknowledged", headers=_operator())

    assert response.status_code == 422
    assert facade.error_feed_calls == []


def test_the_error_status_gate_matches_the_facade_vocabulary() -> None:
    """The edge gate and the facade's vocabulary are written twice, so tie them here.

    FastAPI needs a static ``Literal`` to render the accepted values into OpenAPI, so
    ``/errors`` cannot derive its gate from
    ``ERROR_STATUS_VOCABULARY``. That makes widening the filter two edits, and this is
    what makes it two edits rather than a silent drift: read the enum off the rendered
    schema and compare it to the one place the set is written down.
    """
    client = _client()

    schema = client.get("/openapi.json").json()
    status_param = next(
        parameter
        for parameter in schema["paths"][ERRORS_PATH]["get"]["parameters"]
        if parameter["name"] == "status"
    )
    # Read off the RENDERED schema rather than the annotation, so this also proves the
    # values reach a client reading the spec - which is the whole reason the gate is a
    # ``Literal`` instead of a hand-rolled check.
    rendered = next(entry for entry in status_param["schema"]["anyOf"] if "enum" in entry)["enum"]

    assert tuple(rendered) == ERROR_STATUS_VOCABULARY
    assert "open" in rendered and "resolved" in rendered


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


# ------------------------------------------------------------------ business


def test_operator_reads_period_spend_against_the_cap_with_its_breakdown() -> None:
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(BUSINESS_PATH, headers=_operator())

    assert response.status_code == 200
    # The cap figures ride every period, so a panel opened on "today" still says where
    # the month lands - which is the whole "before the cap, not after" answer.
    body = response.json()
    assert body["spend_paise"] == 90_000
    assert body["monthly_cap_paise"] == 150_000
    assert body["cap_consumed_pct"] == "60.00"
    assert body["projected_month_end_paise"] == 232_500
    assert body["projected_over_cap"] is True
    assert body["projection_basis"]["elapsed_days"] == 12
    assert body["projection_basis"]["period_days"] == 31
    # The per-thousand-token figures are quoted decimals as STRINGS too, at the rate
    # scale the other ratios use.
    assert body["paise_per_1k_input_tokens"] == "204.5455"
    assert body["paise_per_1k_output_tokens"] == "1800.0000"
    assert [row["task_type"] for row in body["by_task_type"]] == ["draft"]
    assert [(row["provider"], row["model"]) for row in body["by_model"]] == [
        ("openai", "gpt-4o-mini")
    ]
    assert [row["provider"] for row in body["by_provider"]] == ["openai"]


def test_the_business_route_carries_the_unit_metrics_and_actor_attribution() -> None:
    """The per-unit figures and the actor lists reach the wire on this ONE endpoint.

    The widening rides the read #731 already had rather than arriving as a second
    route, so what has to be proved here is that it survived the response model: a
    field added to the view and not to the schema would 200 with the number missing,
    which a panel renders as a blank rather than as an error.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    body = client.get(BUSINESS_PATH, headers=_operator()).json()

    # Quoted decimal strings at the rate scale, like every other money ratio on this
    # surface - a client parsing one and not the other would get a number and a string.
    assert body["cost_per_request_paise"] == "3000.0000"
    assert body["cost_per_completed_task_paise"] == "3333.3333"
    assert body["cost_per_patient_paise"] == "22500.0000"
    assert body["cost_per_doctor_paise"] == "10000.0000"
    assert body["cost_of_pass_paise"] == "3333.3333"
    # The distribution is over the population; the list beside it is the capped panel.
    assert body["patient_spend"]["median_spend_paise"] == "5000"
    assert body["patient_spend"]["p95_spend_paise"] == "20000"
    assert body["patient_spend"]["max_spend_paise"] == 20_000
    assert [row["patient_key"] for row in body["top_patients"]] == [
        "patient-hash-1",
        "patient-hash-2",
    ]
    # A key, never an identity: a top-patient list is people-shaped data in a
    # PHI-free schema, so the wire carries a hash and nothing a human is named by.
    assert body["top_patients"][0]["attributed_doctor_key"] == "doctor-hash-1"
    assert body["top_patients"][1]["attributed_doctor_key"] is None
    assert body["top_doctors"][0]["doctor_key"] == "doctor-hash-1"
    assert body["top_doctors"][0]["patients"] == 2


def test_the_business_route_serves_an_absent_margin_as_null_carrying_its_reason() -> None:
    """``null`` on the wire, plus a reason - never ``0.00``, which is the defect.

    This is asserted on the JSON rather than on the view because the wire is where the
    distinction is actually lost: a client cannot tell a Python ``None`` from a zero
    it was handed, but it can absolutely tell ``null`` from ``0.00``. The reason is on
    the wire for the same reason - a client that renders "revenue is not captured yet"
    is answering the operator, and one rendering a bare null is showing an empty box.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    body = client.get(BUSINESS_PATH, headers=_operator()).json()

    margin = body["margin"]
    assert margin["revenue_captured"] is False
    assert margin["tier_keys"] == []
    for figure in (margin["gross_margin"], margin["ai_cost_pct_of_revenue"]):
        assert figure["value"] is None
        assert figure["reason"] == "revenue_not_captured"
        assert figure["detail"]
    # The board number rides the same response, and is the consumed figure rather than
    # a separately derived one.
    assert margin["headline_month_cost_of_goods_paise"] == body["cap_consumed_paise"]


def test_the_business_read_defaults_to_the_month_the_cap_is_measured_against() -> None:
    """No period means "how is this month going", not "what did today cost".

    The cap it is compared against is a MONTHLY cap, so answering with a single day
    would compare one day against a month-long budget and look alarming every day.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(BUSINESS_PATH, headers=_operator())

    assert response.status_code == 200
    assert facade.business_periods == ["month_to_date"]


@pytest.mark.parametrize("period", BUSINESS_PERIODS)
def test_every_business_period_is_served_by_the_one_endpoint(period: str) -> None:
    """Three periods, one route, one facade call each - not three routes (#717 dec. 11).

    ``period`` is a window selection, so a fourth window is another value on this
    query string rather than another handler, another facade method and another
    aggregation to keep in agreement with the first three.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{BUSINESS_PATH}?period={period}", headers=_operator())

    assert response.status_code == 200
    assert facade.business_periods == [period]
    assert response.json()["period"] == period


def test_a_business_period_off_the_closed_list_is_refused_at_the_edge() -> None:
    """A misspelled period must not 200 with SOME period's spend.

    This is the read where a permissive fallback is worst: an operator would read
    another window's rupee figure as fact, with nothing in the response to contradict
    it. So the gate refuses at the edge, before the facade is reached.
    """
    facade = StubObservabilityFacade()
    client = _client(facade)

    response = client.get(f"{BUSINESS_PATH}?period=yesterday", headers=_operator())

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.business_periods == []


def test_the_business_period_gate_matches_the_facade_vocabulary() -> None:
    """The edge gate and the facade's vocabulary are written twice, so tie them here.

    FastAPI needs a static ``Literal`` to render the accepted values into OpenAPI, so
    ``/business`` cannot derive its gate from ``BUSINESS_PERIODS``. That makes adding
    a period two edits, and this is what makes it two edits rather than a silent
    drift: read the enum off the rendered schema and compare it to the one place the
    set is written down.
    """
    client = _client()

    schema = client.get("/openapi.json").json()
    period_param = next(
        parameter
        for parameter in schema["paths"][BUSINESS_PATH]["get"]["parameters"]
        if parameter["name"] == "period"
    )
    # Read off the RENDERED schema rather than the annotation, so this also proves the
    # values reach a client reading the spec. ``period`` is a plain ``Literal`` (it is
    # never nullable), so the values land directly under ``enum`` rather than in an
    # ``anyOf`` the way the feeds' optional status does.
    rendered = period_param["schema"]["enum"]

    assert tuple(rendered) == BUSINESS_PERIODS
    assert set(rendered) == {"today", "week_to_date", "month_to_date"}


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
    RELIABILITY_PATH,
    ALERTS_PATH,
    ERRORS_PATH,
    DEEPLINKS_PATH,
    BUSINESS_PATH,
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
        and facade.error_feed_calls == []
        and facade.deeplink_settings == []
        and facade.business_periods == []
    )


# ------------------------------------------------------------------ wiring


@pytest.mark.parametrize("path", _ALL_PATHS)
def test_every_read_route_is_registered(path: str) -> None:
    app = create_app()

    assert path in app.openapi()["paths"]


def test_read_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    assert JWTVerifyMiddleware in {middleware.cls for middleware in app.user_middleware}
