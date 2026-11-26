"""PHASE-3 T2: the record REST surface behind the gateway (ticket #211).

The routes are thin adapters: resolve the gateway ``Principal``, call the
health facade, answer the typed timeline. Every expected failure answers the
shared error envelope (api-standards §2) - including the non-owner read,
which the facade refuses (and records server-side; the DB-backed denial row
is the integration suite's job). The facade is stubbed here, and real
patient-scoped access JWTs minted by the iam module drive the gateway's
admit/deny exactly like the ``/v1/me`` tests.
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
from modules.health.domain.exceptions import (
    HealthError,
    RecordAccessDeniedError,
    RecordNotFoundError,
)
from modules.health.facade import RecordEntryView, RecordTimeline
from modules.iam.domain.jwt import issue_token

_SIGNING_KEY = "unit-test-record-signing-key"

_TRACE_ID = "unit-trace-1234abcd"

_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)

_EMPTY_TIMELINE = RecordTimeline(record_id=123, patient_id=7, created_at=_NOW, entries=[])

_ENTRY_TIMELINE = RecordTimeline(
    record_id=123,
    patient_id=7,
    created_at=_NOW,
    entries=[
        RecordEntryView(
            entry_id=2,
            entry_type="metric",
            payload={"kind": "bp"},
            occurred_at=_NOW,
            created_at=_NOW,
        ),
        RecordEntryView(
            entry_id=1,
            entry_type="lab_report",
            payload={},
            occurred_at=datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC),
            created_at=datetime(2026, 8, 1, 9, 5, 0, tzinfo=UTC),
        ),
    ],
)


class StubHealthFacade:
    """Minimal facade stand-in recording calls and replaying canned answers."""

    def __init__(self) -> None:
        self.own_reads: list[int] = []
        self.addressed_reads: list[tuple[int, int]] = []
        self.timeline: RecordTimeline = _EMPTY_TIMELINE
        self.error: Exception | None = None

    async def get_own_record(self, patient_id: int) -> RecordTimeline:
        self.own_reads.append(patient_id)
        if self.error is not None:
            raise self.error
        return self.timeline

    async def get_record_as_owner(self, patient_id: int, record_id: int) -> RecordTimeline:
        self.addressed_reads.append((patient_id, record_id))
        if self.error is not None:
            raise self.error
        return self.timeline


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


def test_own_record_returns_typed_empty_timeline() -> None:
    facade = StubHealthFacade()
    client = _client(facade)

    response = client.get("/v1/records", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _EMPTY_TIMELINE.model_dump(mode="json")
    # The subject comes from the token claim, never client input.
    assert facade.own_reads == [7]
    assert facade.addressed_reads == []


def test_addressed_owner_read_returns_timeline() -> None:
    facade = StubHealthFacade()
    client = _client(facade)

    response = client.get("/v1/records/123", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _EMPTY_TIMELINE.model_dump(mode="json")
    assert facade.addressed_reads == [(7, 123)]


def test_entries_answer_reverse_chronologically_as_documented() -> None:
    facade = StubHealthFacade()
    facade.timeline = _ENTRY_TIMELINE
    client = _client(facade)

    body = client.get("/v1/records", headers=_bearer(_token())).json()

    occurred = [entry["occurred_at"] for entry in body["entries"]]
    assert occurred == sorted(occurred, reverse=True)
    assert body["entries"][0]["entry_type"] == "metric"


def test_anonymous_read_denied_with_401_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    client = _client()

    response = client.get("/v1/records", headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


def test_non_patient_scope_denied_with_403_envelope() -> None:
    client = _client()

    response = client.get("/v1/records", headers=_bearer(_token(scope="operator")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_non_owner_read_answers_403_envelope() -> None:
    facade = StubHealthFacade()
    facade.error = RecordAccessDeniedError("only the record owner may read this record")
    client = _client(facade)

    response = client.get(
        "/v1/records/999",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "RECORD_ACCESS_DENIED"
    assert body["trace_id"]
    assert body["details"] == {}
    # The refusal reached the facade with the caller's own subject + the id.
    assert facade.addressed_reads == [(7, 999)]


def test_unknown_record_answers_404_envelope() -> None:
    facade = StubHealthFacade()
    facade.error = RecordNotFoundError("no record exists with id 424242")
    client = _client(facade)

    response = client.get("/v1/records/424242", headers=_bearer(_token()))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "RECORD_NOT_FOUND"
    assert body["trace_id"]
    assert body["details"] == {}


def test_unexpected_health_error_answers_sanitized_500_envelope() -> None:
    facade = StubHealthFacade()
    facade.error = HealthError("database exploded")
    client = _client(facade)

    response = client.get("/v1/records", headers=_bearer(_token()))

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "HEALTH_INTERNAL"
    assert body["message"] == "Internal health record error"
    assert "exploded" not in body["message"]


def test_non_integer_record_id_rejected_at_validation() -> None:
    client = _client()

    response = client.get("/v1/records/not-a-number", headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_record_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    paths = app.openapi()["paths"]
    assert "/v1/records" in paths
    assert "/v1/records/{record_id}" in paths
