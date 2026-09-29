"""Ticket #534: the patient health-background snapshot REST surface.

The routes are thin adapters: resolve the gateway ``Principal``, call the
health facade, answer the typed view. The snapshot is patient-owned surface -
the ``require_patient`` gate admits only an authenticated patient, so a
doctor-scoped token is refused before the facade is ever consulted (the
snapshot is never returned to a doctor via this surface - that is later,
consent-gated doctor work). The first save requires the acknowledgement flag;
the facade enforces it, and the route maps the refusal to the shared error
envelope. The facade is stubbed here; the ack / auto-grant / re-grant logic is
the DB-backed facade-suite's job.
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
from modules.health.domain.exceptions import HealthBackgroundAcknowledgmentRequiredError
from modules.health.facade import HealthBackground, HealthBackgroundView
from modules.iam.domain.jwt import issue_token

_SIGNING_KEY = "unit-test-background-signing-key"

_TRACE_ID = "unit-trace-1234abcd"

_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)

_BACKGROUND = HealthBackground(
    blood_group="B+",
    conditions=["diabetes"],
    allergies=["penicillin"],
    medications=["metformin"],
    immunizations=["COVID-19"],
    family_history=["mother: hypertension"],
)

_SET_VIEW = HealthBackgroundView(set=True, acknowledged=True, background=_BACKGROUND)

_NOT_SET_VIEW = HealthBackgroundView(set=False, acknowledged=False, background=None)

_SAVE_BODY = {
    "acknowledge_phi": True,
    "background": _BACKGROUND.model_dump(mode="json"),
}


class StubHealthFacade:
    """Minimal facade stand-in recording calls and replaying canned answers."""

    def __init__(self) -> None:
        self.background_reads: list[int] = []
        self.saves: list[tuple[int, HealthBackground, bool]] = []
        self.view: HealthBackgroundView = _NOT_SET_VIEW
        self.error: Exception | None = None

    async def get_health_background(self, patient_id: int) -> HealthBackgroundView:
        self.background_reads.append(patient_id)
        if self.error is not None:
            raise self.error
        return self.view

    async def save_health_background(
        self,
        patient_id: int,
        background: HealthBackground,
        *,
        acknowledge_phi: bool,
    ) -> HealthBackgroundView:
        self.saves.append((patient_id, background, acknowledge_phi))
        if self.error is not None:
            raise self.error
        return self.view


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


def test_not_set_read_answers_typed_empty_view() -> None:
    facade = StubHealthFacade()
    facade.view = _NOT_SET_VIEW
    client = _client(facade)

    response = client.get("/v1/me/health-background", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _NOT_SET_VIEW.model_dump(mode="json")
    # The subject comes from the token claim, never client input.
    assert facade.background_reads == [7]
    assert facade.saves == []


def test_set_read_answers_the_stored_snapshot() -> None:
    facade = StubHealthFacade()
    facade.view = _SET_VIEW
    client = _client(facade)

    response = client.get("/v1/me/health-background", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == _SET_VIEW.model_dump(mode="json")
    assert facade.background_reads == [7]


def test_acknowledged_first_save_returns_the_set_view() -> None:
    facade = StubHealthFacade()
    facade.view = _SET_VIEW
    client = _client(facade)

    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=_SAVE_BODY,
    )

    assert response.status_code == 200
    assert response.json() == _SET_VIEW.model_dump(mode="json")
    assert facade.saves == [(7, _BACKGROUND, True)]


def test_first_save_without_acknowledgement_is_rejected_with_an_envelope() -> None:
    facade = StubHealthFacade()
    facade.error = HealthBackgroundAcknowledgmentRequiredError(
        "the first health-background save must acknowledge"
    )
    client = _client(facade)

    body = {"acknowledge_phi": False, "background": _BACKGROUND.model_dump(mode="json")}
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=body,
    )

    assert response.status_code == 422
    envelope = response.json()
    assert envelope["code"] == "HEALTH_BACKGROUND_ACK_REQUIRED"
    assert envelope["trace_id"]
    assert facade.saves == [(7, _BACKGROUND, False)]


def test_later_edit_without_acknowledgement_is_accepted() -> None:
    facade = StubHealthFacade()
    facade.view = _SET_VIEW
    client = _client(facade)

    body = {
        "acknowledge_phi": False,
        "background": _BACKGROUND.model_dump(mode="json"),
    }
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=body,
    )

    assert response.status_code == 200
    # The route passes the flag through untouched; the facade decides that a
    # later edit does not need one (covered in the facade suite).
    assert facade.saves == [(7, _BACKGROUND, False)]


def test_later_edit_omitting_the_flag_reaches_the_facade() -> None:
    """#534 AC "later edits do not require it": omission is not a 422.

    The flag defaults to ``False``, so a second save that leaves it out passes
    validation and reaches the facade, which - the snapshot already existing -
    accepts it. The FIRST save without the flag is still refused (see
    ``test_first_save_without_acknowledgement_is_rejected_with_an_envelope``,
    where the facade raises).
    """
    facade = StubHealthFacade()
    facade.view = _SET_VIEW
    client = _client(facade)

    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json={"background": _BACKGROUND.model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert facade.saves == [(7, _BACKGROUND, False)]


def test_unknown_field_in_the_save_request_is_rejected() -> None:
    client = _client()

    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json={**_SAVE_BODY, "acknowledged": True},
    )

    # api-standards §3: unknown/extra fields are rejected, not silently ignored.
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_unknown_field_in_the_background_is_rejected() -> None:
    client = _client()

    body = {
        "acknowledge_phi": True,
        "background": {**_BACKGROUND.model_dump(mode="json"), "smoking": "yes"},
    }
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_overlong_list_area_rejected_at_validation() -> None:
    client = _client()

    body = {
        "acknowledge_phi": True,
        "background": {
            **_BACKGROUND.model_dump(mode="json"),
            "conditions": [f"condition {index}" for index in range(51)],
        },
    }
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=body,
    )

    # The JSONB column carries no column-level cap, so the item-count bound is
    # enforced only here - a PHI write must never be unbounded.
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_overlong_list_item_rejected_at_validation() -> None:
    client = _client()

    body = {
        "acknowledge_phi": True,
        "background": {
            **_BACKGROUND.model_dump(mode="json"),
            "allergies": ["a" * 201],
        },
    }
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_a_generously_sized_snapshot_is_accepted() -> None:
    """The bounds are ceilings, not a wall: real clinical history still fits."""
    facade = StubHealthFacade()
    facade.view = _SET_VIEW
    client = _client(facade)

    background = {
        **_BACKGROUND.model_dump(mode="json"),
        "immunizations": [f"vaccine-{index}" for index in range(50)],
        "conditions": ["x" * 200],
    }
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json={"acknowledge_phi": True, "background": background},
    )

    assert response.status_code == 200


def test_replayed_idempotency_key_does_not_re_save() -> None:
    facade = StubHealthFacade()
    facade.view = _SET_VIEW
    client = _client(facade)
    headers = {**_bearer(_token()), "Idempotency-Key": "background-save-1"}

    first = client.put("/v1/me/health-background", headers=headers, json=_SAVE_BODY)
    second = client.put("/v1/me/health-background", headers=headers, json=_SAVE_BODY)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert facade.saves == [(7, _BACKGROUND, True)]


def test_doctor_scope_never_reaches_the_snapshot_surface() -> None:
    facade = StubHealthFacade()
    client = _client(facade)

    get_response = client.get("/v1/me/health-background", headers=_bearer(_token(scope="doctor")))
    put_response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token(scope="doctor")),
        json=_SAVE_BODY,
    )

    assert get_response.status_code == 403
    assert get_response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert put_response.status_code == 403
    assert put_response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    # The facade was never consulted: the snapshot is never served to a doctor
    # through this surface.
    assert facade.background_reads == []
    assert facade.saves == []


def test_anonymous_access_denied_with_401_envelope(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    client = _client()

    response = client.get("/v1/me/health-background", headers={"X-Request-Id": _TRACE_ID})

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["trace_id"] == _TRACE_ID
    assert body["details"] == {}


def test_invalid_body_rejected_at_validation() -> None:
    client = _client()

    # ``background`` is the one required field; ``acknowledge_phi`` now defaults
    # to ``False`` (a later edit may omit it), so the missing snapshot is what
    # fails here.
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json={"acknowledge_phi": True},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_overlong_blood_group_rejected_at_validation() -> None:
    client = _client()

    body = {
        "acknowledge_phi": True,
        "background": {"blood_group": "B" * 17},
    }
    response = client.put(
        "/v1/me/health-background",
        headers=_bearer(_token()),
        json=body,
    )

    # The column is VARCHAR(16): the cap is enforced at the API boundary so a
    # client-input overrun never surfaces as an operational 5xx at the DB.
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_snapshot_routes_sit_behind_the_gateway_stack() -> None:
    app = create_app()

    middlewares = {middleware.cls for middleware in app.user_middleware}
    assert JWTVerifyMiddleware in middlewares
    paths = app.openapi()["paths"]
    assert "/v1/me/health-background" in paths
