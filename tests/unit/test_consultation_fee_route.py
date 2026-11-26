"""PHASE-8.1 T06 (#444): PATCH /v1/partner/consultation-fee HTTP adapter.

The route is a thin partner-scoped adapter: resolve the gateway ``Principal``
(via ``require_partner``), call the partner facade, answer the typed
``PartnerView``. The facade is stubbed here; the DB-backed write belongs to the
integration suite. Acceptance criteria pinned here:

- A doctor partner can set (and clear) their own consultation fee.
- The route is gated by ``require_partner`` - anon/patient/operator is denied
  (401/403).
- Only a doctor partner may set a fee: a non-doctor partner answers the shared
  error envelope with 403 ``CONSULTATION_FEE_NOT_ALLOWED``.
- Validation: the fee is required (nullable null clears), non-negative, and the
  body is strict (unknown fields rejected).
- Idempotent (api-standards 5): a duplicate ``Idempotency-Key`` replays the
  stored result without re-executing the facade call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.exceptions import (
    ConsultationFeeNotAllowedError,
    PartnerNotActiveError,
    PartnerSuspendedError,
)
from modules.partner.facade import PartnerView

_SIGNING_KEY = "unit-test-partner-fee-key"
_PARTNER_ID = 42

_DOCTOR_VIEW = PartnerView(partner_id=_PARTNER_ID, partner_type="doctor", status="Active", round=1)


class StubFeeFacade:
    """Minimal facade stand-in recording the call and replaying a canned answer."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.partner_view: PartnerView = _DOCTOR_VIEW
        self.reject = False

    async def update_consultation_fee(
        self,
        identity_id: int,
        *,
        fee_paise: int | None,
    ) -> PartnerView:
        self.calls.append({"identity_id": identity_id, "fee_paise": fee_paise})
        if self.reject:
            raise ConsultationFeeNotAllowedError()
        return self.partner_view


def _token(*, scope: str = "partner", subject_id: int = 7) -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _client(facade: StubFeeFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.partner_facade = facade if facade is not None else StubFeeFacade()
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -- Happy paths ---------------------------------------------------------------


def test_doctor_sets_own_consultation_fee() -> None:
    facade = StubFeeFacade()
    client = _client(facade)

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": 50000},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == _DOCTOR_VIEW.model_dump(mode="json")
    assert facade.calls == [{"identity_id": 7, "fee_paise": 50000}]


def test_doctor_clears_own_consultation_fee() -> None:
    facade = StubFeeFacade()
    client = _client(facade)

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": None},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.calls == [{"identity_id": 7, "fee_paise": None}]


def test_fee_update_uses_caller_identity_only() -> None:
    facade = StubFeeFacade()
    client = _client(facade)

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": 30000},
        headers=_bearer(_token(subject_id=99)),
    )

    assert response.status_code == 200
    # Partner-scoped: the fee lands on the caller's own profile, never a path id.
    assert facade.calls == [{"identity_id": 99, "fee_paise": 30000}]


def test_fee_update_forwards_zero_and_large_paise() -> None:
    facade = StubFeeFacade()
    client = _client(facade)

    for value in (0, 100000):
        response = client.patch(
            "/v1/partner/consultation-fee",
            json={"fee_paise": value},
            headers=_bearer(_token()),
        )
        assert response.status_code == 200
    assert facade.calls == [
        {"identity_id": 7, "fee_paise": 0},
        {"identity_id": 7, "fee_paise": 100000},
    ]


# -- Doctor-only rule ----------------------------------------------------------


def test_non_doctor_partner_rejected_with_403_code() -> None:
    """A lab/chemist partner (partner scope but not a doctor) is refused."""
    facade = StubFeeFacade()
    facade.reject = True
    client = _client(facade)

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": 50000},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "CONSULTATION_FEE_NOT_ALLOWED"
    assert "doctor partner" in body["message"]
    assert "trace_id" in body
    assert facade.calls == [{"identity_id": 7, "fee_paise": 50000}]


# -- Active-state rule (F014-T06 #466) -----------------------------------------


def test_not_active_partner_refused_with_403_code() -> None:
    """A doctor whose profile is not ``[Active]`` cannot set a fee.

    The fee route is gated to the active state; a not-yet-activated (or
    deactivated) doctor maps to the ``PARTNER_NOT_ACTIVE`` 403 envelope.
    """
    facade = StubFeeFacade()

    async def raise_not_active(
        identity_id: int,
        *,
        fee_paise: int | None,
    ) -> PartnerView:
        facade.calls.append({"identity_id": identity_id, "fee_paise": fee_paise})
        raise PartnerNotActiveError(_PARTNER_ID, "Under Verification")

    facade.update_consultation_fee = raise_not_active  # type: ignore[method-assign]
    client = _client(facade)

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": 50000},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "PARTNER_NOT_ACTIVE"
    assert body["details"]["current_status"] == "Under Verification"
    assert "trace_id" in body


def test_suspended_partner_refused_with_403_code() -> None:
    """A suspended identity is refused before the fee logic runs (F014-T06 #466)."""
    facade = StubFeeFacade()

    async def raise_suspended(
        identity_id: int,
        *,
        fee_paise: int | None,
    ) -> PartnerView:
        facade.calls.append({"identity_id": identity_id, "fee_paise": fee_paise})
        raise PartnerSuspendedError(identity_id)

    facade.update_consultation_fee = raise_suspended  # type: ignore[method-assign]
    client = _client(facade)

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": 50000},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PARTNER_SUSPENDED"


# -- RBAC guard ----------------------------------------------------------------


def test_fee_route_requires_partner_scope() -> None:
    client = _client()

    # Anonymous: 401.
    assert (
        client.patch("/v1/partner/consultation-fee", json={"fee_paise": 50000}).status_code == 401
    )

    # Operator scope: 403 (not a partner principal).
    op_headers = _bearer(_token(scope="operator"))
    assert (
        client.patch(
            "/v1/partner/consultation-fee",
            json={"fee_paise": 50000},
            headers=op_headers,
        ).status_code
        == 403
    )

    # Patient scope: 403.
    pt_headers = _bearer(_token(scope="patient"))
    assert (
        client.patch(
            "/v1/partner/consultation-fee",
            json={"fee_paise": 50000},
            headers=pt_headers,
        ).status_code
        == 403
    )


# -- Validation ----------------------------------------------------------------


def test_fee_missing_body_field_answers_422() -> None:
    """The fee is REQUIRED in the body - an empty object is a 422, not a clear."""
    client = _client()

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_fee_negative_value_answers_422() -> None:
    client = _client()

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": -1},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


def test_fee_unknown_extra_field_answers_422() -> None:
    """Strict body (api-standards §3): unknown fields are rejected."""
    client = _client()

    response = client.patch(
        "/v1/partner/consultation-fee",
        json={"fee_paise": 50000, "partner_id": 1},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422


# -- Idempotency ---------------------------------------------------------------


def test_fee_update_replays_under_duplicate_key() -> None:
    """A replayed ``Idempotency-Key`` returns the stored result, no re-execute."""
    facade = StubFeeFacade()
    client = _client(facade)
    headers = {**_bearer(_token()), "Idempotency-Key": "fee-set-1"}

    first = client.patch("/v1/partner/consultation-fee", json={"fee_paise": 50000}, headers=headers)
    second = client.patch(
        "/v1/partner/consultation-fee", json={"fee_paise": 50000}, headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert facade.calls == [{"identity_id": 7, "fee_paise": 50000}]


# -- Surface -------------------------------------------------------------------


def test_fee_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/v1/partner/consultation-fee" in paths
