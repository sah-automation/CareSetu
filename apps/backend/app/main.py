"""FastAPI application shell (PHASE-1 T7a, #28; PHASE-2 T3, #54).

``create_app`` builds the ASGI app from the shared ``Settings``, registers the
infra-only ``/health`` route, and (Phase 2) mounts the iam module's public
routes behind the gateway middleware stack. The iam facade - engine, EXT-001
adapter, clock - is resolved once from ``Settings`` and stored on
``app.state.iam_facade`` so routes read one settled instance.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware
from modules.iam.adapters.routes import register_error_handlers
from modules.iam.adapters.routes import router as iam_router
from modules.iam.adapters.sms import build_sms_adapter
from modules.iam.facade import IamFacade


class HealthResponse(BaseModel):
    """Payload of the ``/health`` route."""

    status: Literal["ok"]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application, resolving config when none is given.

    Settings are stored on ``app.state.settings`` so the gateway (#29) and
    worker (#30) can read the same resolved config from the app instance.
    """
    resolved_settings = settings if settings is not None else get_settings()
    app = FastAPI(title="CareSetu API", version="0.1.0")
    app.state.settings = resolved_settings

    # Gateway middleware stack (PHASE-1 T7b, #29). Both stubs are disabled by
    # default; the order is the contract Phase 2 fills in - caller identity is
    # established (jwt_verify, outermost) before per-identity rate limiting
    # (rate_limit), so later limits can key off the Principal.
    app.add_middleware(
        RateLimitMiddleware,
        enabled=resolved_settings.gateway_rate_limit_enabled,
    )
    app.add_middleware(
        JWTVerifyMiddleware,
        enabled=resolved_settings.gateway_jwt_verify_enabled,
        test_header=resolved_settings.gateway_jwt_test_header,
    )

    # MOD-001 (PHASE-2 T3, #54): one resolved iam facade instance behind the
    # gateway stack. The engine is lazy - no connection is opened at boot.
    engine = create_async_engine(resolved_settings.database_url, poolclass=NullPool)
    app.state.iam_facade = IamFacade(
        engine=engine,
        sms_adapter=build_sms_adapter(resolved_settings),
    )
    app.include_router(iam_router)
    register_error_handlers(app)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
