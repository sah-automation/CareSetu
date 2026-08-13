"""``jwt_verify`` gateway middleware (PHASE-2 T8, ticket #59).

The Phase 1 accept-all test-header stub becomes real JWT verification behind
the settled ``Principal`` seam (spec #51 Implementation Decision 8). When
enabled the middleware reads the ``Authorization: Bearer <access-jwt>``
header, verifies the token through the iam facade's ``validate_token`` (a
stateless signature + expiry check, p95 < 100 ms), and attaches a typed
``Principal`` carrying the resolved RBAC scope. A request with no
``Authorization`` header yields an anonymous principal (public auth routes
still work); a request that *presents* a malformed, expired, unsigned, or
wrongly-signed token is denied with a 401 envelope - there is no accept-all
fallback that silently downgrades a bad token to anonymous.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.gateway.errors import (
    CODE_AUTH_UNAUTHENTICATED,
    MESSAGE_AUTH_UNAUTHENTICATED,
    error_response,
)
from app.gateway.principal import Principal
from app.gateway.rbac import resolve_scope_roles
from modules.iam.domain.exceptions import InvalidAccessTokenError
from modules.iam.facade import ValidatedAccessToken

TokenValidator = Callable[[str], Awaitable[ValidatedAccessToken]]


class JWTVerifyMiddleware(BaseHTTPMiddleware):
    """Verify the presented access JWT and attach a scoped ``Principal``."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool,
        validate_token: TokenValidator,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.validate_token = validate_token

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled:
            return await call_next(request)

        header = request.headers.get("authorization")
        if header is None:
            request.state.principal = Principal.anonymous()
            return await call_next(request)

        token = _parse_bearer(header)
        if token is None:
            return await _deny_unauthenticated(request)

        try:
            validated = await self.validate_token(token)
        except InvalidAccessTokenError:
            return await _deny_unauthenticated(request)

        request.state.principal = Principal.for_subject(
            str(validated.subject_id), *resolve_scope_roles(validated.scope)
        )
        return await call_next(request)


def _parse_bearer(header: str) -> str | None:
    """The Bearer token when ``header`` is a well-formed ``Bearer`` scheme.

    ``None`` means the header is present but not a valid ``Bearer`` value; the
    caller presented credentials the gateway cannot use, so it must be denied -
    never silently treated as anonymous (no accept-all fallback).
    """
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def _deny_unauthenticated(request: Request) -> Response:
    """One 401 envelope for every presented-but-unusable token.

    The rejected token's exact cause (expired vs malformed vs unsigned vs
    wrong signature) stays server-side per the security error taxonomy; the
    envelope message is fixed and human-safe, and the log line carries the
    request-scoped trace id (error-handling-observability §1).
    """
    return error_response(
        status_code=401,
        code=CODE_AUTH_UNAUTHENTICATED,
        message=MESSAGE_AUTH_UNAUTHENTICATED,
        request=request,
    )
