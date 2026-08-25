"""PHASE-3 T3: the consent REST surface behind the gateway (ticket #212, FEAT-002).

The routes are thin adapters: resolve the gateway ``Principal``, call the
consent facade, answer the typed view. Every expected failure answers the
shared error envelope (api-standards §2) - not-found, non-owner, illegal
transition, and the sanitized internal error. The facade is stubbed here,
and real patient-scoped access JWTs minted by the iam module drive the
gateway's admit/deny exactly like the record-surface tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.main import create_app
from modules.consent.domain.exceptions import (
    ConsentAccessDeniedError,
    ConsentError,
    ConsentNotFoundError,
    IllegalConsentTransitionError,
)
from modules.consent.facade import ConsentEventView, ConsentLog, ConsentView
from modules.iam.domain.jwt import issue_token

_SIGNING_KEY = "unit-test-consent-signing-key"

_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


def _view(consent_id: int = 9, **overrides: object) -> ConsentView:
    fields: dict[str, object] = {
        "consent_id": consent_id,
        "lineage_ref": "C-2026-004",
        "patient_id": 7,
        "counterparty_type": "doctor",
        "counterparty_id": "dr-77",
        "record_scope": "consultations",
        "status": "granted",
        "version": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
        "events": [
            ConsentEventView(kind="granted", version=1, actor_patient_id=7, occurred_at=_NOW)
        ],
    }
    fields.update(overrides)
    return ConsentView(**fields)  # type: ignore[arg-type]


class StubConsentFacade:
    """Minimal facade stand-in recording calls and replaying canned answers."""

    def __init__(self) -> None:
        self.grants: list[tuple[int, str, str, str]] = []
        self.requests: list[tuple[int, str, str, str]] = []
        self.addressed: list[tuple[str, int, int]] = []
        self.listed: list[int] = []
        self.view: ConsentView = _view()
        self.log: ConsentLog = ConsentLog(items=[_view()])
        self.error: Exception | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def grant_consent(
        self, patient_id: int, counterparty_type: str, counterparty_id: str, record_scope: str
    ) -> ConsentView:
        self.grants.append((patient_id, counterparty_type, counterparty_id, record_scope))
        self._maybe_raise()
        return self.view

    async def request_consent(
        self, patient_id: int, counterparty_type: str, counterparty_id: str, record_scope: str
    ) -> ConsentView:
        self.requests.append((patient_id, counterparty_type, counterparty_id, record_scope))
        self._maybe_raise()
        return _view(status="requested", version=0)

    async def list_consents(self, patient_id: int) -> ConsentLog:
        self.listed.append(patient_id)
        self._maybe_raise()
        return self.log

    async def grant_requested(self, patient_id: int, consent_id: int) -> ConsentView:
        self.addressed.append(("grant", patient_id, consent_id))
        self._maybe_raise()
        return self.view

    async def revoke_consent(self, patient_id: int, consent_id: int) -> ConsentView:
        self.addressed.append(("revoke", patient_id, consent_id))
        self._maybe_raise()
        return _view(status="revoked", version=1)

    async def decline_consent(self, patient_id: int, consent_id: int) -> ConsentView:
        self.addressed.append(("decline", patient_id, consent_id))
        self._maybe_raise()
        return _view(status="declined", version=0)


def _token(*, subject_id: int = 7, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubConsentFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.consent_facade = facade if facade is not None else StubConsentFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_TRIPLE_BODY = {
    "counterparty_type": "doctor",
    "counterparty_id": "dr-77",
    "record_scope": "consultations",
}


def test_grant_answers_201_with_the_typed_view() -> None:
    facade = StubConsentFacade()
    client = _client(facade)

    response = client.post("/v1/consents", json=_TRIPLE_BODY, headers=_bearer(_token()))

    assert response.status_code == 201
    assert response.json() == facade.view.model_dump(mode="json")
    # The subject comes from the token claim, never client input.
    assert facade.grants == [(7, "doctor", "dr-77", "consultations")]


def test_request_answers_201_in_the_requested_state() -> None:
    facade = StubConsentFacade()
    client = _client(facade)

    body = client.post("/v1/consents/requests", json=_TRIPLE_BODY, headers=_bearer(_token())).json()

    assert body["status"] == "requested"
    assert body["version"] == 0


def test_list_answers_the_log_envelope() -> None:
    facade = StubConsentFacade()
    client = _client(facade)

    response = client.get("/v1/consents", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.log.model_dump(mode="json")
    assert facade.listed == [7]


@pytest.mark.parametrize(
    ("action", "path"),
    [
        ("grant", "/v1/consents/9/grant"),
        ("revoke", "/v1/consents/9/revoke"),
        ("decline", "/v1/consents/9/decline"),
    ],
)
def test_addressed_actions_reach_the_facade_with_subject_and_id(action: str, path: str) -> None:
    facade = StubConsentFacade()
    client = _client(facade)

    response = client.post(path, headers=_bearer(_token()))

    assert response.status_code == 200
    assert facade.addressed == [(action, 7, 9)]


def test_anonymous_grant_denied_with_401_envelope() -> None:
    client = _client()

    response = client.post("/v1/consents", json=_TRIPLE_BODY)

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_non_patient_scope_denied_with_403_envelope() -> None:
    client = _client()

    response = client.get("/v1/consents", headers=_bearer(_token(scope="operator")))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"


def test_unknown_consent_answers_404_envelope() -> None:
    facade = StubConsentFacade()
    facade.error = ConsentNotFoundError(424242)
    client = _client(facade)

    response = client.post("/v1/consents/424242/revoke", headers=_bearer(_token()))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "CONSENT_NOT_FOUND"
    assert body["trace_id"]
    assert body["details"] == {}


def test_non_owner_action_answers_403_consent_envelope() -> None:
    facade = StubConsentFacade()
    facade.error = ConsentAccessDeniedError("only the owning patient may act on this consent")
    client = _client(facade)

    response = client.post("/v1/consents/9/revoke", headers=_bearer(_token(subject_id=8)))

    assert response.status_code == 403
    assert response.json()["code"] == "CONSENT_ACCESS_DENIED"


def test_illegal_transition_answers_409_envelope() -> None:
    facade = StubConsentFacade()
    facade.error = IllegalConsentTransitionError("revoke is illegal while the consent is revoked")
    client = _client(facade)

    response = client.post("/v1/consents/9/revoke", headers=_bearer(_token()))

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONSENT_INVALID_TRANSITION"
    assert "revoked" in body["message"]


def test_unexpected_consent_error_answers_sanitized_500_envelope() -> None:
    facade = StubConsentFacade()
    facade.error = ConsentError("database exploded")
    client = _client(facade)

    response = client.post("/v1/consents", json=_TRIPLE_BODY, headers=_bearer(_token()))

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "CONSENT_INTERNAL"
    assert body["message"] == "Internal consent error"
    assert "exploded" not in body["message"]


def test_out_of_enum_scope_rejected_at_validation() -> None:
    client = _client()
    body = {**_TRIPLE_BODY, "record_scope": "everything"}

    response = client.post("/v1/consents", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_extra_body_fields_rejected_strictly() -> None:
    client = _client()
    body = {**_TRIPLE_BODY, "ttl_days": 30}

    response = client.post("/v1/consents", json=body, headers=_bearer(_token()))

    # No TTL exists in Phase 3 - "how long" renders as "Until you revoke".
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_consent_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    paths = app.openapi()["paths"]
    for path in (
        "/v1/consents",
        "/v1/consents/requests",
        "/v1/consents/{consent_id}/grant",
        "/v1/consents/{consent_id}/revoke",
        "/v1/consents/{consent_id}/decline",
    ):
        assert path in paths
