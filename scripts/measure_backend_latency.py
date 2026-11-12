"""LAT-HARNESS (#901): reproducible backend request latency probe.

One command that quantifies backend request latency instead of guessing: it
runs N requests per endpoint against a base URL, reports the p50/p95/min/max
per endpoint in a table, and exits non-zero when an endpoint's p95 breaches a
threshold. The latency tickets (#902, #903, #904) cite this probe's exit code
as their before/after verification gate.

Usage:

    node scripts/py.cjs scripts/measure_backend_latency.py \\
        --backend-url http://localhost:8000 --iterations 10

    npm run check:latency -- --backend-url https://<render>.onrender.com

Endpoints default to ``/health`` (unauthenticated) plus ``/v1/me`` and
``/v1/me/profile`` (representative authenticated patient reads).
``--endpoint`` (repeatable) replaces the list.
Every non-``/health`` endpoint needs a bearer token; when ``--token`` (or the
``LATENCY_PROBE_TOKEN`` environment variable) is not supplied, the probe
mints one through the demo login flow: register a phone -> read the mock OTP
back through ``GET /v1/auth/dev/otp`` -> verify -> ``POST /v1/auth/session``.
The read-back is only answerable when the backend runs the mock SMS provider
in a dev/test environment (or under ``DEMO_MODE=true``); against a deployment
without it, pass ``--token`` explicitly. The demo phone is randomized per run
so back-to-back probe runs never collide with the 60 s resend cooldown or the
per-phone lockout counter; ``--phone`` pins it when wanted.

Attribution (user story 3): when the backend answers with the opt-in server
timing header (``Server-Timing: caresetu_tstmp;dur=<ms>``, gated by
``SERVER_TIMING_HEADER_ENABLED``, default on in dev/test and off in
production), the table adds a server-processing p95 column. Total minus
server is the network round trip, so a slow link and a slow server stop
looking identical. The header is developer-facing debug only - never a
telemetry source (OTel's request histograms serve that).

Verdict (user story 4): an endpoint passes when every response was 2xx AND
its p95 is at or under the threshold. A probe that measured a fast 401 would
be a false pass, so non-2xx answers fail the endpoint.

Exit codes: 0 all endpoints pass, 1 at least one endpoint breached the
threshold (or answered non-2xx), 2 the harness itself could not run
(connection refused, login failure). Stdlib-only like the other gate scripts.

Cleanup (user story 7): every piece of this instrumentation carries the
``caresetu_tstmp`` tag and the ``SERVER_TIMING_HEADER_ENABLED`` flag - a
single grep for either finds everything to remove.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_ITERATIONS = 10
DEFAULT_P95_THRESHOLD_MS = 1000.0
DEFAULT_ENDPOINTS: tuple[str, ...] = ("/health", "/v1/me", "/v1/me/profile")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0

#: The single-grep cleanup tag shared by this probe and the backend's opt-in
#: server-timing middleware (issue #901 user story 7).
SERVER_TIMING_TAG = "caresetu_tstmp"
SERVER_TIMING_HEADER = "Server-Timing"

#: The one unauthenticated default endpoint; everything else gets a bearer.
HEALTH_ENDPOINT = "/health"

_REGISTER_TIMEOUT_SECONDS = 15.0
_MAX_REGISTER_ATTEMPTS = 3
_COOLDOWN_FALLBACK_SECONDS = 60

EXIT_OK = 0
EXIT_BREACH = 1
EXIT_HARNESS_ERROR = 2


class ProbeError(Exception):
    """The harness itself cannot run (connection, login); not a latency verdict."""


def percentile(samples: Sequence[float], fraction: float) -> float | None:
    """The ``fraction`` percentile of a sample, linear between closest ranks.

    The same rank convention as the observability rollup's ``percentile`` so a
    probe figure and a dashboard figure never disagree about the same samples.
    ``None`` for an empty sample.
    """
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be within [0, 1], got {fraction}")
    if not samples:
        return None
    ordered = sorted(samples)
    position = fraction * (len(ordered) - 1)
    lower_rank = math.floor(position)
    upper_rank = math.ceil(position)
    if lower_rank == upper_rank:
        return ordered[int(position)]
    lower_value = ordered[lower_rank]
    upper_value = ordered[upper_rank]
    return lower_value + (upper_value - lower_value) * (position - lower_rank)


@dataclass(frozen=True)
class EndpointStats:
    """One endpoint's measured distribution, ready for the verdict."""

    endpoint: str
    count: int
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    server_p95_ms: float | None
    status_failures: int


