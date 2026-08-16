"""NFR-SEC-001 transport-posture response headers (TEST-B2, #136).

The boundary security posture gate (``scripts/security_posture.py``) asserts
HTTPS-only, TLS 1.2+, HSTS, and ``X-Content-Type-Options`` against the live
Render backend and Vercel frontend URLs. Render free web services cannot
inject response headers at the platform edge (Render's ``headers`` feature is
static-sites-only), so the backend emits the headers itself; the frontend
carries them in its Vercel edge config (``apps/frontend/vercel.json``).

Always on and unconditional - there is no environment where omitting these
headers is the right posture, so unlike the gateway middleware there is no
Settings flag. ``setdefault`` preserves an upstream value (e.g. a future
platform header) when one exists.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_HSTS_VALUE = "max-age=31536000; includeSubDomains"
_X_CONTENT_TYPE_OPTIONS_VALUE = "nosniff"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Emit the NFR-SEC-001 headers on every response of the app.

    Registered outermost of the whole stack (after ``TraceMiddleware``) so a
    rejection from an inner gateway middleware, an iam error handler, or a
    404 from the router carries the same transport-posture headers as a 200.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Strict-Transport-Security", _HSTS_VALUE)
        response.headers.setdefault("X-Content-Type-Options", _X_CONTENT_TYPE_OPTIONS_VALUE)
        return response
