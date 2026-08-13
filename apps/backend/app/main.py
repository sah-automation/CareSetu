"""FastAPI application shell (PHASE-1 T7a, #28; PHASE-2 T3, #54; T8, #59).

``create_app`` builds the ASGI app from the shared ``Settings``, registers the
infra-only ``/health`` route, and (Phase 2) mounts the iam module's public
routes behind the gateway middleware stack. The iam facade - engine, EXT-001
adapter, clock - is resolved once from ``Settings`` and stored on
``app.state.iam_facade`` so routes read one settled instance. The gateway's
``jwt_verify`` calls that same facade's ``validate_token``; ``/v1/me`` is the
protected route that proves the edge admit/deny.
"""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.gateway.errors import register_gateway_error_handlers
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.principal import Principal
from app.gateway.rate_limit import RateLimitMiddleware
from app.gateway.rbac import require_patient
from modules.iam.adapters.routes import register_error_handlers
from modules.iam.adapters.routes import router as iam_router
from modules.iam.adapters.sms import build_sms_adapter
from modules.iam.facade import IamFacade


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
    # call the facade's ``validate_token`` on the settled instance.
    engine = create_async_engine(resolved_settings.database_url, poolclass=NullPool)
    facade = IamFacade(
        engine=engine,
        sms_adapter=build_sms_adapter(resolved_settings),
        access_token_signing_key=resolved_settings.gateway_jwt_signing_key,
        access_token_ttl_seconds=resolved_settings.gateway_access_token_ttl_seconds,
        refresh_token_ttl_seconds=resolved_settings.gateway_refresh_token_ttl_seconds,
    )
    app.state.iam_facade = facade

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

    return app


app = create_app()
