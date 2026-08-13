"""``rate_limit`` gateway middleware (PHASE-2 T8, ticket #59).

Enforces the strictest limit on the OTP/auth surface (``NFR-SEC-004``,
api-standards §6): the auth endpoints are the abuse target, so only their path
prefix is counted and capped. The limit is a fixed in-memory window keyed per
identity when the gateway attached an authenticated ``Principal``, else per
client IP; exceeding it answers 429 with ``Retry-After`` and the shared error
envelope. In-memory per process by design - the DDoS layer is the edge (Caddy)
and this middleware is the application's own per-caller abuse brake.
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
from app.gateway.principal import Principal

_DEFAULT_AUTH_PATH_PREFIX = "/v1/auth/"
# Upper bound on tracked buckets: once exceeded, stale windows are pruned and,
# if the dict is still over the cap, the oldest live buckets are evicted so an
# attacker spraying many keys cannot grow the dict without bound.
_MAX_TRACKED_BUCKETS = 1024


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Cap per-caller requests to the auth surface within a fixed window."""

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
        if not request.url.path.startswith(self.auth_path_prefix):
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

    def _key_for(self, request: Request) -> str:
        """Per-identity when authenticated, else per client IP (api-standards §6)."""
        principal: Principal | None = getattr(request.state, "principal", None)
        if principal is not None and principal.is_authenticated:
            return f"identity:{principal.subject_id}"
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
