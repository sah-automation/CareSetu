"""C1a #706: the MOD-013 operator observability read routes.

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

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.observability.facade import (
    CostBudgetView,
    CostSummary,
    CostTrend,
    CostTrendPoint,
    ProviderQualityRow,
    QualityReport,
    UsageReport,
    UsageRow,
)

_SIGNING_KEY = "unit-test-observability-read-signing-key"

_TODAY = date(2026, 10, 12)
_FROM = _TODAY - timedelta(days=29)

COST_PATH = "/v1/operator/observability/cost"
TREND_PATH = "/v1/operator/observability/cost/trend"
USAGE_PATH = "/v1/operator/observability/usage"
QUALITY_PATH = "/v1/operator/observability/quality"

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


def _token(*, subject_id: int = 1, scope: str = "operator") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubObservabilityFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
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


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    "path",
    [TREND_PATH, USAGE_PATH, QUALITY_PATH],
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


# ------------------------------------------------------------------ refuses


_ALL_PATHS = [COST_PATH, TREND_PATH, USAGE_PATH, QUALITY_PATH]


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
    )


# ------------------------------------------------------------------ wiring


@pytest.mark.parametrize("path", _ALL_PATHS)
def test_every_read_route_is_registered(path: str) -> None:
    app = create_app()

    assert path in app.openapi()["paths"]


def test_read_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    assert JWTVerifyMiddleware in {middleware.cls for middleware in app.user_middleware}
