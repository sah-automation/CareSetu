"""FastAPI application shell (PHASE-1 T7a, #28; PHASE-2 T3, #54; T8, #59).

``create_app`` builds the ASGI app from the shared ``Settings``, registers the
infra-only ``/health`` route, and (Phase 2) mounts the iam module's public
routes behind the gateway middleware stack. The iam facade - engine, EXT-001
adapter, clock - is resolved once from ``Settings`` and stored on
``app.state.iam_facade`` so routes read one settled instance. The gateway's
``jwt_verify`` calls that same facade's ``validate_token``; ``/v1/me`` is the
protected route that proves the edge admit/deny.
"""

from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.gateway.errors import register_gateway_error_handlers
from app.gateway.idempotency import IdempotencyStore
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.principal import Principal
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.rbac import require_patient
from app.gateway.security_headers import SecurityHeadersMiddleware
from app.gateway.trace import TraceMiddleware, resolve_trace_id
from modules.iam.adapters.routes import ErrorEnvelope, register_error_handlers
from modules.iam.adapters.routes import router as iam_router
from modules.iam.adapters.sms import MockSmsAdapter, build_sms_adapter
from modules.iam.facade import IamFacade

# Browser dev/E2E origin the PWA calls the API from (:3000). The staging edge
# reverse-proxies /api/* same-origin (deploy/edge/Caddyfile), so no CORS entry
# is needed outside local development and the Playwright suite.
_DEV_CORS_ORIGINS = ("http://localhost:3000",)


class MockOtpResponse(BaseModel):
    """Payload of the dev/test/demo mock OTP read-back (api-standards §3)."""

    code: str | None


class HealthResponse(BaseModel):
    """Payload of the ``/health`` route."""

    status: Literal["ok"]


class MeResponse(BaseModel):
    """Payload of the protected ``/v1/me`` route (the caller's own identity).

    ``subject_id`` is the identity the token is scoped to - a patient sees
    their own record id and nothing else; ``roles`` is the resolved RBAC scope
    from the token claim (api-standards §6).
    """

    subject_id: str
    roles: list[str]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application, resolving config when none is given.

    Settings are stored on ``app.state.settings`` so the gateway (#29) and
    worker (#30) can read the same resolved config from the app instance.
    """
    resolved_settings = settings if settings is not None else get_settings()
    app = FastAPI(title="CareSetu API", version="0.1.0")
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
    )
    app.state.iam_facade = facade
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
    register_error_handlers(app)
    register_gateway_error_handlers(app)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/v1/me", response_model=MeResponse)
    def me(principal: Annotated[Principal, Depends(require_patient)]) -> MeResponse:
        """Protected proof route: admit only a valid patient-scoped session."""
        return MeResponse(subject_id=principal.subject_id, roles=list(principal.roles))

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

    return app


app = create_app()
