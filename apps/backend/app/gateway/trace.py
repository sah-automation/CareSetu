"""Request-scoped trace id (PHASE-2 REM T6, ticket #77).

One ``trace_id`` per incoming request, taken from the client's ``X-Request-Id``
when present else minted once, is established before any gateway middleware or
route can answer, and flows through every error envelope and the log lines that
record them (error-handling-observability §3). ``resolve_trace_id`` is the
single read point for both the gateway rejection funnel and the iam error
envelope, so an envelope and its log line can never drift.

A client-supplied id is honoured only when it is an identifier this platform can
store and link (see ``observability.trace_ids``); anything else falls back to a
minted id. The rule is shared with the deep-link builder, so a stored id and
the link built from it can never disagree.

Since PHASE-14A B8 (#726) this middleware is also where a server-error
RESPONSE is captured into the bounded in-process error buffer. An exception that
escapes every module handler is captured on the other side instead, by the
catch-all seam in ``app/main.py`` - Starlette runs a registered ``Exception``
handler in its ``ServerErrorMiddleware``, which sits OUTSIDE all user middleware,
so an exception never comes back through here and the two seams cannot double
capture the same failure. What reaches ``call_next`` instead is a 5xx a handler
produced deliberately, and that is the half of the error feed the exception seam
cannot see.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from observability.error_capture import ERROR_KIND_SERVER_ERROR_RESPONSE, capture_server_error
from observability.logging import reset_trace_id, set_trace_id
from observability.trace_ids import normalize_trace_id

_TRACE_HEADER = "x-request-id"
_TRACE_STATE_ATTR = "trace_id"


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
    minted. Registered inside the TEST-B2 security-posture headers middleware
    (which wraps it), so a rejection from an inner gateway middleware
    (``jwt_verify``, ``rate_limit``) or an iam error handler carries the same
    id the app's logs record for that request - and the response still gets
    the NFR-SEC-001 headers on the way back out.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_trace_id = request.headers.get(_TRACE_HEADER)
        if client_trace_id:
            # #757: the client's id is honoured only when it is an identifier this
            # platform can STORE and LINK - printable ASCII, no whitespace, no URL
            # separator, at most the column's width. A longer value would reach
            # the product ledger unclamped and wedge its write; a value carrying a
            # separator would reach a deep link the builder refuses. Anything else
            # falls back to a minted id, and the request is unaffected.
            candidate = normalize_trace_id(client_trace_id)
            if candidate is not None:
                request.state.trace_id = candidate
        # Resolved ONCE and reused by the capture below: ``resolve_trace_id`` reads
        # ``request.state`` after the first call, so a second call is a redundant
        # read, and one local is the cheaper way to say "this request's id".
        trace_id = resolve_trace_id(request)
        # PHASE-14A A1 (#694): bind the one request-scoped id into the logging
        # context so every log line emitted while this request is in flight -
        # across the gateway, routes, and module facades - carries it.
        token = set_trace_id(trace_id)
        try:
            response = await call_next(request)
        finally:
            reset_trace_id(token)
        # PHASE-14A B8 (#726): a 5xx the handler produced itself is captured here,
        # outside the trace-reset above so the record still carries this request's
        # id. One integer comparison on the way out of every request; the capture
        # itself only runs for a failure, and it buffers rather than writes.
        if response.status_code >= 500:
            capture_server_error(
                request=request,
                status_code=response.status_code,
                kind=ERROR_KIND_SERVER_ERROR_RESPONSE,
                # No envelope code: reading one would mean consuming the response
                # stream this middleware exists to hand back. The route template,
                # method and status already identify the failure, and ``kind`` is
                # what keeps it separate from an escaped exception in the feed.
                code="",
                trace_id=trace_id,
            )
        return response
