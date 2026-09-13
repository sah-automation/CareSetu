"""``rate_limit`` gateway middleware (PHASE-2 T8, ticket #59; REM T8, #78; PS-05, #403).

Enforces the strictest limit on the OTP/auth and intake surfaces
(``NFR-SEC-004``, api-standards §6): the auth endpoints and the patient
intake's media-and-row-writing endpoints are the abuse targets, so only their
paths are counted and capped. The intake GET reads (detail, pre-summary, clip
playback) stay outside the cap - re-fetching a status is not the threat the
tier exists for. Each surface keeps its own strict tier - the intake tier has
its own settings defaulting to the auth tier values (PS-05, #403) - so a burst
on one surface can never exhaust the other's budget and the auth-only limiting
semantics hold unchanged. The limit is a fixed in-memory window keyed per
client IP and per surface - the middleware runs outermost of the gateway pair
(before ``jwt_verify``) so every request counts toward its cap even when the
presented token is unusable. Exceeding a tier answers 429 with ``Retry-After``
and the shared error envelope. In-memory per process by design - the DDoS
layer is the edge (Caddy) and this middleware is the application's own
per-caller abuse brake.
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

#: Per-surface bucket namespace: each strict-tier surface keeps its own
#: per-client-IP budget so unrelated surfaces cannot exhaust each other (PS-05).
_SURFACE_AUTH = "auth"
_SURFACE_INTAKE = "intake"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Cap per-caller requests to the strict-tier surfaces within a fixed window.

    One independent per-client-IP bucket per surface: auth and intake each
    answer 429 once their OWN tier is exhausted, so a spent auth budget never
    blocks an intake write and vice versa (PS-05 ``"auth-only limiting semantics
    still hold"``).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        max_requests: int,
        window_seconds: int,
        auth_path_prefix: str = _DEFAULT_AUTH_PATH_PREFIX,
        intake_max_requests: int | None = None,
        intake_window_seconds: int | None = None,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.auth_path_prefix = auth_path_prefix
        # The intake tier defaults to the auth tier values so the two surfaces
        # are strict by default and only diverge when configured (PS-05).
        self.intake_max_requests = (
            intake_max_requests if intake_max_requests is not None else max_requests
        )
        self.intake_window_seconds = (
            intake_window_seconds if intake_window_seconds is not None else window_seconds
        )
        self._buckets: dict[str, tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)
        surface = self._surface_for(request.url.path)
        if surface is None:
            return await call_next(request)

        max_requests, window_seconds = self._limits_for(surface)
        now = time.monotonic()
        key = f"{surface}:{self._key_for(request)}"
        bucket = self._buckets.get(key)
        if bucket is None or bucket[0] <= now:
            self._buckets[key] = (now + window_seconds, 1)
        elif bucket[1] >= max_requests:
            return error_response(
                status_code=429,
                code=CODE_RATE_LIMIT_EXCEEDED,
                message=MESSAGE_RATE_LIMIT_EXCEEDED,
                request=request,
                headers={"Retry-After": str(window_seconds)},
            )
        else:
            self._buckets[key] = (bucket[0], bucket[1] + 1)

        if len(self._buckets) > _MAX_TRACKED_BUCKETS:
            self._prune(now)

        request.state.gateway_rate_limit_checked = True
        return await call_next(request)

    def _surface_for(self, path: str) -> str | None:
        """The strict-tier surface ``path`` belongs to, if any.

        The auth surface is prefix-matched (``/v1/auth/*``). The intake surface
        is the write trio - ``upload-media``, ``submit``, and the per-intake
        ``re-record`` shape - so the patient's read routes (intake detail,
        pre-summary, clip playback) are never counted: abusing the
        payer-facing writes is the threat, re-fetching a status or a clip is
        not (PS-05, #403).
        """
        if path.startswith(self.auth_path_prefix):
            return _SURFACE_AUTH
        if path in (_INTAKE_UPLOAD_MEDIA_PATH, _INTAKE_SUBMIT_PATH) or (
            path.startswith(_DEFAULT_INTAKE_PATH_PREFIX)
            and path.endswith(_INTAKE_RE_RECORD_PATH_SUFFIX)
        ):
            return _SURFACE_INTAKE
        return None

    def _limits_for(self, surface: str) -> tuple[int, int]:
        """The (max_requests, window_seconds) tier for ``surface``."""
        if surface == _SURFACE_INTAKE:
            return self.intake_max_requests, self.intake_window_seconds
        return self.max_requests, self.window_seconds

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
