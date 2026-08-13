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
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import _DEV_TEST_ENVIRONMENTS, Settings, get_settings
from app.gateway.errors import register_gateway_error_handlers
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.principal import Principal
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.rbac import require_patient
from modules.iam.adapters.routes import ErrorEnvelope, register_error_handlers
from modules.iam.adapters.routes import router as iam_router
from modules.iam.adapters.sms import MockSmsAdapter, build_sms_adapter
from modules.iam.facade import IamFacade

# Browser dev/E2E origin the PWA calls the API from (:3000). The staging edge
# reverse-proxies /api/* same-origin (deploy/edge/Caddyfile), so no CORS entry
# is needed outside local development and the Playwright suite.
_DEV_CORS_ORIGINS = ("http://localhost:3000",)


class MockOtpResponse(BaseModel):
    """Payload of the dev/test-only mock OTP read-back (api-standards §3)."""

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
    # SMS adapter is kept on app state as the read surface for the dev/test
    # only OTP read-back route (the E2E suite) - the real provider is gated out
    # of dev/test by Settings, so the adapter is a MockSmsAdapter whenever it
    # is stored.
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
    # Only keep the plaintext OTP read surface when it can never be a real
    # provider: mock SMS + a dev/test environment. Production-default boots
    # leave app.state.mock_sms_adapter absent.
    if (
        resolved_settings.sms_provider.strip().lower() == "mock"
        and resolved_settings.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS
    ):
        app.state.mock_sms_adapter = cast(MockSmsAdapter, sms_adapter)

    # Gateway middleware stack (PHASE-1 T7b, #29; PHASE-2 T8, #59). Caller
    # identity is established (jwt_verify, outermost) before per-identity rate
    # limiting (rate_limit), so later limits can key off the Principal.
    app.add_middleware(
        RateLimitMiddleware,
        enabled=resolved_settings.gateway_rate_limit_enabled,
        max_requests=resolved_settings.gateway_rate_limit_auth_max_requests,
        window_seconds=resolved_settings.gateway_rate_limit_auth_window_seconds,
    )
    app.add_middleware(
        JWTVerifyMiddleware,
        enabled=resolved_settings.gateway_jwt_verify_enabled,
        validate_token=facade.validate_token,
    )
    # CORS for the local-dev PWA origin (added last so it is outermost and the
    # allow-origin header reaches every response, including 401/403 from the
    # gateway stack). No production origin is granted; the staging edge proxies
    # the API same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_DEV_CORS_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    def dev_otp(request: Request, phone: str) -> MockOtpResponse | JSONResponse:
        """Dev/test-only read-back of the most recent mock OTP sent to a phone.

        The mock SMS adapter keeps sent codes in memory inside the backend
        process (they are hashed in the database), so the browser E2E suite
        needs a small HTTP read-back to drive register -> verify. Gated to the
        mock provider in dev/test; never answers against the real provider or
        in production.
        """
        settings = cast(Settings, request.app.state.settings)
        adapter = cast(MockSmsAdapter | None, getattr(request.app.state, "mock_sms_adapter", None))
        # mypy narrows ``adapter is not None`` only inside an if-condition, so
        # gate the success path directly rather than asserting on a boolean.
        if (
            settings.sms_provider.strip().lower() == "mock"
            and settings.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS
            and adapter is not None
        ):
            return MockOtpResponse(code=adapter.last_sent_code(phone))
        envelope = ErrorEnvelope(
            code="DEV_OTP_UNAVAILABLE",
            message="mock OTP read-back is only available in dev/test with the mock SMS adapter",
            trace_id=uuid4().hex,
            details={},
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=envelope.model_dump(),
        )

    return app


app = create_app()
