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
        # PHASE-8.1 T1 (#482): the patient's own profile-completion read/write.
        "/v1/me/profile",
        # US-20 (#533): the patient's own profile-photo upload/replace/preview/remove.
        "/v1/me/photo",
        # US-21/US-22 (#534): the patient's health-background snapshot read/write
        # with the one-time first-save acknowledgement.
        "/v1/me/health-background",
        # US-23 (#535): the height/weight time series the patient appends next
        # to the snapshot - append (POST) and newest-first paged list (GET).
        "/v1/me/health-background/metrics",
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
        # #768: the admin-only operator user list for user management.
        "/v1/auth/operator/users",
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
        # B4e (#721): the funnel's entry step - a bodyless patient-scoped POST
        # that records that the composer opened and writes no clinical content.
        "/v1/intake/composer-opened",
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
        # PHASE-8.1 T09 (#484): the doctor-owned intake-detail read keyed by
        # pre-summary id - resolves the intake and enforces the assigned-doctor
        # scope for the case workspace transcript + audio surface.
        "/v1/intake/pre-summary/{pre_summary_id}/detail",
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
        # PHASE-8.2 T01 (#539): the doctor console Patients list - derived
        # Current/Past buckets over live grants + care cases (ADR-0019).
        "/v1/doctor/patients",
        # #647: the doctor's open-cases list - the console seam's derived
        # projection, cases plus the patient's name/age/photo presence.
        "/v1/doctor/cases",
        # PHASE-8.2 T02 (#540): the consent-gated patient detail read and
        # its gated photo stream - contact/consultation/health-background
        # sections locked under the wrong grant (ADR-0019).
        "/v1/doctor/patients/{patient_id}",
        "/v1/doctor/patients/{patient_id}/photo",
        "/v1/doctor/profile",
        "/v1/doctor/profile/photo",
        # #608-#610: all four Practice/Address/About/Notification section writes.
        # Each takes its own path under the profile prefix rather than a second
        # verb on /v1/doctor/profile, so a replayed Idempotency-Key issued
        # against one write can never be served another's stored result.
        "/v1/doctor/profile/practice",
        "/v1/doctor/profile/address",
        "/v1/doctor/profile/about",
        "/v1/doctor/profile/notifications",
        # PHASE-14A C1 (#706/#707): the whole plan-phase14 §9.1 operator
        # observability read table.
        "/v1/operator/observability/cost",
        "/v1/operator/observability/cost/trend",
        "/v1/operator/observability/usage",
        "/v1/operator/observability/quality",
        "/v1/operator/observability/overview",
        "/v1/operator/observability/latency",
        "/v1/operator/observability/health",
        "/v1/operator/observability/alerts",
        "/v1/operator/observability/deeplinks",
        # PHASE-14B Batch 2 (#782): the security summary read.
        "/v1/operator/observability/security",
        # PHASE-14A B9 (#727): the per-minute request counter, which carries the
        # capture-liveness answer rather than only the numbers.
        "/v1/operator/observability/throughput",
        # PHASE-14A B9 (#728): the degraded-provider board, one row per upstream
        # model API with its healthy/degraded/down status derived at read time.
        "/v1/operator/observability/providers",
        # PHASE-14A B5 (#729): the reliability read - AI-queue depth with the age of
        # the oldest queued item, the per-outbox backlog breakdown, the RECENT-activity
        # figure, and the link out to true concurrency.
        "/v1/operator/observability/reliability",
        # PHASE-14A B8 (#730): the live error feed, served from the capture's own
        # collapsed rows because Postgres is the system of record.
        "/v1/operator/observability/errors",
        # PHASE-14A B2 (#731): the business read - ONE period-parameterised endpoint
        # serving today, week-to-date and month-to-date, so the three periods are not
        # three aggregation copies.
        "/v1/operator/observability/business",
        # PHASE-14A B8 (#740): the funnel read - the walk from the composer to an
        # issued e-prescription or a closed case, with each step's conversion, the
        # median gap to the step before it, and success and abandonment over one
        # denominator.
        "/v1/operator/observability/product/funnel",
        # PHASE-14A B4f (#741): the adoption read - daily, weekly and monthly active
        # users with the stickiness ratio between them, plus the window's throughput,
        # requests per active user and a daily load trend, all computed in Postgres
        # because the free metrics tier's fourteen-day retention cannot answer a month.
        "/v1/operator/observability/product/active-users",
        # PHASE-14A B4g (#742): the stickiness read - what share of each arrival day
        # came back at seven and thirty days, derived at read time from the daily
        # per-actor product aggregate so a thirty-day question never scans the raw
        # event ledger.
        "/v1/operator/observability/product/retention-cohorts",
        # PHASE-14A B5 (#735): the one operator WRITE in the module - the
        # acknowledgement that fills the alert row's acked_by/acked_at columns.
        "/v1/operator/observability/alerts/{alert_id}/acknowledge",
        # MOD-014 ops (#771/#773): effective-settings read, settings write,
        # feature-flag list/read and the runtime flag write.
        "/v1/operator/settings",
        "/v1/operator/settings/effective",
        # #798: the append-only setting history the Settings AI section reads
        # after every successful write.
        "/v1/operator/settings/history",
        "/v1/operator/feature-flags",
        "/v1/operator/feature-flags/{flag_key}",
        "/v1/auth/operator/users/{identity_id}/active",
        "/v1/auth/operator/users/{identity_id}/tier",
        "/v1/operator/feature-flags/history",
        "/v1/operator/observability/alert-delivery",
        "/v1/operator/observability/alert-delivery/test",
        "/v1/operator/observability/alert-delivery/{delivery_id}/redeliver",
        "/v1/operator/observability/evaluation",
        "/v1/operator/observability/evaluation/agreement",
        "/v1/operator/observability/evaluation/dataset/active",
        "/v1/operator/observability/evaluation/datasets",
        "/v1/operator/observability/evaluation/datasets/seed",
        "/v1/operator/observability/evaluation/datasets/{name}/{version}",
        "/v1/operator/observability/evaluation/datasets/{name}/{version}/activate",
        "/v1/operator/observability/evaluation/datasets/{name}/{version}/clone",
        "/v1/operator/observability/evaluation/datasets/{name}/{version}/retire",
        "/v1/operator/observability/evaluation/golden-labels",
        "/v1/operator/observability/evaluation/golden-labels/{example_ref}",
        "/v1/operator/observability/evaluation/human-labels",
        "/v1/operator/observability/evaluation/human-labels/{example_ref}",
        "/v1/operator/observability/evaluation/labels",
        "/v1/operator/observability/evaluation/labels/golden",
        "/v1/operator/observability/evaluation/labels/human",
        "/v1/operator/observability/evaluation/labels/{example_ref}",
        "/v1/operator/observability/evaluation/labels/{example_ref}/label",
        "/v1/operator/observability/evaluation/runs",
        "/v1/operator/observability/evaluation/runs/latest",
        "/v1/operator/observability/evaluation/scores",
        "/v1/operator/observability/golden-labels",
        "/v1/operator/observability/human-labels",
        "/v1/operator/observability/labels",
        "/v1/operator/observability/labels/{example_ref}",
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
