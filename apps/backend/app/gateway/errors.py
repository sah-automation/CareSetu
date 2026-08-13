"""Gateway rejection envelope and logging (PHASE-2 T8, ticket #59).

The gateway answers every rejection - invalid access token (401),
insufficient RBAC scope (403), and exceeded auth-surface rate limit (429) -
with the shared CareSetu error envelope (api-standards §2). Security
rejections never echo token internals (error-handling-observability §1:
"never return internal detail"), so the messages are fixed, human-safe
strings and the distinguishing cause stays server-side, recorded via the
module logger as a structured ``gateway_rejection`` line carrying the trace
id. ``error_response`` is the single funnel for all three shapes so the log
line and the envelope can never drift.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.gateway.trace import resolve_trace_id

CODE_AUTH_UNAUTHENTICATED = "AUTH_UNAUTHENTICATED"
CODE_AUTH_INSUFFICIENT_SCOPE = "AUTH_INSUFFICIENT_SCOPE"
CODE_RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

MESSAGE_AUTH_UNAUTHENTICATED = "Authentication required; provide a valid access token"
MESSAGE_AUTH_INSUFFICIENT_SCOPE = "Your session does not grant the scope this route requires"
MESSAGE_RATE_LIMIT_EXCEEDED = "Too many requests; retry after the window"

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    """Base for a rejection produced at the gateway."""


class AuthenticationRequiredError(GatewayError):
    """The caller holds no valid session for a route that requires one.

    Raised by the protected-route dependency when the attached ``Principal``
    is anonymous or absent. The middleware itself answers an invalid presented
    token with the same 401 envelope, so one code covers both shapes.
    """


class InsufficientScopeError(GatewayError):
    """The caller is authenticated but lacks the route's required scope.

    Raised by the protected-route dependency when the authenticated
    ``Principal`` does not carry the patient role - e.g. a future partner or
    operator token reaching a patient-only route.
    """


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    request: Request,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """One error envelope for every gateway rejection (api-standards §2).

    Records the rejection as a structured log line keyed by the request-scoped
    trace id the envelope carries - the same id every log line for that request
    uses - so a reported 401/403/429 is reproducible from logs alone
    (error-handling-observability §3). Never logs the token or the caller's raw
    input.
    """
    trace_id = resolve_trace_id(request)
    logger.warning("gateway_rejection code=%s status=%d trace_id=%s", code, status_code, trace_id)
    envelope = {"code": code, "message": message, "trace_id": trace_id, "details": {}}
    return JSONResponse(status_code=status_code, content=envelope, headers=headers)


async def _emit_access_denial(request: Request) -> None:
    """Publish ``patient.auth_failed`` (reason ``access_denied``) for an authenticated 403.

    PHASE-2 REM T7 (#87): an access denial on a protected route becomes
    auditable. The gateway is a thin adapter (spec #51, Implementation Decision
    6) - the iam facade owns the outbox write and resolves the identity's phone
    in its own transaction; only the authenticated ``Principal`` the
    ``jwt_verify`` middleware attached is passed over, never a token. Anonymous
    401s carry no identity to attribute and never reach this call - they stay
    log-only by boundary (``error_response``'s ``gateway_rejection`` line).
    An outbox failure must not turn a denial into a 5xx, so the emission is
    best-effort and the loss is logged (security-phii-standards KPI-006:
    authz failures are 100% audited, so a missed write is an operator signal).
    """
    principal = getattr(request.state, "principal", None)
    if principal is None or not principal.is_authenticated:
        return
    facade = getattr(request.app.state, "iam_facade", None)
    if facade is None:
        logger.error(
            "access_denial_emit_failed trace_id=%s identity=%s: iam facade not attached to the app",
            resolve_trace_id(request),
            principal.subject_id,
        )
        return
    try:
        await facade.emit_access_denied(int(principal.subject_id))
    except Exception:
        logger.exception(
            "access_denial_emit_failed trace_id=%s identity=%s",
            resolve_trace_id(request),
            principal.subject_id,
        )


def register_gateway_error_handlers(app: FastAPI) -> None:
    """Attach the gateway error envelope to the protected-route rejections."""

    async def _authentication_required(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            CODE_AUTH_UNAUTHENTICATED,
            MESSAGE_AUTH_UNAUTHENTICATED,
            request=request,
        )

    async def _insufficient_scope(request: Request, exc: Exception) -> JSONResponse:
        await _emit_access_denial(request)
        return error_response(
            status.HTTP_403_FORBIDDEN,
            CODE_AUTH_INSUFFICIENT_SCOPE,
            MESSAGE_AUTH_INSUFFICIENT_SCOPE,
            request=request,
        )

    app.add_exception_handler(AuthenticationRequiredError, _authentication_required)
    app.add_exception_handler(InsufficientScopeError, _insufficient_scope)
