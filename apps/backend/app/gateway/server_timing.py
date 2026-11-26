"""Opt-in server-processing timing header (issue #901, the latency feedback loop).

One response header - ``Server-Timing: caresetu_tstmp;dur=<ms>`` - that tells
the latency probe (``scripts/measure_backend_latency.py``, issue #901) how
many of a request's milliseconds the server spent processing. Total round
trip minus this figure is the network leg, so a slow link and a slow server
stop looking identical (issue #901 user story 3).

Registered OUTERMOST of the user middleware stack (after the HTTP counter),
so the measured window covers the whole served request: a gateway rejection -
the 401 from ``jwt_verify``, the 429 from ``rate_limit`` - is timed like any
other answer, which is exactly the shape the probe measures from outside.
The one response this middleware cannot see is the 500 Starlette answers
from its own ``ServerErrorMiddleware``, outside all user middleware.

Debug-only by design (issue #901 user story 7): the whole instrumentation
carries the ``caresetu_tstmp`` tag and the ``SERVER_TIMING_HEADER_ENABLED``
flag, so removing it is a single grep. Gated on
``Settings.server_timing_header_enabled`` - default ON in dev/test, OFF in
production (``from_settings`` resolves the env-dependent default) - and with
the gate off the middleware is not installed at all, so a deployment that did
not opt in pays no per-request cost. Developer-facing only, never a telemetry
source: OTel's request-latency histograms (``METRICS_ENABLED``) are the
server-side telemetry path.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

#: The single-grep cleanup tag for the whole latency harness (issue #901).
SERVER_TIMING_TAG = "caresetu_tstmp"

_SERVER_TIMING_HEADER = "Server-Timing"


class ServerTimingMiddleware(BaseHTTPMiddleware):
    """Stamp server processing milliseconds onto every answered response.

    The clock runs from middleware entry (before any gateway middleware or
    route) until the response headers are ready to hand back - the TTFB a
    client experiences from this app, minus the network. Set (not
    ``setdefault``): this middleware owns the header's value.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response.headers[_SERVER_TIMING_HEADER] = f"{SERVER_TIMING_TAG};dur={elapsed_ms:.1f}"
        return response
