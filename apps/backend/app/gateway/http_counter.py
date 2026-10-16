"""Per-minute request counting (PHASE-14A B9, #727).

Every ANSWERED request is counted into the in-process per-minute bucket named by
its route template, method and collapsed status class
(:mod:`observability.http_counter`), and a worker folds those buckets into
``observability_http_minute`` off the request path. That is what makes request
throughput and error rate queryable from Postgres - past the free Grafana tier's
fourteen-day retention, at one row per route per minute rather than one write per
request (#717 decision 15).

Registered after ``SecurityHeadersMiddleware`` and so the OUTERMOST of the gateway
stack, which is the position that answers "what did the platform serve" rather than
"what did the router answer". A gateway rejection - the 401 from ``jwt_verify``,
the 429 from ``rate_limit`` - is a served request, and the most operationally
important ones to count, because a 429 storm is precisely the signal a throughput
panel exists to show; an inner registration would silently omit every request the
gateway turned away.

It counts after ``call_next`` rather than before it, because the matched route is
only on the scope once routing has run: ``request.scope["route"]`` holds the route
Starlette picked, and that object's ``path`` is the TEMPLATE
(``/v1/cases/{case_id}``) rather than the concrete path. Counting the concrete path
would put a patient's identifier into a telemetry label and make the label set
unbounded - the same defect decision 13 rules out for the error stream, and the
reason the extractor (:func:`~observability.error_capture.route_template_for`) is
borrowed rather than written a second time, so the two seams cannot drift apart. A
handler decorator could not do this at all: it runs where the route is known but
never sees a request the gateway rejected.

**The one request this middleware cannot see is the one where a handler raised.**
Starlette answers an escaped exception from its ``ServerErrorMiddleware``, which
sits OUTSIDE all user middleware, so the exception propagates past here without a
response ever arriving. That 500 is counted instead by the catch-all seam in
``app/main.py`` - the same two-seam split the error capture uses, and for the same
reason. Counting only here would under-report throughput by exactly the requests
that failed worst, which is the failure mode this ticket exists to prevent: an
error rate that reads zero during a crash loop.

Always on and unconditional, like ``SecurityHeadersMiddleware`` and unlike the
optional observability gates. Two reasons. An unconfigured counter is a silently
blind system, which is the answer an operator must never be handed by default; and
the capture-liveness half of ``/throughput`` can only mean anything if capture
cannot be switched off to make it read as broken. Decision 45's "new configuration
gates, disabled by default" is about the observability FEATURE gates this counter
does not gate - it is an instrument, like the error capture beside it, not a
capability behind a flag.

**What is stored is a COLLAPSED class, never a raw status code.** Four classes
(``2xx``/``3xx``/``4xx``/``5xx``) rather than the three of decision 37, because that
decision's three-way collapse is the COLLECTOR's cardinality firewall (#749) and the
table #726 shipped admits exactly those four in its CHECK constraint - storing three
would be a migration, and this ticket alters no existing table. What decision 37
protects against is reached the same way: the class is resolved BEFORE the bucket key
is built, so ``/v1/cases`` answering 500 then 503 is one series, and the server-error
class alone feeds the stored error numerator.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from observability.http_counter import record_request


class HttpCounterMiddleware(BaseHTTPMiddleware):
    """Count every answered request into its per-minute bucket on the way out.

    The count happens AFTER ``call_next`` rather than before it, because the status
    class and the matched route are both only known once the request has been
    answered - and because a request that is still in flight has not been served
    yet, which is the only thing a throughput figure is allowed to count.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        # One dict increment under a lock: no I/O, no await, no connection. The
        # counter must never be the reason a request is slow, least of all on the
        # 429s this position exists to count.
        record_request(request=request, status_code=response.status_code)
        return response