def summarize(
    endpoint: str,
    samples: Sequence[float],
    *,
    server_samples: Sequence[float] | None = None,
    status_failures: int = 0,
) -> EndpointStats | None:
    """The per-endpoint summary over measured total round-trip milliseconds.

    ``server_samples`` are the server-processing figures the opt-in timing
    header contributed for the same requests (``None``/empty when the backend
    does not send it); ``status_failures`` counts non-2xx answers. ``None``
    when nothing was measured (the endpoint never answered).
    """
    if not samples:
        return None
    # A non-empty sample always ranks; cast narrows what mypy cannot see.
    p50 = cast(float, percentile(samples, 0.5))
    p95 = cast(float, percentile(samples, 0.95))
    server = list(server_samples or ())
    server_p95 = percentile(server, 0.95) if server else None
    return EndpointStats(
        endpoint=endpoint,
        count=len(samples),
        p50_ms=p50,
        p95_ms=p95,
        min_ms=min(samples),
        max_ms=max(samples),
        server_p95_ms=server_p95,
        status_failures=status_failures,
    )


def verdict(stats: EndpointStats, threshold_ms: float) -> bool:
    """Pass when every response was 2xx and p95 is at or under the threshold."""
    return stats.status_failures == 0 and stats.p95_ms <= threshold_ms


def parse_server_timing_ms(header_value: str, tag: str = SERVER_TIMING_TAG) -> float | None:
    """The ``dur`` of the tagged metric in a ``Server-Timing`` header value.

    Tolerates sibling metrics and surrounding whitespace; ``None`` when the
    tag is absent or carries no parsable duration - a backend without the
    opt-in middleware simply contributes no server column.
    """
    for metric in header_value.split(","):
        parts = metric.split(";")
        if parts[0].strip() != tag:
            continue
        for param in parts[1:]:
            name, _, value = param.strip().partition("=")
            if name.strip().lower() == "dur":
                try:
                    return float(value)
                except ValueError:
                    return None
    return None


