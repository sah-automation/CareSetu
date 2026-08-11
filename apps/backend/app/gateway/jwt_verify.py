"""``jwt_verify`` gateway middleware stub (PHASE-1 T7b, #29).

Accept-all stub: when enabled it reads the configured test header and attaches a
typed ``Principal`` to the request state. A missing header still yields an
anonymous principal - nothing is ever rejected here. Disabled by default; Phase 2
replaces the accept-all logic with real JWT verification behind this settled
seam.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.gateway.principal import Principal


class JWTVerifyMiddleware(BaseHTTPMiddleware):
    """Attach a ``Principal`` to every request when enabled; else pass through."""

    def __init__(self, app: ASGIApp, *, enabled: bool, test_header: str) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.test_header = test_header

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)

        subject_id = request.headers.get(self.test_header)
        if subject_id:
            request.state.principal = Principal.for_subject(subject_id)
        else:
            request.state.principal = Principal.anonymous()
        return await call_next(request)
