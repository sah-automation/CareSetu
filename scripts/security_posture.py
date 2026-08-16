"""TEST-B2 (#136): live boundary security posture gate.

Asserts ``NFR-SEC-001`` (``docs/standards/security-phii-standards.md``: TLS 1.2+
on every external interface, HSTS, no legacy ciphers) against the live Render
backend and Vercel frontend URLs that TEST-A2 (#134) published as the
``LIVE_BACKEND_URL`` / ``LIVE_FRONTEND_URL`` repo variables. The checks are
absolute - HTTPS only, TLS >= 1.2, legacy TLS refused, no legacy/cleartext
cipher, HSTS present with a meaningful max-age, and ``X-Content-Type-Options:
nosniff`` - and the job hard-fails on merge (``deploy.yml`` after
``deploy-render``) and nightly.

Tolerant only in the availability sense (test-suite plan section 5): the whole
check retries within a bounded window before failing, so a deploy-in-progress
(the Render hook build, Render's cold start, or a mid-deploy Vercel build still
serving the previous release) is not mistaken for a regression. When the window
expires the script fails with the last observed value of every failing
check/header.

Stdlib-only like the other gate scripts. URLs resolve from the environment by
default; ``--backend-url`` / ``--frontend-url`` override for local runs.
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# HSTS below 180 days is effectively disabled - a floor the middleware and the
# Vercel edge config both clear comfortably.
HSTS_MIN_MAX_AGE_SECONDS = 15552000
MINIMUM_TLS_VERSIONS = frozenset({"TLSv1.2", "TLSv1.3"})
# Cipher names whose algorithm is legacy or cleartext (NULL/export-grade,
# RC4/RC2, DES/3DES, MD5-based, and pre-shared-key suites). A negotiated suite
# containing any of these violates "no legacy ciphers" (NFR-SEC-001).
LEGACY_CIPHER_MARKERS = (
    "NULL",
    "RC4",
    "RC2",
    "DES",
    "3DES",
    "EXPORT",
    "MD5",
    "PSK",
    "SRP",
    "SEED",
    "IDEA",
)


def _tls_context() -> ssl.SSLContext:
    """A TLS client that skips certificate verification.

    The probe asserts the protocol floor and the cipher posture, not the CA
    chain - the ``urllib`` header fetch verifies the certificate on its own
    connection, so a broken/bogus cert still surfaces as a failure there.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # nosec B494 - deliberate: the probe skips certificate verification (check_hostname=False / CERT_NONE); the header fetch's default context verifies the chain
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _legacy_only_context() -> ssl.SSLContext:
    """A TLS 1.0/1.1-only client for the legacy-refusal probe.

    Python 3.13 defaults ``PROTOCOL_TLS_CLIENT`` to a TLSv1.2 floor and prunes
    the legacy suites from the default cipher set, so both are re-opened
    explicitly here; a modern server must still refuse the handshake, which is
    the assertion. The deprecated floor/cap constants and the security-level 0
    cipher list are used under a warning filter - the probe exists exactly to
    prove the server rejects this protocol range.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        context = _tls_context()
        context.minimum_version = ssl.TLSVersion.TLSv1
        context.maximum_version = ssl.TLSVersion.TLSv1_1
        context.set_ciphers("ALL:@SECLEVEL=0")
    return context


CONNECT_TIMEOUT_SECONDS = 15.0
RETRY_WINDOW_SECONDS = 600
RETRY_POLL_SECONDS = 10

_HEADER_FETCH_UA = "caresetu-security-posture/1.0"


@dataclass(frozen=True)
class CheckResult:
    """One posture assertion against one target: passed or failed, with the
    observed value so a failure names the header/check and what it showed."""

    label: str
    ok: bool
    observed: str


@dataclass(frozen=True)
class TargetOutcome:
    """The posture results for one URL for one attempt.

    ``reached`` is False when the target was unavailable (connection refused,
    DNS, timeout) rather than having answered - those are retried as
    availability; an SSL handshake error or a header mismatch is a hard result
    that is still retried (a deploy may be mid-swap) but reported verbatim if
    the window runs out.
    """

    url: str
    reached: bool
    results: tuple[CheckResult, ...]
    availability_error: str = ""

    @property
    def ok(self) -> bool:
        return self.reached and all(result.ok for result in self.results)


def _pass(label: str, observed: str) -> CheckResult:
    return CheckResult(label=label, ok=True, observed=observed)


def _fail(label: str, observed: str) -> CheckResult:
    return CheckResult(label=label, ok=False, observed=observed)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive read of one response header."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _hsts_max_age(value: str) -> int | None:
    """The ``max-age`` directive of an HSTS value, or None when absent/garbled."""
    for part in value.split(";"):
        part = part.strip()
        if part.lower().startswith("max-age="):
            try:
                return int(part.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def check_response_headers(headers: Mapping[str, str]) -> tuple[CheckResult, ...]:
    """HSTS + X-Content-Type-Options assertions on a live response."""
    results: list[CheckResult] = []
    hsts = _header(headers, "strict-transport-security")
    if hsts is None:
        results.append(
            _fail("HSTS (Strict-Transport-Security)", "header missing (observed: absent)")
        )
    else:
        max_age = _hsts_max_age(hsts)
        if max_age is None or max_age < HSTS_MIN_MAX_AGE_SECONDS:
            results.append(
                _fail(
                    "HSTS (Strict-Transport-Security)",
                    f"max-age below the {HSTS_MIN_MAX_AGE_SECONDS}s floor (observed: {hsts!r})",
                )
            )
        else:
            results.append(_pass("HSTS (Strict-Transport-Security)", f"max-age={max_age}s"))
    xcto = _header(headers, "x-content-type-options")
    if xcto is None:
        results.append(_fail("X-Content-Type-Options", "header missing (observed: absent)"))
    elif xcto.strip().lower() != "nosniff":
        results.append(
            _fail("X-Content-Type-Options", f"wrong value (observed: {xcto!r}, expected nosniff)")
        )
    else:
        results.append(_pass("X-Content-Type-Options", "nosniff"))
    return tuple(results)


def is_legacy_cipher(cipher_name: str) -> bool:
    """Whether a negotiated cipher suite uses a legacy/cleartext algorithm."""
    upper = cipher_name.upper()
    return any(marker in upper for marker in LEGACY_CIPHER_MARKERS)


def _probe_tls(host: str, port: int, *, legacy_only: bool = False) -> tuple[str, str]:
    """One TLS handshake; returns ``(protocol_version, cipher_name)``.

    Raises ``ssl.SSLError`` when the handshake is refused and ``OSError`` for
    connection-level failures (refused/timeout/DNS) - ``check_target`` treats
    the latter as an availability problem that the retry window absorbs. With
    ``legacy_only`` the client is limited to TLS 1.0/1.1 so a modern server
    refuses the handshake.
    """
    context = _legacy_only_context() if legacy_only else _tls_context()
    with socket.socket() as raw:
        raw.settimeout(CONNECT_TIMEOUT_SECONDS)
        raw.connect((host, port))
        with context.wrap_socket(raw, server_hostname=host) as tls_sock:
            return tls_sock.version(), tls_sock.cipher()[0]


def check_tls(host: str, port: int) -> tuple[CheckResult, ...]:
    """TLS 1.2+ and cipher assertions against ``host:port``.

    The 1.2+ handshake and the legacy-refusal probe both speak to the server's
    configured protocol floor; the negotiated cipher names the suite in use.
    ``ssl.SSLError`` here means the server refused the handshake (a hard
    result); ``OSError`` (connection refused/timeout/DNS) propagates to the
    caller so it is reported as an availability problem, not a security pass.
    """
    results: list[CheckResult] = []
    try:
        version, cipher = _probe_tls(host, port)
    except ssl.SSLError as exc:
        return (_fail("TLS >= 1.2 handshake", f"refused (observed: {exc})"),)
    if version not in MINIMUM_TLS_VERSIONS:
        results.append(_fail("TLS >= 1.2", f"negotiated a legacy protocol (observed: {version})"))
    else:
        results.append(_pass("TLS >= 1.2", version))
    if is_legacy_cipher(cipher):
        results.append(_fail("no legacy/cleartext cipher", f"negotiated (observed: {cipher})"))
    else:
        results.append(_pass("no legacy/cleartext cipher", cipher))
    try:
        _probe_tls(host, port, legacy_only=True)
    except ssl.SSLError:
        results.append(_pass("legacy TLS (1.0/1.1) refused", "handshake rejected"))
    else:
        results.append(
            _fail("legacy TLS (1.0/1.1) refused", "server accepted a TLS <= 1.1 handshake")
        )
    return tuple(results)


def _fetch_response(url: str) -> tuple[int, dict[str, str]]:
    """A GET on ``url`` returning ``(status, headers)``.

    Any HTTP status is accepted (a 404 still carries the response headers);
    only connection-level failures raise. The default opener verifies the
    certificate, so a broken/bogus cert surfaces as an ``OSError``.
    """
    request = urllib.request.Request(url, headers={"User-Agent": _HEADER_FETCH_UA})
    try:
        with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT_SECONDS) as response:  # nosec B310 - dev-only CLI gate; the URLs are the fixed LIVE_BACKEND_URL / LIVE_FRONTEND_URL repo variables (or explicit flags), never user input, and urllib keeps the script stdlib-only like contract_check.py
            return response.status, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items())


def check_target(url: str) -> TargetOutcome:
    """Run the full posture assertion set against one URL."""
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme != "https":
        return TargetOutcome(
            url=url,
            reached=True,
            results=(_fail("HTTPS only", f"non-HTTPS scheme (observed: {scheme!r})"),),
        )
    host = parsed.hostname
    if host is None:
        return TargetOutcome(
            url=url,
            reached=False,
            results=(),
            availability_error=f"URL has no host: {url!r}",
        )
    port = parsed.port or 443
    results = [_pass("HTTPS only", "https")]
    try:
        results.extend(check_tls(host, port))
    except OSError as exc:
        return TargetOutcome(
            url=url,
            reached=False,
            results=tuple(results),
            availability_error=f"TLS probe failed: {exc}",
        )
    try:
        status, headers = _fetch_response(url)
    except OSError as exc:
        return TargetOutcome(
            url=url,
            reached=False,
            results=tuple(results),
            availability_error=str(exc),
        )
    results.append(_pass("HTTP reachable", f"GET {url} -> {status}"))
    results.extend(check_response_headers(headers))
    return TargetOutcome(url=url, reached=True, results=tuple(results))


def _resolve_urls(args: argparse.Namespace) -> tuple[str, str]:
    """The two live URLs from flags or the TEST-A2 repo variables."""
    backend = args.backend_url or os.environ.get("LIVE_BACKEND_URL")
    frontend = args.frontend_url or os.environ.get("LIVE_FRONTEND_URL")
    missing: list[str] = []
    if not backend:
        missing.append("LIVE_BACKEND_URL")
    if not frontend:
        missing.append("LIVE_FRONTEND_URL")
    if missing:
        raise SystemExit(
            f"security posture FAILED: missing {' and '.join(missing)} "
            "(set the repo variables TEST-A2 created, or pass --backend-url/--frontend-url)",
        )
    return backend, frontend


def _attempt(urls: Sequence[str]) -> list[TargetOutcome]:
    return [check_target(url) for url in urls]


def _outcome_lines(outcomes: Sequence[TargetOutcome]) -> list[str]:
    """Per-target PASS/FAIL lines for the final report, naming each failure's
    observed value (acceptance criterion: report which check/header failed)."""
    lines: list[str] = []
    for outcome in outcomes:
        lines.append(f"  target: {outcome.url}")
        if not outcome.reached:
            lines.append(f"    UNAVAILABLE: {outcome.availability_error}")
            continue
        for result in outcome.results:
            verdict = "PASS" if result.ok else "FAIL"
            lines.append(f"    {verdict} {result.label}: {result.observed}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run the boundary posture gate; exit 0 when both live URLs comply."""
    parser = argparse.ArgumentParser(
        description="Live boundary security posture gate (NFR-SEC-001): HTTPS only, "
        "TLS 1.2+, HSTS, X-Content-Type-Options, no legacy ciphers (test-suite plan 3.B2).",
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help="live backend URL (default: LIVE_BACKEND_URL env var)",
    )
    parser.add_argument(
        "--frontend-url",
        default=None,
        help="live frontend URL (default: LIVE_FRONTEND_URL env var)",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="fail on the first attempt instead of retrying within the warm-up window",
    )
    args = parser.parse_args(argv)
    backend_url, frontend_url = _resolve_urls(args)
    urls = (backend_url, frontend_url)

    deadline = time.monotonic() + RETRY_WINDOW_SECONDS
    outcomes = _attempt(urls)
    while not all(outcome.ok for outcome in outcomes):
        attempts_left = deadline - time.monotonic()
        if args.no_retry or attempts_left <= 0:
            break
        statuses = ", ".join(
            "ok" if outcome.ok else "unavailable" if not outcome.reached else "failed"
            for outcome in outcomes
        )
        print(
            f"security posture: retrying ({statuses}, {int(attempts_left)}s left)",
            file=sys.stderr,
        )
        time.sleep(RETRY_POLL_SECONDS)
        outcomes = _attempt(urls)

    if all(outcome.ok for outcome in outcomes):
        for line in _outcome_lines(outcomes):
            print(line)
        print(
            f"security posture OK: {backend_url} and {frontend_url} meet NFR-SEC-001 "
            "(HTTPS only, TLS 1.2+, HSTS, X-Content-Type-Options: nosniff, no legacy ciphers)",
        )
        return 0

    for line in _outcome_lines(outcomes):
        print(line, file=sys.stderr)
    print("security posture FAILED: one or more NFR-SEC-001 assertions violated", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
