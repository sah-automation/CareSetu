"""Request-scoped trace id (PHASE-2 REM T6, ticket #77).

One ``trace_id`` per incoming request, taken from the client's ``X-Request-Id``
when present else minted once, is established before any gateway middleware or
route can answer, and flows through every error envelope and the log lines that
record them (error-handling-observability §3). ``resolve_trace_id`` is the
single read point for both the gateway rejection funnel and the iam error
envelope, so an envelope and its log line can never drift.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_TRACE_HEADER = "x-request-id"
_TRACE_STATE_ATTR = "trace_id"
_MAX_TRACE_ID_LENGTH = 128


def _is_safe_trace_id(trace_id: str) -> bool:
    """A client-supplied id is echoed into log lines and envelopes, so only
    printable non-space tokens up to a sane length are honoured; anything else
    (blank, newlines, tabs, unbounded length) falls back to a minted id
    (error-handling-observability §2 - no log injection, no PHI vector).
    """
    if not trace_id or len(trace_id) > _MAX_TRACE_ID_LENGTH:
        return False
    return all(char.isprintable() and not char.isspace() for char in trace_id)


def resolve_trace_id(request: Request) -> str:
    """The request-scoped trace id, minting one when none is established yet.

    The trace middleware runs before every request reaches a handler, so this
    is normally a read of ``request.state``; the mint is a defensive fallback
    so a handler can never reintroduce the per-call drift this ticket removes.
    """
    trace_id = getattr(request.state, _TRACE_STATE_ATTR, None)
    if not trace_id:
        trace_id = uuid.uuid4().hex
        setattr(request.state, _TRACE_STATE_ATTR, trace_id)
    return trace_id


class TraceMiddleware(BaseHTTPMiddleware):
    """Establish the one request-scoped trace id before any handler runs.

    The client's ``X-Request-Id`` is honoured when present, else a fresh id is
    minted. Registered outermost in the app shell so a rejection from an inner
    gateway middleware (``jwt_verify``, ``rate_limit``) or an iam error handler
    carries the same id the app's logs record for that request.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_trace_id = request.headers.get(_TRACE_HEADER)
        if client_trace_id:
            candidate = client_trace_id.strip()
            if _is_safe_trace_id(candidate):
                request.state.trace_id = candidate
                return await call_next(request)
        resolve_trace_id(request)
        return await call_next(request)
