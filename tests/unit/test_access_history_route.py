"""PHASE-4 T7: the patient access-history REST surface (ticket #241, FEAT-003).

The route is a thin adapter: resolve the gateway ``Principal`` (via
``require_patient``), enforce the own-record-only rule (the ``patient_id``
query param must equal the session subject), call the audit facade, answer the
typed ``AccessHistoryView``. The facade is stubbed here; real ledger SQL
belongs to the facade test (``test_access_history_facade``) and the
integration suite. Patient-scoped JWTs minted by the iam module drive the
gateway's admit/deny exactly like the ``/v1/records`` tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.health.facade import AccessHistoryEntry, AccessHistoryView
from modules.iam.domain.jwt import issue_token

_SIGNING_KEY = "unit-test-access-history-signing-key"

_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)

_VIEW = AccessHistoryView(
    entries=[
        AccessHistoryEntry(
            actor_id=3,
            actor_type="doctor",
            scope="consultations",
            accessed_at=_NOW,
            denied=False,
            denial_reason=None,
        ),
        AccessHistoryEntry(
            actor_id=7,
            actor_type="patient",
            scope="full_record",
            accessed_at=_NOW,
            denied=False,
            denial_reason=None,
        ),
    ]
)


class StubAuditFacade:
    """Minimal facade stand-in recording calls and replaying a canned view."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.view: AccessHistoryView = _VIEW

    async def get_access_history(self, patient_id: int) -> AccessHistoryView:
        self.calls.append(patient_id)
        return self.view


def _token(*, subject_id: int = 7, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
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


def _history_path(patient_id: int) -> str:
    return f"/v1/audit/access-history?patient_id={patient_id}"


def test_patient_querying_their_own_record_succeeds() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    response = client.get(_history_path(7), headers=_bearer(_token(subject_id=7)))

    assert response.status_code == 200
    assert response.json() == _VIEW.model_dump(mode="json")
    # The subject comes from the token; the patient_id param must match it.
    assert facade.calls == [7]


def test_empty_history_returns_an_empty_list_not_an_error() -> None:
    facade = StubAuditFacade()
    facade.view = AccessHistoryView(entries=[])
    client = _client(facade)

    response = client.get(_history_path(7), headers=_bearer(_token(subject_id=7)))

    assert response.status_code == 200
    assert response.json() == {"entries": []}


def test_cross_patient_query_is_rejected_with_403() -> None:
    facade = StubAuditFacade()
    client = _client(facade)

    response = client.get(_history_path(7), headers=_bearer(_token(subject_id=1)))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    # The facade is never reached: rejection happens at the route boundary.
    assert facade.calls == []


def test_missing_patient_id_is_rejected_at_validation() -> None:
    client = _client()

    response = client.get("/v1/audit/access-history", headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_anonymous_read_denied_with_401() -> None:
    client = _client()

    response = client.get(_history_path(7))

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_non_patient_scope_denied_with_403() -> None:
    client = _client()

    response = client.get(_history_path(7), headers=_bearer(_token(scope="operator")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_partner_scope_denied_with_403() -> None:
    client = _client()

    response = client.get(_history_path(7), headers=_bearer(_token(scope="partner")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_access_history_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    assert "/v1/audit/access-history" in app.openapi()["paths"]
