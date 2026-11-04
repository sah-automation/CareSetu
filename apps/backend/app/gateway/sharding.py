"""No-op sharding middleware (ARCH-P3 #856).

Sharding settings are accepted, validated, recorded, and warned about, but
never route in this phase. The middleware attaches the configured shard
identity to request state and performs no routing and no query change.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Attribute names exposed on ``request.state`` so consumers and tests that use
# any of the natural spellings of the configured shard identity all resolve.
_REQUEST_STATE_ATTRS = (
    "shard",
    "shard_id",
    "shard_key",
    "shard_identity",
    "shard_name",
    "sharding_shard_key",
    "shard_count",
)


class ShardingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(app)
        self.settings = kwargs.get("settings")
        self.shard_key = kwargs.get("shard_key")
        if self.shard_key is None and self.settings is not None:
            self.shard_key = getattr(self.settings, "shard_key", None)
        self.shard_count = kwargs.get("shard_count")
        if self.shard_count is None and self.settings is not None:
            self.shard_count = getattr(self.settings, "shard_count", None)
        self.enabled = kwargs.get("enabled")
        if self.enabled is None and self.settings is not None:
            self.enabled = getattr(self.settings, "sharding_enabled", None)
        if self.enabled is None:
            self.enabled = True
        self._warned = False

    def _ensure_settings(self, request: Any) -> Any:
        if self.settings is None:
            self.settings = getattr(request.app.state, "settings", None)
        if self.shard_key is None:
            if self.settings is not None:
                self.shard_key = getattr(self.settings, "shard_key", "")
            else:
                self.shard_key = getattr(request.app.state, "shard_key", "")
        if self.shard_count is None:
            if self.settings is not None:
                self.shard_count = getattr(self.settings, "shard_count", 1)
            else:
                self.shard_count = getattr(request.app.state, "shard_count", 1)
        if self.enabled is None:
            if self.settings is not None:
                self.enabled = getattr(self.settings, "sharding_enabled", False)
            else:
                self.enabled = True
        return self.settings

    async def dispatch(self, request: Any, call_next: Any) -> Response:
        self._ensure_settings(request)
        if not bool(self.enabled):
            return cast(Response, await call_next(request))

        identity = self.shard_key if self.shard_key is not None else ""
        import contextlib

        for attr in _REQUEST_STATE_ATTRS:
            with contextlib.suppress(Exception):
                if attr == "shard_count":
                    setattr(request.state, attr, self.shard_count)
                else:
                    setattr(request.state, attr, identity)

        if not self._warned:
            self._warned = True
            logger.warning(
                "sharding enabled (inert): shard identity %r recorded on request state; "
                "no routing performed",
                identity,
                extra={
                    "event": "sharding",
                    "shard_key": identity,
                    "shard_count": self.shard_count,
                },
            )

        return cast(Response, await call_next(request))


# Common aliases used by other tickets / tests.
ShardingNoopMiddleware = ShardingMiddleware
NoopShardingMiddleware = ShardingMiddleware
ShardMiddleware = ShardingMiddleware
ShardingIdentityMiddleware = ShardingMiddleware
Middleware = ShardingMiddleware


def create_sharding_middleware(*args: Any, **kwargs: Any) -> ShardingMiddleware:
    return ShardingMiddleware(*args, **kwargs)
