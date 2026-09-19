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

import app.main as app_main
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
        "/v1/auth/refresh",
        "/v1/auth/dev/otp",
        "/v1/me",
        # PHASE-3 T2 (#211): the owner-only record surface.
        "/v1/records",
        "/v1/records/{record_id}",
        # PHASE-3 T5 (#214): partner consent-gated record read.
        "/v1/records/consented-read",
        # PHASE-3 T3 (#212): the patient-driven consent lifecycle surface.
        "/v1/consents",
        "/v1/consents/requests",
        "/v1/consents/{consent_id}/grant",
        "/v1/consents/{consent_id}/revoke",
        "/v1/consents/{consent_id}/decline",
        # PHASE-3 T5 (#214): patient egress log.
        "/v1/consents/egress-log",
        # PHASE-3 T11 (#220): test-only data seeding endpoints.
        "/v1/test/seed",
        "/v1/test/seed-egress",
        # PHASE-4 T6 (#240): operator-only audit query surface.
        "/v1/audit/events",
        # PHASE-4 T7 (#241): patient-only own access-history surface.
        "/v1/audit/access-history",
        # PHASE-5 T05 (#249): open partner self-service registration.
        "/v1/partner/register",
        # PHASE-5 T06 (#251): partner credential submission (Step-1 pre-filter).
        "/v1/partner/credentials",
        # PHASE-5 T09 (#253): rejected-partner recovery - the partner view of
        # their specific rejection reason and the one-time appeal that
        # re-enters the operator queue.
        "/v1/partner/rejection-reason",
        "/v1/partner/appeal",
        # PHASE-5 review fix P2/P3 (#271): partner self-service onboarding
        # status (US-6) and current-round credential review status (US-7).
        "/v1/partner/me",
        "/v1/partner/me/verification",
        # PHASE-5 T08 (#252): the operator verification console (FEAT-015) -
        # age-sortable queue, per-partner detail, approve/reject gate.
        "/v1/partner/verification-queue",
        "/v1/partner/verification/{partner_id}",
        "/v1/partner/verification/{partner_id}/decision",
        # PHASE-5 T10 (#254): grace-window lapse auto-drop (event-driven reverify path).
        "/v1/partner/verification/{partner_id}/grace-lapse",
        # PHASE-5 S9 (#262): operator invite + MFA-gated operator login.
        "/v1/auth/operator/invite",
        "/v1/auth/operator/login",
        # PHASE-5 review fix P1 (#272): operator MFA TOTP enrollment.
        "/v1/auth/operator/mfa/enroll",
        # T05 (#298): partner-scoped session issuance for registered partners.
        "/v1/auth/partner/session",
        # F014 T02 (#462): partner OTP login - sends a challenge only when the
        # phone resolves to a registered partner profile.
        "/v1/auth/partner/login",
        # F014 T03 (#463): partner OTP verify - silent, consumes the challenge
        # and writes the phone-verified marker.
        "/v1/auth/partner/verify",
        # PHASE-6 T02a (#313): the public provider directory search (FEAT-004) -
        # open surface, patients browse without logging in.
        "/v1/directory/search",
        # PHASE-6 T03 (#309): the public provider profile (FEAT-005) - open
        # surface, patients view a provider's verified-safe profile.
        "/v1/directory/providers/{partner_id}",
        # PHASE-6 T4 (#326): the public directory-pick ingest (FEAT-004) -
        # open surface, anonymous analytics, same gateway surface as search.
        "/v1/directory/select",
        # PHASE-7 T12 (#356): the patient intake surface - submit, upload
        # media, re-record, read intake + pre-summary, save patient edits.
        "/v1/intake/submit",
        "/v1/intake/upload-media",
        # PHASE-8.1 T04 (#481): the doctor-scoped rx-input voice/photo upload.
        "/v1/intake/upload-doctor-media",
        "/v1/intake/{intake_id}/re-record",
        "/v1/intake/{intake_id}",
        "/v1/intake/{intake_id}/pre-summary",
        "/v1/intake/{intake_id}/patient-edits",
        # PHASE-7 T13 (#357): the doctor review-and-edit route (contract only).
        "/v1/intake/{intake_id}/review",
        # PHASE-7 T13/T17 (#373): the audio playback route - owning patient or
        # doctor partner streams the decrypted clip.
        "/v1/intake/{intake_id}/media/{media_ref_id}",
        # PHASE-8.1 T05 (#443): the patient pick-a-doctor + consent write.
        "/v1/intake/{intake_id}/pick-doctor",
        # PHASE-8.1 T07 (#447): the doctor review-queue read - assigned
        # pre-summaries awaiting review, low-confidence first.
        "/v1/intake/review-queue",
        # PHASE-8.1 T08 (#448): the doctor full pre-summary read - the assigned
        # doctor reads the pre-summary content (structured summary, confidence
        # flag, review state) before reviewing it.
        "/v1/intake/{intake_id}/pre-summary/review",
        # PHASE-8.1 T06 (#444): the doctor-owned consultation fee
        # (integer paise; null = not set) - partner-scoped update surface.
        "/v1/partner/consultation-fee",
        # PHASE-8 T06 (#422): the doctor care surface - consult-complete,
        # open-case list/detail, doctor input, rx draft/revision/approve/
        # reject, and the approved e-prescription read.
        "/v1/care/cases",
        "/v1/care/cases/{case_id}",
        "/v1/care/cases/{case_id}/consult-complete",
        "/v1/care/cases/{case_id}/doctor-input",
        "/v1/care/cases/{case_id}/rx/draft",
        "/v1/care/cases/{case_id}/rx/{rx_id}/revision",
        "/v1/care/cases/{case_id}/rx/{rx_id}/approve",
        "/v1/care/cases/{case_id}/rx/{rx_id}/reject",
        "/v1/care/cases/{case_id}/rx/current",
        "/v1/care/cases/{case_id}/close",
        "/v1/care/prescriptions/{rx_id}",
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


def test_lifespan_starts_in_process_dispatcher_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = {"called": False, "stopped": False}

    async def fake_run_worker(
        stop_event: asyncio.Event,
        settings: Settings | None = None,
        config: object = None,
    ) -> None:
        entered["called"] = True
        await stop_event.wait()
        entered["stopped"] = True

    monkeypatch.setattr(app_main, "run_worker_until_stopped", fake_run_worker)

    app = create_app(settings=Settings(dispatcher_in_process_enabled=True))

    with TestClient(app):
        assert entered["called"] is True

    assert entered["stopped"] is True


def test_lifespan_skips_in_process_dispatcher_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_run_worker(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(app_main, "run_worker_until_stopped", fake_run_worker)

    app = create_app(settings=Settings(dispatcher_in_process_enabled=False))

    with TestClient(app):
        pass

    assert called is False


def test_in_process_dispatcher_restarts_after_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    stop_event = asyncio.Event()

    async def flaky_run_worker(current_stop: asyncio.Event, **_: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient db blip")
        await current_stop.wait()

    monkeypatch.setattr(app_main, "run_worker_until_stopped", flaky_run_worker)

    async def run() -> None:
        await asyncio.wait_for(
            app_main._run_in_process_dispatcher(stop_event, Settings(), restart_delay_seconds=0.01),
            timeout=1.0,
        )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run())

    assert calls >= 2
    stop_event.set()
