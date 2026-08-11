"""PHASE-1 T7b: gateway middleware stubs (ticket #29).

Acceptance contract from the brief: ``jwt_verify`` attaches a typed ``Principal``
from a test header (accept-all), ``rate_limit`` exists disabled by default, both
are wired in front of routes, and disabled stubs pass through untouched.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import DEFAULT_TEST_PRINCIPAL_HEADER, Settings, get_settings
from app.gateway.principal import Principal
from app.main import create_app


def _probe_client(settings: Settings) -> TestClient:
    """A test-only app that reports the gateway's effect on request state.

    The probe route reflects what the middleware stack left on the request:
    the attached ``Principal`` (or its absence) and whether the rate-limit stub
    ran. This is how the stubs' behaviour is observed without business routes.
    """

    app = create_app(settings=settings)

    @app.get("/probe")
    def probe(request: Request) -> dict[str, object]:
        state = request.state
        principal: Principal | None = getattr(state, "principal", None)
        return {
            "principal_subject": principal.subject_id if principal else None,
            "principal_authenticated": principal.is_authenticated if principal else None,
            "rate_limit_checked": getattr(state, "gateway_rate_limit_checked", False),
        }

    return TestClient(app)


def test_jwt_verify_disabled_passes_through() -> None:
    client = _probe_client(Settings())

    response = client.get("/probe")

    assert response.status_code == 200
    body = response.json()
    assert body["principal_subject"] is None
    assert body["rate_limit_checked"] is False


def test_jwt_verify_disabled_ignores_test_header() -> None:
    client = _probe_client(Settings())

    response = client.get("/probe", headers={DEFAULT_TEST_PRINCIPAL_HEADER: "patient-123"})

    assert response.status_code == 200
    assert response.json()["principal_subject"] is None


def test_jwt_verify_attaches_typed_principal_from_test_header() -> None:
    settings = Settings(gateway_jwt_verify_enabled=True)
    client = _probe_client(settings)

    response = client.get("/probe", headers={DEFAULT_TEST_PRINCIPAL_HEADER: "patient-123"})

    assert response.status_code == 200
    body = response.json()
    assert body["principal_subject"] == "patient-123"
    assert body["principal_authenticated"] is True


def test_jwt_verify_missing_header_attaches_anonymous_principal() -> None:
    settings = Settings(gateway_jwt_verify_enabled=True)
    client = _probe_client(settings)

    response = client.get("/probe")

    assert response.status_code == 200
    body = response.json()
    assert body["principal_subject"] == "anonymous"
    assert body["principal_authenticated"] is False


def test_rate_limit_disabled_passes_through() -> None:
    client = _probe_client(Settings())

    response = client.get("/probe")

    assert response.status_code == 200
    assert response.json()["rate_limit_checked"] is False


def test_rate_limit_stub_runs_when_enabled() -> None:
    settings = Settings(gateway_rate_limit_enabled=True)
    client = _probe_client(settings)

    response = client.get("/probe")

    assert response.status_code == 200
    assert response.json()["rate_limit_checked"] is True


def test_settings_default_to_stubs_disabled() -> None:
    settings = Settings()

    assert settings.gateway_jwt_verify_enabled is False
    assert settings.gateway_rate_limit_enabled is False
    assert settings.gateway_jwt_test_header == DEFAULT_TEST_PRINCIPAL_HEADER


def test_settings_read_gateway_flags_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_JWT_VERIFY_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("GATEWAY_JWT_TEST_HEADER", "X-Probe-Header")

    settings = get_settings()

    assert settings.gateway_jwt_verify_enabled is True
    assert settings.gateway_rate_limit_enabled is True
    assert settings.gateway_jwt_test_header == "X-Probe-Header"


def test_principal_is_a_typed_model() -> None:
    principal = Principal.for_subject("patient-123", "patient")

    assert isinstance(principal, Principal)
    assert principal.subject_id == "patient-123"
    assert principal.roles == ("patient",)
    assert principal.is_authenticated is True


def test_anonymous_principal_is_unauthenticated() -> None:
    principal = Principal.anonymous()

    assert principal.subject_id == "anonymous"
    assert principal.roles == ()
    assert principal.is_authenticated is False
