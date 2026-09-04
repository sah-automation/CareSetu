"""PHASE-5 T06: POST /v1/partner/credentials HTTP adapter (ticket #251).

The route is a thin adapter: parse the typed request, call the partner facade,
answer the typed credential submission result. The facade is stubbed here; the
DB-backed credential submission behavior is the integration suite's job. Every
expected failure answers the shared error envelope (api-standards 2). The route
sits behind the ``require_partner`` gate (partner-scoped JWT required).

Idempotency (api-standards 5): a duplicate ``Idempotency-Key`` replays the
stored result without re-executing the facade call, so a client retry after a
lost response cannot double-submit credentials.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.credentials import CredentialType
from modules.partner.facade import (
    CredentialSubmission,
    CredentialSubmissionResult,
    PartnerView,
)

_SIGNING_KEY = "unit-test-partner-credentials-key"
_PARTNER_ID = 42

_SUBMISSION_RESULT = CredentialSubmissionResult(
    partner_id=_PARTNER_ID,
    status="Under Verification",
    round=1,
    auto_fail_reason=None,
)

_RESOLVED_PARTNER = PartnerView(partner_id=_PARTNER_ID, status="Registered", round=0)


class StubPartnerFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.submission_result: CredentialSubmissionResult = _SUBMISSION_RESULT

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        self.calls.append({"method": "resolve_partner", "identity_id": identity_id})
        return _RESOLVED_PARTNER

    async def submit_credentials(
        self,
        partner_id: int,
        *,
        credentials: list[CredentialSubmission],
    ) -> CredentialSubmissionResult:
        self.calls.append(
            {
                "method": "submit_credentials",
                "partner_id": partner_id,
                "credentials": credentials,
            }
        )
        return self.submission_result


def _token(*, scope: str = "partner", subject_id: int = 7) -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubPartnerFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.partner_facade = facade if facade is not None else StubPartnerFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_BODY = {
    "credentials": [
        {
            "credential_type": "medical_registration",
            "artifacts": ["dGVzdC1kb2N1bWVudA=="],
        }
    ],
}


# -- Happy path ----------------------------------------------------------------


def test_submit_credentials_forwards_to_facade() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.post(
        "/v1/partner/credentials",
        json=_BODY,
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _SUBMISSION_RESULT.model_dump(mode="json")
    assert facade.calls == [
        {"method": "resolve_partner", "identity_id": 7},
        {
            "method": "submit_credentials",
            "partner_id": _PARTNER_ID,
            "credentials": [
                CredentialSubmission(
                    credential_type=CredentialType.MEDICAL_REGISTRATION,
                    artifacts=[b"test-document"],
                )
            ],
        },
    ]


# -- RBAC guard ----------------------------------------------------------------


def test_credentials_routes_require_partner_scope() -> None:
    client = _client()

    # Anonymous: 401.
    assert client.post("/v1/partner/credentials", json=_BODY).status_code == 401

    # Operator scope: 403.
    op_headers = _bearer(_token(scope="operator"))
    assert client.post("/v1/partner/credentials", json=_BODY, headers=op_headers).status_code == 403

    # Patient scope: 403.
    pt_headers = _bearer(_token(scope="patient"))
    assert client.post("/v1/partner/credentials", json=_BODY, headers=pt_headers).status_code == 403


def test_credentials_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/v1/partner/credentials" in paths


# -- Idempotency (api-standards 5) ----------------------------------------------


def test_credentials_idempotent_same_key_replays_result() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    key = "credentials-key-1"

    resp1 = client.post(
        "/v1/partner/credentials",
        json=_BODY,
        headers={**_bearer(_token()), "Idempotency-Key": key},
    )
    resp2 = client.post(
        "/v1/partner/credentials",
        json=_BODY,
        headers={**_bearer(_token()), "Idempotency-Key": key},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
    # resolve_partner + submit_credentials called once each
    assert len(facade.calls) == 2


def test_credentials_distinct_keys_both_apply() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    resp1 = client.post(
        "/v1/partner/credentials",
        json=_BODY,
        headers={**_bearer(_token()), "Idempotency-Key": "key-1"},
    )
    resp2 = client.post(
        "/v1/partner/credentials",
        json=_BODY,
        headers={**_bearer(_token()), "Idempotency-Key": "key-2"},
    )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # resolve_partner + submit_credentials called twice each
    assert len(facade.calls) == 4


def test_credentials_missing_key_still_allows_mutation() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    resp = client.post(
        "/v1/partner/credentials",
        json=_BODY,
        headers=_bearer(_token()),
    )

    assert resp.status_code == 200
    # resolve_partner + submit_credentials
    assert len(facade.calls) == 2
