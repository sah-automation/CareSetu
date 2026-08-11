"""``rate_limit`` gateway middleware stub (PHASE-1 T7b, #29).

Disabled by default; when enabled it is still an accept-all no-op that records
its run on the request state so the wiring is observable. Phase 2 implements
per-identity/IP limits behind this settled seam (``NFR-SEC-004``).
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Placeholder for rate limiting; currently accepts every request."""

    def __init__(self, app: ASGIApp, *, enabled: bool) -> None:
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.enabled:
            request.state.gateway_rate_limit_checked = True
        return await call_next(request)
