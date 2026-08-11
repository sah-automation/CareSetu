"""FastAPI application shell (PHASE-1 T7a, #28).

``create_app`` builds the ASGI app from the shared ``Settings`` and registers
the infra-only ``/health`` route. No business routes exist yet (Phase 2+); the
gateway middleware stack (#29) attaches to this app.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.gateway.jwt_verify import JWTVerifyMiddleware
from app.gateway.rate_limit import RateLimitMiddleware


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

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
