"""``rate_limit`` gateway middleware (PHASE-2 T8, ticket #59; REM T8, #78; PS-05, #403).

Enforces the strictest limit on the OTP/auth and intake surfaces
(``NFR-SEC-004``, api-standards §6): the auth endpoints and the patient
intake's media-and-row-writing endpoints are the abuse targets, so only their
paths are counted and capped. The intake GET reads (detail, pre-summary, clip
playback) stay outside the cap - re-fetching a status is not the threat the
tier exists for. The limit is a fixed in-memory window keyed per client IP -
the middleware runs outermost of the gateway pair (before ``jwt_verify``) so
every request counts toward the cap even when the presented token is unusable,
and both surfaces count into one shared per-IP bucket on the same tier.
Exceeding it answers 429 with ``Retry-After`` and the shared error envelope.
In-memory per process by design - the DDoS layer is the edge (Caddy) and this
middleware is the application's own per-caller abuse brake.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.gateway.errors import (
    CODE_RATE_LIMIT_EXCEEDED,
    MESSAGE_RATE_LIMIT_EXCEEDED,
    error_response,
)

_DEFAULT_AUTH_PATH_PREFIX = "/v1/auth/"
# Intake write surface (PS-05, #403): the media-and-row-writing trio that
# uploads and persists on the strict tier. ``upload-media`` and ``submit`` are
# exact paths; ``re-record`` is a per-intake dynamic route, matched by the
# ``/v1/intake/`` prefix plus the ``/re-record`` suffix so the GET read shapes
# (``/{intake_id}``, ``/pre-summary``, ``/media/{id}``) never match.
_DEFAULT_INTAKE_PATH_PREFIX = "/v1/intake/"
_INTAKE_UPLOAD_MEDIA_PATH = f"{_DEFAULT_INTAKE_PATH_PREFIX}upload-media"
_INTAKE_SUBMIT_PATH = f"{_DEFAULT_INTAKE_PATH_PREFIX}submit"
_INTAKE_RE_RECORD_PATH_SUFFIX = "/re-record"
# Upper bound on tracked buckets: once exceeded, stale windows are pruned and,
# if the dict is still over the cap, the oldest live buckets are evicted so an
# attacker spraying many keys cannot grow the dict without bound.
_MAX_TRACKED_BUCKETS = 1024


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Cap per-caller requests to the strict-tier surfaces within a fixed window."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        max_requests: int,
        window_seconds: int,
        auth_path_prefix: str = _DEFAULT_AUTH_PATH_PREFIX,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.auth_path_prefix = auth_path_prefix
        self._buckets: dict[str, tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)
        if not self._is_limited_path(request.url.path):
            return await call_next(request)

        now = time.monotonic()
        key = self._key_for(request)
        bucket = self._buckets.get(key)
        if bucket is None or bucket[0] <= now:
            self._buckets[key] = (now + self.window_seconds, 1)
        elif bucket[1] >= self.max_requests:
            return error_response(
                status_code=429,
                code=CODE_RATE_LIMIT_EXCEEDED,
                message=MESSAGE_RATE_LIMIT_EXCEEDED,
                request=request,
                headers={"Retry-After": str(self.window_seconds)},
            )
        else:
            self._buckets[key] = (bucket[0], bucket[1] + 1)

        if len(self._buckets) > _MAX_TRACKED_BUCKETS:
            self._prune(now)

        request.state.gateway_rate_limit_checked = True
        return await call_next(request)

    def _is_limited_path(self, path: str) -> bool:
        """Whether ``path`` is on the strict-tier surfaces (OTP/auth + intake writes).

        The auth surface is prefix-matched (``/v1/auth/*``). The intake surface
        is the write trio - ``upload-media``, ``submit``, and the per-intake
        ``re-record`` shape - so the patient's read routes (intake detail,
        pre-summary, clip playback) are never counted: abusing the
        payer-facing writes is the threat, re-fetching a status or a clip is
        not (PS-05, #403).
        """
        return (
            path.startswith(self.auth_path_prefix)
            or path in (_INTAKE_UPLOAD_MEDIA_PATH, _INTAKE_SUBMIT_PATH)
            or (
                path.startswith(_DEFAULT_INTAKE_PATH_PREFIX)
                and path.endswith(_INTAKE_RE_RECORD_PATH_SUFFIX)
            )
        )

    def _key_for(self, request: Request) -> str:
        """Per client IP (api-standards §6).

        The limiter runs outermost of the gateway pair (REM T8, #78), before
        ``jwt_verify`` attaches a ``Principal``, so the unauthenticated auth
        surface and the intake writes always key by the caller's IP.
        """
        client = request.client
        return f"ip:{client.host if client is not None else 'unknown'}"

    def _prune(self, now: float) -> None:
        """Keep the bucket dict bounded under a key spray.

        First drop windows that have closed; if the dict is still over the cap,
        evict the oldest live buckets too. Under pressure the limiter forgets
        the oldest tracks rather than grow without bound - the sprayer's
        buckets being evicted is exactly the trade-off that keeps memory flat.
        """
        expired = [key for key, (expires_at, _) in self._buckets.items() if expires_at <= now]
        for key in expired:
            del self._buckets[key]

        over = len(self._buckets) - _MAX_TRACKED_BUCKETS
        if over > 0:
            oldest = sorted(self._buckets, key=lambda key: self._buckets[key][0])[:over]
            for key in oldest:
                del self._buckets[key]