def _http_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Mapping[str, object] | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, Mapping[str, str], bytes]:
    """One HTTP round trip; returns (status, headers, body bytes)."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed repo-variable URLs or explicit flags, never user input; stdlib-only like the other gate scripts
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        # A 4xx/5xx is still a usable HTTP answer (the verdict consumes it);
        # only connection-level failures escape as URLError -> ProbeError.
        return error.code, error.headers, error.read()


def _json_body(payload: bytes) -> dict[str, object]:
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ProbeError("backend answered with a non-object JSON body")
    return parsed


def _random_phone() -> str:
    """A fresh 10-digit Indian mobile per run: no cooldown or lockout reuse."""
    return f"9{random.randint(10_000_000_0, 999_999_99_9)}"  # nosec B311 - a demo-phone label, not a credential


def demo_login(base_url: str, phone: str, *, timeout: float = _REGISTER_TIMEOUT_SECONDS) -> str:
    """Mint a patient bearer through the demo-mode OTP read-back flow.

    Register (waiting the resend cooldown out when a prior run holds it),
    read the live challenge code back through the dev surface, verify, and
    open the session. Raises :class:`ProbeError` with the runbook hint when
    any step fails - most commonly a backend without the mock-OTP read-back,
    which wants ``--token`` instead.
    """
    register_url = base_url.rstrip("/") + "/v1/auth/register"
    for attempt in range(1, _MAX_REGISTER_ATTEMPTS + 1):
        status, _headers, payload = _http_request(
            "POST", register_url, body={"phone": phone}, timeout=timeout
        )
        if status != 200:
            raise ProbeError(f"register answered {status}: {payload.decode('utf-8', 'replace')}")
        outcome = _json_body(payload).get("outcome")
        if outcome == "sent":
            break
        if outcome == "cooldown":
            if attempt == _MAX_REGISTER_ATTEMPTS:
                raise ProbeError(f"register still in resend cooldown after {attempt} attempts")
            body = _json_body(payload)
            remaining = body.get("cooldown_remaining_seconds")
            wait = (
                float(remaining) + 2.0
                if isinstance(remaining, (int, float))
                else float(_COOLDOWN_FALLBACK_SECONDS)
            )
            print(f"latency probe: register in cooldown; waiting {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
        else:
            raise ProbeError(f"register outcome {outcome!r}; cannot proceed to verify")
    else:
        raise ProbeError("register never delivered a challenge")

    otp_url = (
        base_url.rstrip("/")
        + "/v1/auth/dev/otp?"
        + urllib.parse.urlencode({"phone": f"+91{phone}"})
    )
    status, _headers, payload = _http_request("GET", otp_url, timeout=timeout)
    if status != 200:
        raise ProbeError(
            f"OTP read-back answered {status} - the mock-OTP surface is off "
            "(needs SMS_PROVIDER=mock with APP_ENVIRONMENT in {dev,test} or DEMO_MODE=true); "
            "pass --token / LATENCY_PROBE_TOKEN instead"
        )
    code = _json_body(payload).get("code")
    if not isinstance(code, str) or not code:
        raise ProbeError("OTP read-back returned no code")

    verify_url = base_url.rstrip("/") + "/v1/auth/verify"
    status, _headers, payload = _http_request(
        "POST", verify_url, body={"phone": phone, "otp": code}, timeout=timeout
    )
    if status != 200 or _json_body(payload).get("outcome") != "verified":
        raise ProbeError(f"verify answered {status}: {payload.decode('utf-8', 'replace')}")

    session_url = base_url.rstrip("/") + "/v1/auth/session"
    status, _headers, payload = _http_request(
        "POST", session_url, body={"phone": phone}, timeout=timeout
    )
    if status != 200:
        raise ProbeError(f"session answered {status}: {payload.decode('utf-8', 'replace')}")
    jwt = _json_body(payload).get("jwt")
    if not isinstance(jwt, str) or not jwt:
        raise ProbeError("session answered without a jwt")
    return jwt


def measure_endpoint(
    base_url: str,
    endpoint: str,
    *,
    token: str | None,
    iterations: int,
    timeout: float,
) -> EndpointStats | None:
    """Run the measurement loop for one endpoint and summarize it."""
    url = base_url.rstrip("/") + endpoint
    totals: list[float] = []
    server_timings: list[float] = []
    status_failures = 0
    for _ in range(iterations):
        started = time.perf_counter()
        status, headers, _payload = _http_request("GET", url, token=token, timeout=timeout)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        totals.append(elapsed_ms)
        server_ms = parse_server_timing_ms(headers.get(SERVER_TIMING_HEADER, ""))
        if server_ms is not None:
            server_timings.append(server_ms)
        if not 200 <= status < 300:
            status_failures += 1
    return summarize(
        endpoint, totals, server_samples=server_timings, status_failures=status_failures
    )


def run_probe(
    base_url: str,
    endpoints: Sequence[str],
    *,
    iterations: int,
    token: str | None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    warmup: bool = True,
) -> list[EndpointStats]:
    """Measure every endpoint once and return the per-endpoint summaries.

    One warm-up request per endpoint (unmeasured) settles connection setup and
    route compilation so iteration 1 is not systematically the slowest.
    """
    if warmup:
        for endpoint in endpoints:
            _http_request("GET", base_url.rstrip("/") + endpoint, token=token, timeout=timeout)
    results: list[EndpointStats] = []
    for endpoint in endpoints:
        stats = measure_endpoint(
            base_url, endpoint, token=token, iterations=iterations, timeout=timeout
        )
        if stats is not None:
            results.append(stats)
    return results


def format_table(results: Sequence[EndpointStats], *, threshold_ms: float) -> str:
    """The per-endpoint verdict table (milliseconds, one decimal)."""
    header = (
        f"{'endpoint':<28} {'n':>4} {'p50':>9} {'p95':>9} {'min':>9} {'max':>9} "
        f"{'server-p95':>11} {'verdict':>8}"
    )
    lines = [header, "-" * len(header)]
    for stats in results:
        server = f"{stats.server_p95_ms:.1f}" if stats.server_p95_ms is not None else "-"
        mark = "PASS" if verdict(stats, threshold_ms) else "FAIL"
        lines.append(
            f"{stats.endpoint:<28} {stats.count:>4} {stats.p50_ms:>9.1f} {stats.p95_ms:>9.1f} "
            f"{stats.min_ms:>9.1f} {stats.max_ms:>9.1f} {server:>11} {mark:>8}"
        )
    lines.append(f"- * p95 threshold: {threshold_ms:.1f} ms")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure per-endpoint backend request latency (p50/p95/min/max) "
        "and exit non-zero on a p95 threshold breach (#901)."
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL, help="Backend base URL")
    parser.add_argument(
        "--iterations", type=int, default=DEFAULT_ITERATIONS, help="Requests per endpoint"
    )
    parser.add_argument(
        "--p95-threshold-ms",
        type=float,
        default=DEFAULT_P95_THRESHOLD_MS,
        help="p95 ceiling in milliseconds per endpoint",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        metavar="PATH",
        help="Endpoint path to measure (repeatable; default: /health, /v1/me, /v1/me/profile)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token for authenticated endpoints "
        "(default: LATENCY_PROBE_TOKEN, else the demo login flow)",
    )
    parser.add_argument("--phone", default=None, help="Demo-login phone (default: random per run)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help="Per-request timeout in seconds",
    )
    parser.add_argument("--no-warmup", action="store_true", help="Skip the unmeasured warm-up GET")
    args = parser.parse_args(argv)

    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    endpoints = tuple(args.endpoints) if args.endpoints else DEFAULT_ENDPOINTS
    for endpoint in endpoints:
        if not endpoint.startswith("/"):
            parser.error(f"--endpoint must be a path starting with '/': {endpoint}")

    token = args.token or os.environ.get("LATENCY_PROBE_TOKEN", "").strip() or None
    try:
        if token is None and any(endpoint != HEALTH_ENDPOINT for endpoint in endpoints):
            phone = args.phone or _random_phone()
            print(
                f"latency probe: minting a bearer via the demo login (phone {phone})",
                file=sys.stderr,
            )
            token = demo_login(args.backend_url, phone, timeout=args.timeout)
        results = run_probe(
            args.backend_url,
            endpoints,
            iterations=args.iterations,
            token=token,
            timeout=args.timeout,
            warmup=not args.no_warmup,
        )
    except (ProbeError, urllib.error.URLError) as error:
        print(f"latency probe: {error}", file=sys.stderr)
        return EXIT_HARNESS_ERROR

    print(format_table(results, threshold_ms=args.p95_threshold_ms))
    if not results:
        print("latency probe: no endpoint answered", file=sys.stderr)
        return EXIT_HARNESS_ERROR
    if all(verdict(stats, args.p95_threshold_ms) for stats in results):
        print(f"latency probe: PASS (all endpoints within {args.p95_threshold_ms:.1f} ms p95)")
        return EXIT_OK
    print(f"latency probe: FAIL (an endpoint breached {args.p95_threshold_ms:.1f} ms p95)")
    return EXIT_BREACH


if __name__ == "__main__":
    sys.exit(main())
