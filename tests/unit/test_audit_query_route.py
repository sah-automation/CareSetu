"""PHASE-4 T6: the operator audit query REST surface (ticket #240).

The route is a thin adapter: resolve the gateway ``Principal`` (via
``require_operator``), call the audit facade with the query params, answer
the typed ``AuditPage``. The facade is stubbed here; real DB pagination and
filter SQL belong to the facade test (``test_audit_query_facade``) and the
integration suite. Operator-scoped JWTs minted by the iam module drive the
gateway's admit/deny exactly like the ``/v1/me`` / record tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.audit.facade import AuditEventView, AuditPage
from modules.iam.domain.jwt import issue_token

_SIGNING_KEY = "unit-test-audit-signing-key"

_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)

_ACTOR = uuid4()
_TARGET = uuid4()

_EMPTY_KWARGS = {
    "actor_id": None,
    "event_type": None,
    "target_id": None,
    "scope": None,
    "from_ts": None,
    "to_ts": None,
    "page": 1,
    "page_size": 20,
}


_PAGE = AuditPage(
    events=[
        AuditEventView(
            id=uuid4(),
            event_type="consent.granted",
            actor_id=_ACTOR,
            target_id=_TARGET,
            scope="consultations",
            metadata={"producer": "consent"},
            timestamp=_NOW,
            prev_hash="0" * 64,
            hash="1" * 64,
        )
    ],
    total_count=42,
)


class StubAuditFacade:
    """Minimal facade stand-in recording calls and replaying a canned page."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.page: AuditPage = _PAGE

    async def query_audit(self, **kwargs: object) -> AuditPage:
        self.calls.append(kwargs)
        return self.page


def _token(*, scope: str = "operator") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=1,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubAuditFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.audit_facade = facade if facade is not None else StubAuditFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_operator_query_returns_typed_page() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    response = client.get("/v1/audit/events", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _PAGE.model_dump(mode="json")
    assert facade.calls == [_EMPTY_KWARGS]


def test_missing_filters_call_unfiltered_query() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    client.get("/v1/audit/events", headers=_bearer(_token()))

    # No filter param -> every filter is None (unfiltered SELECT).
    call = facade.calls[0]
    assert call["actor_id"] is None
    assert call["event_type"] is None
    assert call["target_id"] is None
    assert call["scope"] is None
    assert call["from_ts"] is None
    assert call["to_ts"] is None


def test_filters_are_passed_through_to_the_facade() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    from_ts = "2026-08-01T00:00:00Z"
    to_ts = "2026-08-31T23:59:59Z"
    response = client.get(
        "/v1/audit/events",
        params={
            "actor_id": str(_ACTOR),
            "event_type": "consent.granted",
            "target_id": str(_TARGET),
            "scope": "consultations",
            "from_ts": from_ts,
            "to_ts": to_ts,
        },
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    call = facade.calls[0]
    assert call["actor_id"] == _ACTOR
    assert call["event_type"] == "consent.granted"
    assert call["target_id"] == _TARGET
    assert call["scope"] == "consultations"
    assert call["from_ts"] == datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    assert call["to_ts"] == datetime.fromisoformat(to_ts.replace("Z", "+00:00"))


def test_pagination_params_reach_the_facade() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    response = client.get(
        "/v1/audit/events",
        params={"page": 2, "page_size": 10},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.calls[0]["page"] == 2
    assert facade.calls[0]["page_size"] == 10


def test_default_page_size_is_20() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    client.get("/v1/audit/events", headers=_bearer(_token()))

    assert facade.calls[0]["page_size"] == 20
    assert facade.calls[0]["page"] == 1


def test_page_size_over_max_is_rejected() -> None:
    client = _client()

    response = client.get(
        "/v1/audit/events",
        params={"page_size": 101},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_anonymous_operator_query_denied_with_401() -> None:
    client = _client()

    response = client.get("/v1/audit/events")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_non_operator_scope_denied_with_403() -> None:
    client = _client()

    response = client.get("/v1/audit/events", headers=_bearer(_token(scope="patient")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_partner_scope_denied_with_403() -> None:
    client = _client()

    response = client.get("/v1/audit/events", headers=_bearer(_token(scope="partner")))

    assert response.status_code == 403


def test_audit_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert "/v1/audit/events" in app.openapi()["paths"]
