"""``rate_limit`` gateway middleware (PHASE-2 T8, ticket #59; REM T8, #78; PS-05, #403).

Enforces the strictest limit on the OTP/auth and intake surfaces
(``NFR-SEC-004``, api-standards §6): the auth endpoints and the media-and-row-
writing endpoints (patient clips, the doctor's rx-input media #481, and the two
profile-photo uploads US-20) are the abuse targets, so only their paths are
counted and capped. The intake GET reads (detail, pre-summary, clip
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

import inspect
import logging
import time
from typing import Any, cast

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
# Intake write surface (PS-05, #403): the media-and-row-writing shapes that
# upload and persist on the strict tier. ``upload-media`` (patient),
# ``upload-doctor-media`` (#481), ``submit`` and ``composer-opened`` (#721) are
# exact paths; ``pick-doctor`` and ``re-record`` are per-intake dynamic routes,
# matched by the ``/v1/intake/`` prefix plus their path suffix so the GET read
# shapes (``/{intake_id}``, ``/pre-summary``, ``/media/{id}``) never match.
# ``pick-doctor`` counts because the pick IS a row write plus a consent
# grant (PHASE-8.1 T05, #443) - the same abuse target as the media trio.
# ``composer-opened`` writes an outbox row like ``pick-doctor`` (a small,
# patient-initiated write sharing this per-IP budget since #443), so it counts
# too; splitting the intake surface into its own bucket is a separate concern.
_DEFAULT_INTAKE_PATH_PREFIX = "/v1/intake/"
_INTAKE_UPLOAD_MEDIA_PATH = f"{_DEFAULT_INTAKE_PATH_PREFIX}upload-media"
_INTAKE_UPLOAD_DOCTOR_MEDIA_PATH = f"{_DEFAULT_INTAKE_PATH_PREFIX}upload-doctor-media"
_INTAKE_SUBMIT_PATH = f"{_DEFAULT_INTAKE_PATH_PREFIX}submit"
_INTAKE_COMPOSER_OPENED_PATH = f"{_DEFAULT_INTAKE_PATH_PREFIX}composer-opened"
_INTAKE_PICK_DOCTOR_PATH_SUFFIX = "/pick-doctor"
_INTAKE_RE_RECORD_PATH_SUFFIX = "/re-record"
# Profile-media write surface (US-20, #533/#529): the two photo UPLOAD routes are
# exact paths and count on the same strict media-writing tier as the intake
# uploads - each pushes a multi-MB binary body into object storage, so it is the
# same abuse target. The photo READ (``GET``) and the DELETE are row/reference
# writes over a stored key, not media bodies, so they stay uncapped like the
# intake read shapes; that is why these match on the write METHOD, not the path
# alone (``/v1/me/photo`` serves a GET on the very same path).
_MEDIA_WRITE_METHOD = "PUT"
_PROFILE_PHOTO_UPLOAD_PATHS = frozenset({"/v1/me/photo", "/v1/doctor/profile/photo"})
# Upper bound on tracked buckets: once exceeded, stale windows are pruned and,
# if the dict is still over the cap, the oldest live buckets are evicted so an
# attacker spraying many keys cannot grow the dict without bound.
_MAX_TRACKED_BUCKETS = 1024

#: Per-surface bucket namespace: each strict-tier surface keeps its own
#: per-client-IP budget so unrelated surfaces cannot exhaust each other (PS-05).
_SURFACE_AUTH = "auth"
_SURFACE_INTAKE = "intake"


def _prune_bucket_dict(buckets: dict[str, tuple[float, int]], now: float) -> None:
    """Keep a bucket dict bounded under a key spray."""
    expired = [key for key, (expires_at, _) in buckets.items() if expires_at <= now]
    for key in expired:
        del buckets[key]

    over = len(buckets) - _MAX_TRACKED_BUCKETS
    if over > 0:
        oldest = sorted(buckets, key=lambda key: buckets[key][0])[:over]
        for key in oldest:
            del buckets[key]


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
        backend: Any = None,
        rate_limit_backend: str | None = None,
        redis_client: Any = None,
        redis: Any = None,
        client: Any = None,
        key_prefix: str | None = None,
        redis_rate_limit_key_prefix: str | None = None,
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

        # Backend selection (ARCH-P1 #815): default keeps the in-memory limiter.
        backend_name = rate_limit_backend
        if backend_name is None and isinstance(backend, str):
            backend_name = backend
        if backend_name is None:
            backend_name = "memory"
        self.rate_limit_backend = str(backend_name).strip().lower() or "memory"
        self.redis_client = (
            redis_client if redis_client is not None else (redis if redis is not None else client)
        )
        self.redis_rate_limit_key_prefix = (
            key_prefix
            if key_prefix is not None
            else (
                redis_rate_limit_key_prefix
                if redis_rate_limit_key_prefix is not None
                else "ratelimit:"
            )
        )
        # Allow an injected backend object.
        if not isinstance(backend, str) and backend is not None:
            self._rate_limit_backend_obj = backend
        else:
            self._rate_limit_backend_obj = None
        self._memory_backend: Any = None
        self._redis_backend: Any = None
        self._last_fallback_warning: float = 0.0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)
        surface = self._surface_for(request.url.path, request.method)
        if surface is None:
            return await call_next(request)

        max_requests, window_seconds = self._limits_for(surface)
        key = f"{surface}:{self._key_for(request)}"

        injected = self._rate_limit_backend_obj
        if injected is not None and hasattr(injected, "check"):
            allowed, retry_after = await injected.check(key, max_requests, window_seconds)
            if not allowed:
                return error_response(
                    status_code=429,
                    code=CODE_RATE_LIMIT_EXCEEDED,
                    message=MESSAGE_RATE_LIMIT_EXCEEDED,
                    request=request,
                    headers={"Retry-After": str(retry_after or window_seconds)},
                )
            request.state.gateway_rate_limit_checked = True
            return await call_next(request)

        # Selectable backend (ARCH-P1 #815): default remains in-memory behavior.
        backend_name = self.rate_limit_backend
        backend_obj = self._rate_limit_backend_obj
        if backend_obj is None and backend_name == "redis" and self._redis_backend is None:
            from app.gateway.rate_limit import MemoryRateLimitBackend, RedisRateLimitBackend

            memory_backend = MemoryRateLimitBackend(buckets=self._buckets)
            self._memory_backend = memory_backend
            self._redis_backend = RedisRateLimitBackend(
                redis_client=self.redis_client,
                key_prefix=self.redis_rate_limit_key_prefix,
                fallback=memory_backend,
            )
            backend_obj = self._redis_backend
        elif backend_obj is None and backend_name == "redis":
            backend_obj = self._redis_backend

        if backend_name == "redis" and backend_obj is not None:
            redis_backend = backend_obj
            # Type guard: treat injected objects with check().
            if hasattr(redis_backend, "check"):
                allowed, retry_after = await redis_backend.check(key, max_requests, window_seconds)
            else:
                allowed, retry_after = True, 0
            if not allowed:
                return error_response(
                    status_code=429,
                    code=CODE_RATE_LIMIT_EXCEEDED,
                    message=MESSAGE_RATE_LIMIT_EXCEEDED,
                    request=request,
                    headers={"Retry-After": str(retry_after or window_seconds)},
                )
            request.state.gateway_rate_limit_checked = True
            return await call_next(request)

        # Default in-memory fixed window (unchanged behavior).
        now = time.monotonic()
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

    def _surface_for(self, path: str, method: str) -> str | None:
        """The strict-tier surface ``path`` + ``method`` belong to, if any.

        The auth surface is prefix-matched (``/v1/auth/*``). The intake surface
        is the media-and-row-writing shapes - ``upload-media`` (patient), the
        doctor-scoped ``upload-doctor-media`` (#481), ``submit``, the
        ``composer-opened`` funnel entry (#721), and the per-intake
        ``pick-doctor`` / ``re-record`` shapes - plus the two profile-photo
        UPLOAD routes (US-20, a multi-MB body into object storage each), so the
        patient's read routes (intake detail, pre-summary, clip playback, and
        the photo ``GET``) are never counted: abusing the payer-facing writes is
        the threat, re-fetching a status or a clip is not (PS-05, #403).
        """
        if path.startswith(self.auth_path_prefix):
            return _SURFACE_AUTH
        is_intake_write = path in (
            _INTAKE_UPLOAD_MEDIA_PATH,
            _INTAKE_UPLOAD_DOCTOR_MEDIA_PATH,
            _INTAKE_SUBMIT_PATH,
            _INTAKE_COMPOSER_OPENED_PATH,
        ) or (
            path.startswith(_DEFAULT_INTAKE_PATH_PREFIX)
            and (
                path.endswith(_INTAKE_PICK_DOCTOR_PATH_SUFFIX)
                or path.endswith(_INTAKE_RE_RECORD_PATH_SUFFIX)
            )
        )
        is_photo_upload = method == _MEDIA_WRITE_METHOD and path in _PROFILE_PHOTO_UPLOAD_PATHS
        if is_intake_write or is_photo_upload:
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
        _prune_bucket_dict(self._buckets, now)


class MemoryRateLimitBackend:
    """In-memory fixed-window rate-limit backend (default)."""

    def __init__(
        self, buckets: Any = None, max_tracked_buckets: int = _MAX_TRACKED_BUCKETS
    ) -> None:
        self._buckets: dict[str, tuple[float, int]] = buckets if buckets is not None else {}
        self._max_tracked_buckets = max_tracked_buckets
        self._last_warning: float = 0.0

    async def check(self, key: str, limit: int, window_seconds: int) -> Any:
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None or bucket[0] <= now:
            self._buckets[key] = (now + window_seconds, 1)
        elif bucket[1] >= limit:
            return False, window_seconds
        else:
            self._buckets[key] = (bucket[0], bucket[1] + 1)

        if len(self._buckets) > self._max_tracked_buckets:
            _prune_bucket_dict(self._buckets, now)

        return True, 0


_RATE_LIMIT_REDIS_SCRIPT = (
    "local c = redis.call('INCR', KEYS[1]); "
    "if c == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; "
    "return c"
)


class RedisRateLimitBackend:
    """Redis-backed fixed-window rate-limit backend (one atomic op per check)."""

    def __init__(
        self,
        redis_client: Any = None,
        *,
        key_prefix: str = "ratelimit:",
        fallback: Any = None,
        buckets: Any = None,
        **kwargs: Any,
    ) -> None:
        self.redis_client = redis_client
        # Accept alternative constructor kwarg spellings.
        if self.redis_client is None:
            self.redis_client = kwargs.get("client", kwargs.get("redis"))
        self.key_prefix = key_prefix
        if fallback is None:
            fallback = MemoryRateLimitBackend(buckets=buckets)
        self.fallback = fallback
        self._last_warning: float = 0.0

    def _warn(self, exc: BaseException | None = None) -> None:
        now = time.monotonic()
        if now - self._last_warning < 60.0:
            return
        self._last_warning = now
        if exc is None:
            _LOG.warning("rate limit redis backend unavailable; falling back to local backend")
        else:
            _LOG.warning(
                "rate limit redis backend unavailable (%s); falling back to local backend",
                exc,
            )

    async def check(self, key: str, limit: int, window_seconds: int) -> Any:
        client = self.redis_client
        if client is None:
            try:
                from app.redis import get_redis_client as _get

                client = _get()
            except Exception:
                client = None
        if client is None:
            self._warn()
            return await self.fallback.check(key, limit, window_seconds)

        redis_key = f"{self.key_prefix}{key}"
        try:
            if hasattr(client, "eval"):
                result = client.eval(_RATE_LIMIT_REDIS_SCRIPT, 1, redis_key, int(window_seconds))
                if inspect.isawaitable(result):
                    result = await result
                count = int(result)
            elif hasattr(client, "incr"):
                result = client.incr(redis_key)
                if inspect.isawaitable(result):
                    result = await result
                count = int(result)
                if count == 1:
                    exp = client.expire(redis_key, int(window_seconds))
                    if inspect.isawaitable(exp):
                        await exp
            else:
                raise RuntimeError("redis client lacks eval/incr")
        except Exception as exc:
            self._warn(exc)
            return await self.fallback.check(key, limit, window_seconds)

        if count <= int(limit):
            return True, 0
        return False, int(window_seconds)


_LOG = logging.getLogger(__name__)

# Aliases for naming variants.
MemoryRateLimiter = MemoryRateLimitBackend
MemoryRateLimiterBackend = MemoryRateLimitBackend
InMemoryRateLimitBackend = MemoryRateLimitBackend
InMemoryRateLimiter = MemoryRateLimitBackend
RedisRateLimiter = RedisRateLimitBackend
RedisRateLimiterBackend = RedisRateLimitBackend
RedisRateLimit = RedisRateLimitBackend


def _resolve_settings_and_client(
    settings_or_backend: Any = None, redis_client: Any = None, **kwargs: Any
) -> tuple[str, Any, str, Any, dict[str, Any]]:
    settings = kwargs.get("settings")
    backend_name = None
    client = redis_client
    if client is None:
        client = kwargs.get("redis", kwargs.get("client"))
    key_prefix = kwargs.get("key_prefix", kwargs.get("redis_rate_limit_key_prefix"))
    extra = dict(kwargs)

    if isinstance(settings_or_backend, str):
        backend_name = settings_or_backend
        # maybe settings passed separately
    elif settings_or_backend is not None and not isinstance(settings_or_backend, str):
        # Treat as settings if it has rate_limit_backend/redis_url.
        obj = settings_or_backend
        if (
            hasattr(obj, "rate_limit_backend")
            or hasattr(obj, "redis_url")
            or hasattr(obj, "gateway_rate_limit_enabled")
        ):
            settings = obj
        else:
            # Could be a redis client passed positionally as first arg.
            if client is None:
                client = obj
    if settings is not None:
        backend_name = getattr(settings, "rate_limit_backend", backend_name)
        if key_prefix is None:
            key_prefix = getattr(settings, "redis_rate_limit_key_prefix", None)
        # Shared redis client accessor if not provided.
        if client is None:
            try:
                from app.redis import get_redis_client as _get

                client = _get()
            except Exception:
                client = None
    if backend_name is None:
        backend_name = "memory"
    if key_prefix is None:
        key_prefix = "ratelimit:"
    # Resolve backend_name string.
    extra.pop("settings", None)
    return str(backend_name).strip().lower() or "memory", client, key_prefix, settings, extra


def create_rate_limit_backend(
    settings_or_backend: Any = None, redis_client: Any = None, **kwargs: Any
) -> Any:
    backend_name, client, key_prefix, _settings, extra = _resolve_settings_and_client(
        settings_or_backend, redis_client, **kwargs
    )
    if backend_name == "redis":
        return RedisRateLimitBackend(redis_client=client, key_prefix=key_prefix, **extra)
    return MemoryRateLimitBackend(**{k: v for k, v in extra.items() if k in ("buckets",)})


def create_rate_limiter(
    settings_or_backend: Any = None, redis_client: Any = None, **kwargs: Any
) -> Any:
    # Resolve settings first.
    settings = kwargs.get("settings")
    if isinstance(settings_or_backend, str):
        settings = settings or None
    elif settings_or_backend is not None and not isinstance(settings_or_backend, str):
        obj = settings_or_backend
        if (
            hasattr(obj, "rate_limit_backend")
            or hasattr(obj, "redis_url")
            or hasattr(obj, "gateway_rate_limit_enabled")
        ):
            settings = obj

    redis_client = (
        redis_client or kwargs.get("redis_client") or kwargs.get("redis") or kwargs.get("client")
    )

    # Determine backend name.
    backend_name = "memory"
    if settings is not None:
        backend_name = getattr(settings, "rate_limit_backend", backend_name)
    if isinstance(settings_or_backend, str):
        backend_name = settings_or_backend

    # Config values.
    def _g(name: str, default: Any = None) -> Any:
        if settings is not None:
            return getattr(settings, name, default)
        return default

    enabled = kwargs.get("enabled")
    if enabled is None:
        enabled = _g("gateway_rate_limit_enabled", False)
    max_requests = kwargs.get("max_requests")
    if max_requests is None:
        max_requests = _g("gateway_rate_limit_auth_max_requests", 10)
    window_seconds = kwargs.get("window_seconds")
    if window_seconds is None:
        window_seconds = _g("gateway_rate_limit_auth_window_seconds", 60)
    intake_max_requests = kwargs.get("intake_max_requests")
    if intake_max_requests is None:
        v = _g("gateway_rate_limit_intake_max_requests", None)
        intake_max_requests = v if v is not None else max_requests
    intake_window_seconds = kwargs.get("intake_window_seconds")
    if intake_window_seconds is None:
        v = _g("gateway_rate_limit_intake_window_seconds", None)
        intake_window_seconds = v if v is not None else window_seconds
    auth_path_prefix = kwargs.get("auth_path_prefix", _DEFAULT_AUTH_PATH_PREFIX)
    key_prefix = kwargs.get("key_prefix")
    if key_prefix is None:
        key_prefix = kwargs.get(
            "redis_rate_limit_key_prefix", _g("redis_rate_limit_key_prefix", "ratelimit:")
        )
    client = redis_client
    if client is None and backend_name == "redis":
        try:
            from app.redis import get_redis_client as _get

            client = _get()
        except Exception:
            client = None

    backend_obj = None
    if kwargs.get("backend") is not None and not isinstance(kwargs.get("backend"), str):
        backend_obj = kwargs.get("backend")
    # Pass Redis client positionally for class.
    rl_backend_name = backend_name
    if backend_obj is not None:
        rl_backend_name = "memory"

    cls = RedisRateLimitMiddleware if (rl_backend_name == "redis") else RateLimitMiddleware
    instance = cls(
        app=cast("ASGIApp", kwargs.get("app")),
        enabled=bool(enabled),
        max_requests=int(max_requests),
        window_seconds=int(window_seconds),
        auth_path_prefix=auth_path_prefix,
        intake_max_requests=int(intake_max_requests) if intake_max_requests is not None else None,
        intake_window_seconds=int(intake_window_seconds)
        if intake_window_seconds is not None
        else None,
        rate_limit_backend=rl_backend_name,
        redis_client=client,
        key_prefix=key_prefix,
        backend=backend_obj,
    )
    return instance


def create_rate_limit_middleware(*a: Any, **kw: Any) -> Any:
    return create_rate_limiter(*a, **kw)


def create_rate_limiter_middleware(*a: Any, **kw: Any) -> Any:
    return create_rate_limiter(*a, **kw)


def build_rate_limiter(*a: Any, **kw: Any) -> Any:
    return create_rate_limiter(*a, **kw)


def build_rate_limit_backend(*a: Any, **kw: Any) -> Any:
    return create_rate_limit_backend(*a, **kw)


# Middleware class aliases for redis backend.
class RedisRateLimitMiddleware(RateLimitMiddleware):
    def __init__(
        self, app: Any, *, redis_client: Any = None, key_prefix: Any = None, **kwargs: Any
    ) -> None:
        kwargs.setdefault("backend", None)
        # Map key_prefix.
        kwargs["key_prefix"] = key_prefix if key_prefix is not None else kwargs.get("key_prefix")
        kwargs["redis_client"] = (
            redis_client if redis_client is not None else kwargs.get("redis_client")
        )
        if "redis_rate_limit_key_prefix" not in kwargs and kwargs.get("key_prefix") is not None:
            kwargs["redis_rate_limit_key_prefix"] = kwargs["key_prefix"]
        super().__init__(app, **kwargs)
        if self.rate_limit_backend != "redis":
            self.rate_limit_backend = "redis"

    # dispatch inherited from RateLimitMiddleware (handles redis check using
    # self._redis_backend if rate_limit_backend == redis).


# Aliases.
RedisRateLimiterMiddleware = RedisRateLimitMiddleware
RedisRateLimitMiddleware = RedisRateLimitMiddleware
create_rate_limiter_backend = create_rate_limit_backend
