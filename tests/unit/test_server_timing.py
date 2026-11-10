"""LAT-HARNESS (#901): the opt-in server-processing timing header.

Pins the backend half of the latency probe's attribution contract: with the
gate on, every answered response - a 200, a gateway 401, a router 404 -
carries ``Server-Timing: caresetu_tstmp;dur=<ms>`` with a positive duration;
with the gate off (the production default) no header exists at all, because
the middleware is not installed. The probe's
``parse_server_timing_ms`` reads exactly this value (see
``test_measure_backend_latency.py`` for the parse half).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.server_timing import SERVER_TIMING_TAG
from app.main import create_app


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings=settings))


def _enabled_settings(**overrides: object) -> Settings:
    """An app-setting bundle with the timing header forced on."""
    values: dict[str, object] = {"app_environment": "test", "server_timing_header_enabled": True}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_health_response_carries_the_tagged_timing_header() -> None:
    response = _client(_enabled_settings()).get("/health")

    assert response.status_code == 200
    header = response.headers.get("server-timing")
    assert header is not None and header.startswith(f"{SERVER_TIMING_TAG};dur=")
    assert float(header.split("dur=")[1]) > 0.0


def test_gateway_401_rejection_carries_the_timing_header() -> None:
    """The middleware sits outermost, so a jwt_verify rejection is timed too."""
    response = _client(
        _enabled_settings(
            gateway_jwt_verify_enabled=True, gateway_jwt_signing_key="test-signing-key"
        )
    ).get("/v1/me")

    assert response.status_code == 401
    assert response.headers.get("server-timing", "").startswith(f"{SERVER_TIMING_TAG};dur=")


def test_router_404_carries_the_timing_header() -> None:
    response = _client(_enabled_settings()).get("/no-such-route")

    assert response.status_code == 404
    assert response.headers.get("server-timing", "").startswith(f"{SERVER_TIMING_TAG};dur=")


def test_gate_off_installs_no_middleware() -> None:
    """Production default: the header is absent - not merely empty."""
    response = _client(Settings(app_environment="production")).get("/health")

    assert response.status_code == 200
    assert "server-timing" not in response.headers


def test_dev_test_default_is_on_via_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from_settings`` resolves the env-dependent default: dev/test on."""
    from app.config import get_settings

    monkeypatch.setenv("APP_ENVIRONMENT", "dev")
    monkeypatch.delenv("SERVER_TIMING_HEADER_ENABLED", raising=False)
    assert get_settings().server_timing_header_enabled is True


def test_production_default_is_off_via_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production keeps the header off unless the deployment opts in."""
    from app.config import get_settings

    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.delenv("SERVER_TIMING_HEADER_ENABLED", raising=False)
    assert get_settings().server_timing_header_enabled is False


def test_explicit_env_flag_overrides_the_environment_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("SERVER_TIMING_HEADER_ENABLED", "1")
    assert get_settings().server_timing_header_enabled is True
