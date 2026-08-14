"""PHASE-1 T7a: FastAPI app shell boots (ticket #28).

Boot contract from the brief: the app builds from the shared env-driven
``Settings`` and serves ``/health`` with 200. From PHASE-2 T3/T4/T5/T9 (#54,
#55, #56, #60) it mounts exactly the iam auth surface - the register, verify,
resend, and session endpoints - and no other business routes. From T10 (#61)
the app shell also exposes the dev/test-only mock-OTP read-back route the
Playwright E2E suite uses to drive register -> verify in the browser.
"""

import asyncio
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import DEFAULT_DATABASE_URL, Settings
from app.main import create_app
from modules.iam.adapters.sms import MockSmsAdapter, SmsSendRequest, SmsTemplateParams
from modules.iam.facade import IamFacade


def test_app_boots_from_default_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app()

    assert app.state.settings.database_url == DEFAULT_DATABASE_URL


def test_app_reads_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_url = "postgresql+asyncpg://env-db.internal:5432/envdb"
    monkeypatch.setenv("DATABASE_URL", custom_url)

    app = create_app()

    assert app.state.settings.database_url == custom_url


def test_app_accepts_explicit_settings() -> None:
    settings = Settings(database_url="postgresql+asyncpg://override-db.internal:5432/override")

    app = create_app(settings=settings)

    assert app.state.settings == settings


def test_health_returns_200() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_routes_are_the_only_business_routes() -> None:
    app = create_app()

    assert set(app.openapi()["paths"]) == {
        "/health",
        "/v1/auth/register",
        "/v1/auth/verify",
        "/v1/auth/resend",
        "/v1/auth/session",
        "/v1/auth/dev/otp",
        "/v1/me",
    }


def test_dev_otp_reads_back_the_mock_code_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    app = create_app()
    adapter = cast(MockSmsAdapter, app.state.mock_sms_adapter)
    asyncio.run(
        adapter.send(
            SmsSendRequest(
                phone_e164="+919000000000",
                params=SmsTemplateParams(otp="123456"),
            )
        )
    )

    response = TestClient(app).get("/v1/auth/dev/otp", params={"phone": "+919000000000"})

    assert response.status_code == 200
    assert response.json() == {"code": "123456"}


def test_dev_otp_returns_null_when_nothing_sent_for_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    app = create_app()

    response = TestClient(app).get("/v1/auth/dev/otp", params={"phone": "+919000000000"})

    assert response.status_code == 200
    assert response.json() == {"code": None}


def test_dev_otp_gated_outside_dev_test_environment() -> None:
    app = create_app()

    response = TestClient(app).get("/v1/auth/dev/otp", params={"phone": "+919000000000"})

    assert response.status_code == 404
    assert response.json()["code"] == "DEV_OTP_UNAVAILABLE"


async def test_dev_otp_awaits_background_delivery_before_read_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read-back beats the async delivery race by flushing the queue first.

    Delivery is background since PHASE-2 REM T4 (#86), so the dev/test read-back
    must await the facade's delivery queue before reading the recorded code. The
    enqueued send and the route run on the same event loop here (ASGITransport),
    so the route's flush is what makes the code readable - without it the
    background task would race the read.
    """
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    app = create_app()
    facade = cast(IamFacade, app.state.iam_facade)
    facade.delivery_queue.enqueue(
        SmsSendRequest(
            phone_e164="+919000000000",
            params=SmsTemplateParams(otp="123456"),
        )
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/auth/dev/otp", params={"phone": "+919000000000"})

    assert response.status_code == 200
    assert response.json() == {"code": "123456"}


def test_app_answers_cors_headers_for_the_dev_pwa_origin() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/me", headers={"Origin": "http://localhost:3000"})

    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def _cors_allow_origins(app: FastAPI) -> tuple[str, ...]:
    cors = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )
    return cors.kwargs["allow_origins"]


def test_create_app_cors_adds_nothing_when_config_empty() -> None:
    app = create_app(settings=Settings())

    assert _cors_allow_origins(app) == ("http://localhost:3000",)


def test_create_app_cors_preserves_localhost_and_adds_configured_origins() -> None:
    settings = Settings(cors_allowed_origins=("https://demo.example.com",))
    app = create_app(settings=settings)

    assert _cors_allow_origins(app) == ("http://localhost:3000", "https://demo.example.com")


def test_create_app_cors_dedupes_localhost_repeated_in_config() -> None:
    settings = Settings(cors_allowed_origins=("http://localhost:3000", "https://demo.example.com"))
    app = create_app(settings=settings)

    assert _cors_allow_origins(app) == ("http://localhost:3000", "https://demo.example.com")


def test_app_answers_cors_headers_for_the_configured_demo_origin() -> None:
    client = TestClient(
        create_app(settings=Settings(cors_allowed_origins=("https://demo.example.com",)))
    )

    response = client.get("/v1/me", headers={"Origin": "https://demo.example.com"})

    assert response.headers.get("access-control-allow-origin") == "https://demo.example.com"


def test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default() -> None:
    demo_app = create_app(settings=Settings(demo_mode=True))
    prod_app = create_app(settings=Settings())

    assert hasattr(demo_app.state, "mock_sms_adapter")
    assert not hasattr(prod_app.state, "mock_sms_adapter")


def test_dev_otp_reads_back_the_mock_code_in_demo_mode() -> None:
    app = create_app(settings=Settings(demo_mode=True))
    adapter = cast(MockSmsAdapter, app.state.mock_sms_adapter)
    asyncio.run(
        adapter.send(
            SmsSendRequest(
                phone_e164="+919000000000",
                params=SmsTemplateParams(otp="123456"),
            )
        )
    )

    response = TestClient(app).get("/v1/auth/dev/otp", params={"phone": "+919000000000"})

    assert response.status_code == 200
    assert response.json() == {"code": "123456"}


def test_dev_otp_returns_null_in_demo_mode_when_nothing_sent() -> None:
    app = create_app(settings=Settings(demo_mode=True))

    response = TestClient(app).get("/v1/auth/dev/otp", params={"phone": "+919000000000"})

    assert response.status_code == 200
    assert response.json() == {"code": None}
