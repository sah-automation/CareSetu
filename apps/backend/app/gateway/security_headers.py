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

CSP report-only (PHASE-14B Batch 2, #775): hardened CSP on API responses.
The report URI is taken from Settings.csp_report_uri when
Settings.csp_report_only_enabled is True. When unset, reporting directives
are omitted.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings

_HSTS_VALUE = "max-age=31536000; includeSubDomains"
_X_CONTENT_TYPE_OPTIONS_VALUE = "nosniff"

# Hardened CSP for API responses (JSON and error pages)
# - default-src 'self': only same origin
# - script-src 'self': scripts only from same origin (API serves no inline scripts)
# - style-src 'self': styles only from same origin
# - img-src 'self' data:: images from same origin and data URIs
# - font-src 'self': fonts from same origin
# - connect-src 'self': connections only to same origin
# - frame-ancestors 'none': no framing
# - form-action 'self': forms only to same origin
# - base-uri 'self': base URI only same origin
# - object-src 'none': no plugins
# - report-uri/report-to: when collector URL is set
_API_CSP_BASE = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


def _build_csp_header(settings: Settings) -> str:
    """Build the CSP header value for API responses."""
    if not settings.csp_report_only_enabled or not settings.csp_report_uri.strip():
        return _API_CSP_BASE
    # Use both report-uri (legacy) and report-to (modern) for compatibility
    return f"{_API_CSP_BASE}; report-uri {settings.csp_report_uri}; report-to csp-endpoint"


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
        # CSP header for API responses (PHASE-14B Batch 2, #775)
        # Gracefully handle missing app state (e.g., in tests that create bare Request objects)
        app = request.scope.get("app")
        if app is not None and hasattr(app, "state") and hasattr(app.state, "settings"):
            settings: Settings = app.state.settings
            csp_value = _build_csp_header(settings)
            if csp_value:
                response.headers.setdefault("Content-Security-Policy", csp_value)
                # Also set Reporting-Endpoints header when report URI is configured
                if settings.csp_report_only_enabled and settings.csp_report_uri.strip():
                    response.headers.setdefault(
                        "Reporting-Endpoints", f'csp-endpoint="{settings.csp_report_uri}"'
                    )
        return response
