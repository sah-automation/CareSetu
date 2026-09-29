"""Ticket #535: the patient height/weight metrics REST surface.

The routes are thin adapters: resolve the gateway ``Principal``, call the
health facade, answer the typed view. The metrics series is patient-owned
surface - the ``require_patient`` gate admits only an authenticated patient,
so a doctor-scoped token is refused before the facade is ever consulted (the
series is never returned to a doctor via this surface - that is later,
consent-gated doctor work). Append resolves the owner from the session subject
(never client input): a client-supplied id is refused at the typed boundary,
the requested timestamp is required, and the plausible ranges are enforced by
the request model. The facade is stubbed here; the identity-scoped SQL / newest-
first ordering / pagination is the SQL-built facade-suite's job.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.health.facade import (
    HealthBackgroundMetric,
    HealthBackgroundMetricEntry,
    HealthBackgroundMetricList,
)
from modules.iam.domain.jwt import issue_token

_SIGNING_KEY = "unit-test-background-signing-key"

_TRACE_ID = "unit-trace-1234abcd"

_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)

_METRIC = HealthBackgroundMetric(height_cm=172.0, weight_kg=68.5, recorded_at=_NOW)

_METRIC_BODY = _METRIC.model_dump(mode="json")

_ENTRY = HealthBackgroundMetricEntry(
    entry_id=101,
    height_cm=172.0,
    weight_kg=68.5,
    recorded_at=_NOW,
)

_EMPTY_LIST = HealthBackgroundMetricList(items=[], total=0)


class StubHealthFacade:
    """Minimal facade stand-in recording calls and replaying canned answers."""

    def __init__(self) -> None:
        self.metric_lists: list[tuple[int, int, int]] = []
        self.appends: list[tuple[int, HealthBackgroundMetric]] = []
        self.list_view: HealthBackgroundMetricList = _EMPTY_LIST
        self.entry: HealthBackgroundMetricEntry | None = None
        self.error: Exception | None = None

    async def list_health_background_metrics(
        self,
        patient_id: int,
        *,
        page: int = 1,
        per_page: int = 25,
    ) -> HealthBackgroundMetricList:
        self.metric_lists.append((patient_id, page, per_page))
        if self.error is not None:
            raise self.error
        return self.list_view

    async def append_health_background_metric(
        self,
        patient_id: int,
        metric: HealthBackgroundMetric,
    ) -> HealthBackgroundMetricEntry:
        self.appends.append((patient_id, metric))
        if self.error is not None:
            raise self.error
        assert self.entry is not None
        return self.entry


def _token(*, subject_id: int = 7, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubHealthFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.health_facade = facade if facade is not None else StubHealthFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_empty_list_answers_a_paged_empty_view() -> None:
    facade = StubHealthFacade()
    facade.list_view = _EMPTY_LIST
    client = _client(facade)

    response = client.get("/v1/me/health-background/metrics", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _EMPTY_LIST.model_dump(mode="json")
    assert facade.metric_lists == [(7, 1, 25)]


def test_list_passes_pagination_query_params_through() -> None:
    facade = StubHealthFacade()
    facade.list_view = HealthBackgroundMetricList(items=[_ENTRY], total=5)
    client = _client(facade)

    response = client.get(
        "/v1/me/health-background/metrics?page=2&per_page=2",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == {"items": [_ENTRY.model_dump(mode="json")], "total": 5}
    assert facade.metric_lists == [(7, 2, 2)]


def test_list_per_page_above_the_cap_is_rejected() -> None:
    facade = StubHealthFacade()
    client = _client(facade)

    response = client.get(
        "/v1/me/health-background/metrics?per_page=101",
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.metric_lists == []


def test_append_returns_the_new_entry() -> None:
    facade = StubHealthFacade()
    facade.entry = _ENTRY
    client = _client(facade)

    response = client.post(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token()),
        json=_METRIC_BODY,
    )

    assert response.status_code == 201
    assert response.json() == _ENTRY.model_dump(mode="json")
    # The subject comes from the token claim, never client input.
    assert facade.appends == [(7, _METRIC)]


def test_replayed_idempotency_key_does_not_re_append() -> None:
    facade = StubHealthFacade()
    facade.entry = _ENTRY
    client = _client(facade)
    headers = {**_bearer(_token()), "Idempotency-Key": "metric-append-1"}

    first = client.post("/v1/me/health-background/metrics", headers=headers, json=_METRIC_BODY)
    second = client.post("/v1/me/health-background/metrics", headers=headers, json=_METRIC_BODY)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    assert facade.appends == [(7, _METRIC)]


def test_append_missing_timestamp_is_rejected() -> None:
    client = _client()

    body = {"height_cm": 172.0, "weight_kg": 68.5}
    response = client.post(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token()),
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_append_out_of_range_values_are_rejected() -> None:
    client = _client()

    for body in (
        {"height_cm": 300.0, "weight_kg": 68.5, "recorded_at": _NOW.isoformat()},
        {"height_cm": 172.0, "weight_kg": 0.5, "recorded_at": _NOW.isoformat()},
    ):
        response = client.post(
            "/v1/me/health-background/metrics",
            headers=_bearer(_token()),
            json=body,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"


def test_append_without_any_measurement_is_rejected() -> None:
    client = _client()

    response = client.post(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token()),
        json={"recorded_at": _NOW.isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_append_client_supplied_id_is_rejected() -> None:
    client = _client()

    body = {**_METRIC_BODY, "id": 999, "entry_id": 999}
    response = client.post(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token()),
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_owner_scoping_resolves_from_the_token_subject() -> None:
    facade = StubHealthFacade()
    facade.entry = _ENTRY
    client = _client(facade)

    get_a = client.get("/v1/me/health-background/metrics", headers=_bearer(_token(subject_id=7)))
    get_b = client.get("/v1/me/health-background/metrics", headers=_bearer(_token(subject_id=9)))
    post_b = client.post(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token(subject_id=9)),
        json=_METRIC_BODY,
    )

    assert get_a.status_code == 200 and get_b.status_code == 200 and post_b.status_code == 201
    # No patient id is ever client input: the facade is addressed by the token
    # subject alone, so a patient can only ever reach their own series.
    assert facade.metric_lists == [(7, 1, 25), (9, 1, 25)]
    assert facade.appends == [(9, _METRIC)]


def test_doctor_scope_never_reaches_the_metrics_surface() -> None:
    facade = StubHealthFacade()
    facade.entry = _ENTRY
    client = _client(facade)

    get_response = client.get(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token(scope="doctor")),
    )
    post_response = client.post(
        "/v1/me/health-background/metrics",
        headers=_bearer(_token(scope="doctor")),
        json=_METRIC_BODY,
    )

    assert get_response.status_code == 403
    assert get_response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert post_response.status_code == 403
    assert post_response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    # The facade was never consulted: the series is never served to a doctor
    # through this surface.
    assert facade.metric_lists == []
    assert facade.appends == []


def test_anonymous_access_denied_with_401_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    client = _client()

    response = client.get(
        "/v1/me/health-background/metrics",
        headers={"X-Request-Id": _TRACE_ID},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


def test_metrics_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    paths = app.openapi()["paths"]
    assert "/v1/me/health-background/metrics" in paths
