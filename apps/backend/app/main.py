"""FastAPI application shell (PHASE-1 T7a, #28; PHASE-2 T3, #54; T8, #59).

``create_app`` builds the ASGI app from the shared ``Settings``, registers the
infra-only ``/health`` route, and (Phase 2) mounts the iam module's public
routes behind the gateway middleware stack. The iam facade - engine, EXT-001
adapter, clock - is resolved once from ``Settings`` and stored on
``app.state.iam_facade`` so routes read one settled instance. The gateway's
``jwt_verify`` calls that same facade's ``validate_token``; ``/v1/me`` is the
protected route that proves the edge admit/deny.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.gateway.errors import ErrorEnvelope, register_gateway_error_handlers
from app.gateway.idempotency import IdempotencyStore
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.principal import Principal
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.rbac import require_authenticated, require_patient
from app.gateway.security_headers import SecurityHeadersMiddleware
from app.gateway.trace import TraceMiddleware, resolve_trace_id
from modules.audit.adapters.routes import router as audit_router
from modules.audit.facade import AuditFacade
from modules.consent.adapters.routes import (
    register_error_handlers as register_consent_error_handlers,
)
from modules.consent.adapters.routes import router as consent_router
from modules.consent.facade import ConsentFacade
from modules.consent.redis_cache import close_redis_client, init_redis_client
from modules.health.adapters.routes import register_error_handlers as register_health_error_handlers
from modules.health.adapters.routes import router as health_router
from modules.health.facade import HealthFacade
from modules.iam.adapters.routes import register_error_handlers
from modules.iam.adapters.routes import router as iam_router
from modules.iam.adapters.sms import MockSmsAdapter, build_sms_adapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import build_artifact_store
from modules.partner.adapters.routes import (
    register_error_handlers as register_partner_error_handlers,
)
from modules.partner.adapters.routes import router as partner_router
from modules.partner.facade import PartnerFacade

logger = logging.getLogger(__name__)

# Browser dev/E2E origin the PWA calls the API from (:3000). The staging edge
# reverse-proxies /api/* same-origin (deploy/edge/Caddyfile), so no CORS entry
# is needed outside local development and the Playwright suite.
_DEV_CORS_ORIGINS = ("http://localhost:3000",)


class MockOtpResponse(BaseModel):
    """Payload of the dev/test/demo mock OTP read-back (api-standards §3)."""

    code: str | None


class SeedResponse(BaseModel):
    """Payload of the test-only /v1/test/seed endpoint.

    Returns the record entries created via synthetic outbox rows processed
    through the real dispatcher (PHASE-3 T11, #220).
    """

    entry_ids: list[int]
    entry_types: list[str]


class SeedEgressResponse(BaseModel):
    """Payload of the test-only /v1/test/seed-egress endpoint.

    Inserts a synthetic egress log row to prove the egress slice renders
    in the consent log screen (PHASE-3 T11, #220).
    """

    egress_id: int


class HealthResponse(BaseModel):
    """Payload of the ``/health`` route."""

    status: Literal["ok"]


class MeResponse(BaseModel):
    """Payload of the protected ``/v1/me`` route (the caller's own identity).

    ``subject_id`` is the identity the token is scoped to - a patient sees
    their own record id and nothing else; ``roles`` is the resolved RBAC scope
    from the token claim (api-standards §6). ``phone`` (PHASE-2.6 T05, #196,
    decision D4) is the caller's E.164 number resolved from the identity
    table, additive so older clients keep working.
    """

    subject_id: str
    roles: list[str]
    phone: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application, resolving config when none is given.

    Settings are stored on ``app.state.settings`` so the gateway (#29) and
    worker (#30) can read the same resolved config from the app instance.
    """
    resolved_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Initialize Redis client for consent cache
        await init_redis_client(resolved_settings)
        yield
        # Close Redis client on shutdown
        await close_redis_client()

    app = FastAPI(title="CareSetu API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings

    # MOD-001 (PHASE-2 T3, #54): one resolved iam facade instance behind the
    # gateway stack. The engine is lazy - no connection is opened at boot. It
    # is resolved before the middleware is registered so ``jwt_verify`` can
    # call the facade's ``validate_token`` on the settled instance. The mock
    # SMS adapter is kept on app state as the read surface for the dev/test/demo
    # OTP read-back route (the E2E suite and the deployed demo) - the real
    # provider is gated out of dev/test by Settings, so the adapter is a
    # MockSmsAdapter whenever it is stored.
    engine = create_async_engine(resolved_settings.database_url, poolclass=NullPool)
    sms_adapter = build_sms_adapter(resolved_settings)
    facade = IamFacade(
        engine=engine,
        sms_adapter=sms_adapter,
        access_token_signing_key=resolved_settings.gateway_jwt_signing_key,
        access_token_ttl_seconds=resolved_settings.gateway_access_token_ttl_seconds,
        refresh_token_ttl_seconds=resolved_settings.gateway_refresh_token_ttl_seconds,
        mfa_secret_key=resolved_settings.iam_mfa_secret_key,
    )
    app.state.iam_facade = facade
    # MOD-004 (PHASE-3 T3, #212): the consent facade shares the same settled
    # engine and app-state pattern - routes read one resolved object and unit
    # tests stub it on state.
    app.state.consent_facade = ConsentFacade(engine=engine)
    # MOD-003 (PHASE-3 T2, #211): the record facade shares the one settled
    # engine - no connection opens at boot - and is stored like the iam
    # instance so routes read one resolved object and unit tests can stub it.
    # Pass consent_facade for PHASE-3 T5 (#214) gated reads.
    app.state.health_facade = HealthFacade(engine=engine, consent_facade=app.state.consent_facade)
    # MOD-011 (PHASE-4 T6, #240): the audit facade shares the settled engine
    # for the operator query surface - stored on state so routes read one
    # resolved object and unit tests stub it. The health facade (MOD-003) is
    # passed for T7's patient access-history delegation: the ledger lives in
    # the health schema, so the audit facade calls through the facade seam
    # instead of reading across schemas (module isolation rule).
    app.state.audit_facade = AuditFacade(engine=engine, health_facade=app.state.health_facade)
    # MOD-002 (PHASE-5 T05, #249): the partner facade shares the settled engine
    # and, for open registration (ADR-0010), the settled iam facade - the sync
    # ``create_credential_account`` seam is called in-sequence at registration
    # so a login-capable account exists before the partner can authenticate.
    # Stored on state so the registration route reads one resolved instance and
    # unit tests stub it.
    # MOD-002 (PHASE-5 T06, #251): credential documents are AES-encrypted into
    # the ``partner/`` object-storage prefix before a Step-1 pass enters the
    # queue. The store's key/root come from the environment (fail-closed when a
    # key is supplied but malformed); dev/test without a key derives an ephemeral
    # one so the encrypted write path still runs.
    partner_artifact_store = build_artifact_store(
        root=resolved_settings.partner_artifact_root,
        b64_key=resolved_settings.partner_artifact_key,
    )
    app.state.partner_facade = PartnerFacade(
        engine=engine,
        iam_facade=facade,
        artifact_store=partner_artifact_store,
        audit_facade=app.state.audit_facade,
        re_submission_max=resolved_settings.partner_re_submission_max,
        re_submission_cooldown_days=resolved_settings.partner_re_submission_cooldown_days,
        credential_cleanup_days=resolved_settings.partner_credential_cleanup_days,
    )
    # The edge's in-process idempotency store (api-standards §5, PHASE-2 REM
    # T11, #80): the auth mutation adapters read/write it per ``Idempotency-Key``
    # so a retried register/verify/resend replays the stored result instead of
    # re-executing. Resolved once like the facade; a restart loses the entries
    # and degrades to at-most-once (documented trade-off in the store module).
    app.state.idempotency_store = IdempotencyStore()
    # Only keep the plaintext OTP read surface when it can never be a real
    # provider (mock SMS in dev/test, or the explicit demo flag - deployment
    # plan 4.3). Production-default boots leave app.state.mock_sms_adapter
    # absent. The policy lives on Settings.mock_otp_readback_enabled so the
    # storage gate and the route gate below can never drift apart.
    if resolved_settings.mock_otp_readback_enabled:
        app.state.mock_sms_adapter = cast(MockSmsAdapter, sms_adapter)

    # Gateway middleware stack (PHASE-1 T7b, #29; PHASE-2 T8, #59; REM T6, #77;
    # REM T8, #78). The auth surface is unauthenticated, so rate_limit is the
    # outermost of the gateway pair: every /v1/auth/* request - valid, invalid,
    # or missing token - is counted toward the per-client-IP cap before
    # jwt_verify can short-circuit on a bad token. jwt_verify runs inside the
    # limiter and attaches the settled Principal for the routes and the
    # protected-route dependency.
    app.add_middleware(
        JWTVerifyMiddleware,
        enabled=resolved_settings.gateway_jwt_verify_enabled,
        validate_token=facade.validate_token,
    )
    app.add_middleware(
        RateLimitMiddleware,
        enabled=resolved_settings.gateway_rate_limit_enabled,
        max_requests=resolved_settings.gateway_rate_limit_auth_max_requests,
        window_seconds=resolved_settings.gateway_rate_limit_auth_window_seconds,
    )
    # CORS for the local-dev PWA origin (added so the allow-origin header
    # reaches every response, including 401/403 from the gateway stack). The
    # deployment plan's public demo adds the env-configured Vercel origin on
    # top, deduped against the dev origin; empty config grants nothing extra.
    # The staging edge proxies the API same-origin and needs no CORS entry.
    allow_origins = tuple(dict.fromkeys(_DEV_CORS_ORIGINS + resolved_settings.cors_allowed_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    # Trace established outermost of the whole stack (PHASE-2 REM T6, #77), so
    # the one request-scoped trace id is settled before the gateway middleware
    # and every route can answer - a 401/403/429/422/5xx envelope and the log
    # line that records it carry the same id (error-handling-observability §3).
    app.add_middleware(TraceMiddleware)
    # NFR-SEC-001 transport-posture headers on the outermost user middleware
    # (TEST-B2, #136): every response the gateway emits - 200, gateway
    # rejection, 404 - carries HSTS and X-Content-Type-Options, the exact pair
    # the boundary security posture gate asserts against the live URLs.
    # Registered last so it wraps the trace middleware's responses too; the
    # one path it does not cover is a 500 regenerated by Starlette's
    # ServerErrorMiddleware, which sits outside all user middleware.
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(iam_router)
    app.include_router(health_router)
    app.include_router(consent_router)
    app.include_router(audit_router)
    app.include_router(partner_router)
    register_error_handlers(app)
    register_gateway_error_handlers(app)
    register_health_error_handlers(app)
    register_consent_error_handlers(app)
    register_partner_error_handlers(app)

    # Catch-all for any unhandled exception that escapes the module-level
    # handlers above (e.g. SQLAlchemy OperationalError from a DB connection
    # failure).  Without this, Starlette's own ServerErrorMiddleware - which
    # sits OUTSIDE all user middleware including CORSMiddleware - generates a
    # raw 500 HTML page with no CORS headers, causing the browser to report a
    # misleading CORS error instead of the real failure.
    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        trace_id = resolve_trace_id(request)
        logger.exception("unhandled_exception trace_id=%s path=%s", trace_id, request.url.path)
        envelope = ErrorEnvelope(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
            trace_id=trace_id,
            details={},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(mode="json"),
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/v1/me", response_model=MeResponse)
    async def me(
        request: Request, principal: Annotated[Principal, Depends(require_authenticated)]
    ) -> MeResponse:
        """Protected proof route: admit any authenticated principal.

        The phone is resolved through the iam facade's one-column lookup by
        the principal's subject id (PHASE-2.6 T05, #196) - the route never
        touches the database itself.
        """
        facade = cast(IamFacade, request.app.state.iam_facade)
        phone = await facade.identity_phone(int(principal.subject_id))
        return MeResponse(
            subject_id=principal.subject_id,
            roles=list(principal.roles),
            phone=phone,
        )

    @app.get("/v1/auth/dev/otp", response_model=MockOtpResponse)
    async def dev_otp(request: Request, phone: str) -> MockOtpResponse | JSONResponse:
        """Dev/test/demo read-back of the most recent mock OTP sent to a phone.

        The mock SMS adapter keeps sent codes in memory inside the backend
        process (they are hashed in the database), so the browser E2E suite and
        the deployed portfolio demo need a small HTTP read-back to drive
        register -> verify. Delivery is asynchronous since PHASE-2 REM T4
        (#86), so the route first awaits the facade's delivery queue - the
        read-back is safe against the background send racing the response - and
        only then reads the recorded code. Gated to the mock provider in
        dev/test, or in any environment under the explicit DEMO_MODE flag
        (deployment plan 4.3); never answers against the real provider.
        """
        settings = cast(Settings, request.app.state.settings)
        adapter = cast(MockSmsAdapter | None, getattr(request.app.state, "mock_sms_adapter", None))
        facade = cast(IamFacade, request.app.state.iam_facade)
        # mypy narrows ``adapter is not None`` only inside an if-condition, so
        # gate the success path directly rather than asserting on a boolean.
        if settings.mock_otp_readback_enabled and adapter is not None:
            await facade.delivery_queue.flush()
            return MockOtpResponse(code=adapter.last_sent_code(phone))
        envelope = ErrorEnvelope(
            code="DEV_OTP_UNAVAILABLE",
            message="mock OTP read-back is only available in dev/test with the mock SMS adapter",
            trace_id=resolve_trace_id(request),
            details={},
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=envelope.model_dump(),
        )

    @app.post("/v1/test/seed", response_model=SeedResponse)
    async def test_seed(
        request: Request, principal: Annotated[Principal, Depends(require_patient)]
    ) -> SeedResponse | JSONResponse:
        """Test-only data seeding via synthetic outbox rows (PHASE-3 T11, #220).

        Creates a lab report and a prescription entry by publishing synthetic
        outbox events through the real dispatcher. Gated to the same dev/test
        surface as the mock OTP read-back (``mock_otp_readback_enabled``).

        Timeline entries are seeded by emitting synthetic outbox rows fanned
        out through the real dispatcher - no direct table inserts.
        """
        settings = cast(Settings, request.app.state.settings)
        if not settings.mock_otp_readback_enabled:
            envelope = ErrorEnvelope(
                code="SEED_UNAVAILABLE",
                message="test seeding is only available in dev/test mode",
                trace_id=resolve_trace_id(request),
                details={},
            )
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=envelope.model_dump(),
            )

        from datetime import UTC, datetime
        from uuid import uuid4

        from bus.dispatch import dispatch
        from bus.envelope import Envelope
        from bus.outbox_writer import write_outbox
        from modules.health.domain.events import (
            PrescriptionIssuedPayload,
            ReportFiledPayload,
        )
        from modules.health.outbox import HEALTH_OUTBOX_TABLE
        from worker.main import build_registry

        patient_id = int(principal.subject_id)
        now = datetime.now(UTC)
        registry = build_registry()
        entry_ids: list[int] = []
        entry_types: list[str] = []

        # Publish report.filed + prescription.issued through the outbox and
        # dispatch synchronously so the handlers create record entries in the
        # same request cycle.
        report_envelope = Envelope[ReportFiledPayload](
            event_id=uuid4(),
            event_type="report.filed",
            occurred_at=now,
            producer="test.seed",
            payload=ReportFiledPayload(
                order_id=9001,
                patient_id=patient_id,
                filename="Blood_Panel_2026.pdf",
                occurred_at=now.isoformat(),
            ),
        )
        rx_envelope = Envelope[PrescriptionIssuedPayload](
            event_id=uuid4(),
            event_type="prescription.issued",
            occurred_at=now,
            producer="test.seed",
            payload=PrescriptionIssuedPayload(
                prescription_id=8001,
                patient_id=patient_id,
                occurred_at=now.isoformat(),
            ),
        )

        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await write_outbox(connection, "health", HEALTH_OUTBOX_TABLE, report_envelope)
                await write_outbox(connection, "health", HEALTH_OUTBOX_TABLE, rx_envelope)
            # Dispatch synchronously - handlers create record entries.
            await dispatch(registry, report_envelope)
            await dispatch(registry, rx_envelope)
        finally:
            await engine.dispose()

        # Read back the created entries to return their IDs.
        health_facade = cast(HealthFacade, request.app.state.health_facade)
        entry_ids, entry_types = await health_facade.seed_record_entries(patient_id)

        return SeedResponse(entry_ids=entry_ids, entry_types=entry_types)

    @app.post("/v1/test/seed-egress", response_model=SeedEgressResponse)
    async def test_seed_egress(
        request: Request, principal: Annotated[Principal, Depends(require_patient)]
    ) -> SeedEgressResponse | JSONResponse:
        """Test-only egress data seeding (PHASE-3 T11, #220).

        Inserts a synthetic row into ``consent.consent_egress_log`` so the
        consent log screen's egress table renders with real data. Gated to
        the same dev/test surface as mock OTP read-back.

        The egress log normally records partner disclosures; since partners
        do not exist yet, this endpoint creates the row directly.
        """
        settings = cast(Settings, request.app.state.settings)
        if not settings.mock_otp_readback_enabled:
            envelope = ErrorEnvelope(
                code="SEED_UNAVAILABLE",
                message="test seeding is only available in dev/test mode",
                trace_id=resolve_trace_id(request),
                details={},
            )
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=envelope.model_dump(),
            )

        patient_id = int(principal.subject_id)
        consent_facade = cast(ConsentFacade, request.app.state.consent_facade)
        egress_id = await consent_facade.seed_egress_log(
            patient_id=patient_id,
            counterparty_type="doctor",
            counterparty_id="e2e-test-doctor",
            record_scope="full_record",
            disclosed_entry_ids=[],
        )

        return SeedEgressResponse(egress_id=egress_id)

    return app


app = create_app()
