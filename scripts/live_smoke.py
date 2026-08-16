"""TEST-D (#137): post-deploy live smoke gate.

Automates the manual DEPLOY-7 verification (issue #117) as a hard-fail smoke
against the live demo stack, after `deploy-render` and after Vercel's build
settles (test-suite plan section 3.D). Five steps, in order:

1. Warm up the backend (Render free cold start), then `GET /health` -> 200
   `{"status": "ok"}`.
2. Full live demo flow with the Vercel `Origin` header on every call: register
   `+91 9000000001` -> `GET /v1/auth/dev/otp` -> verify -> `POST
   /v1/auth/session` -> `GET /v1/me` with Bearer (asserts `roles:
   ["patient"]`). Register on the seeded phone goes through the existing-phone
   login branch, which honours the 60 s resend cooldown - a `cooldown` answer
   waits the window out and retries (mirrors `tests/e2e/auth-loop.spec.ts`).
3. Assert `access-control-allow-origin` echoes the Vercel origin on every
   response (guards the CORS regression).
4. Assert error envelopes carry `code` / `message` / `trace_id` (api-standards
   section 2), probed with an unauthenticated `GET /v1/me` - a deterministic
   401 outside the per-IP `/v1/auth/*` rate limiter.
5. Assert the Vercel `/patient` page returns 200 with title "CareSetu" and the
   served JS chunk inlines the backend base URL and the demo-banner strings
   (guards the trailing-slash and env-inlining bugs found during DEPLOY-7).

Pacing: the flow makes ~4 auth-surface calls per runner-IP window (register,
dev/otp, verify, session) - safely under the 10 req / 60 s limiter (plan
section 2, section 3.D). A register cooldown retry only fires after waiting
the window out, so a retry never pushes the window over the cap.

Reads the `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` repo variables (created by
TEST-A2, #134); `--backend-url` / `--frontend-url` / `--origin` / `--phone`
override for local runs. Stdlib-only like the other gate scripts. Any step
failing exits 1, so the `deploy.yml` live-smoke job hard-fails on it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

CONNECT_TIMEOUT_SECONDS = 15.0
WARMUP_WINDOW_SECONDS = 600
WARMUP_POLL_SECONDS = 10
COOLDOWN_WAIT_BUFFER_SECONDS = 5
MAX_REGISTER_ATTEMPTS = 5
FRONTEND_SETTLE_WINDOW_SECONDS = 600
FRONTEND_POLL_SECONDS = 10

# The seeded demo phone (deploy plan / DEPLOY-7): registering it goes through
# the existing-phone login branch, which is exactly the branch under test.
DEMO_PHONE_DIGITS = "9000000001"


def _phone_e164(phone: str) -> str:
    """The E.164 form of a 10-digit demo phone (the dev/otp read-back key)."""
    return f"+91{phone}"


_USER_AGENT = "caresetu-live-smoke/1.0"
# Next.js renders its chunk <script> tags with the src attribute among other
# attributes; this pulls every script src (relative or absolute) out of the
# served page HTML so the step-5 JS-content assertion can fetch each chunk.
_SCRIPT_SRC = re.compile(r'<script[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)


class SmokeError(Exception):
    """A hard failure in the smoke runner itself (network/encoding)."""


@dataclass(frozen=True)
class CheckResult:
    """One smoke assertion: passed or failed, with the observed value."""

    label: str
    ok: bool
    observed: str


@dataclass(frozen=True)
class HttpResponse:
    """A completed HTTP exchange: status, headers, and raw body."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def json_body(self) -> dict[str, object]:
        """The body parsed as a JSON object, or {} for unreadable bodies."""
        try:
            parsed = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def text(self) -> str:
        """The body decoded as UTF-8, decompressed when a server ignores the
        `Accept-Encoding: identity` request."""
        encoding = (_header(self.headers, "content-encoding") or "").lower()
        raw = self.body
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            raw = zlib.decompress(raw)
        elif encoding:
            raise SmokeError(
                f"unexpected Content-Encoding {encoding!r} on a response "
                "requested with Accept-Encoding: identity",
            )
        return raw.decode("utf-8", errors="replace")


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


def _request(
    method: str,
    url: str,
    *,
    origin: str | None,
    payload: Mapping[str, object] | None = None,
    bearer: str | None = None,
) -> HttpResponse:
    """One HTTP request; returns the response for any HTTP status.

    Connection-level failures (refused/DNS/timeout) raise - callers decide
    whether to retry as availability. ``Origin`` is sent on every backend call
    so the smoke observes the real CORS behaviour of the deployed stack. The
    URLs come from the fixed repo-variable values (or explicit flags), never
    user input.
    """
    headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"}
    if origin is not None:
        headers["Origin"] = origin
    data: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT_SECONDS) as response:  # nosec B310 - fixed repo-variable URLs or explicit flags, never user input; stdlib-only like the other gate scripts
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, headers=dict(exc.headers.items()), body=exc.read())


def check_health(
    backend: str,
    origin: str,
    *,
    responses: list[HttpResponse],
    no_retry: bool,
) -> tuple[CheckResult, ...]:
    """Step 1: warm up, then /health -> 200 {"status": "ok"}.

    The warm-up poll absorbs the Render free cold start (plan section 2). The
    first 200 is the assertion target; earlier non-200 answers (the Render
    spin-up page) are poll noise and are NOT recorded for the step-3 CORS
    echo check, so a cold-start page that lacks the app's CORS headers cannot
    fail step 3.
    """
    deadline = time.monotonic() + (0 if no_retry else WARMUP_WINDOW_SECONDS)
    attempts = 0
    last_observation = "no response yet"
    while True:
        attempts += 1
        try:
            response = _request("GET", f"{backend}/health", origin=origin)
        except OSError as exc:
            last_observation = f"connection failed: {exc}"
        else:
            if response.status == 200:
                responses.append(response)
                body = response.json_body()
                if body.get("status") == "ok":
                    return (
                        _pass("warm-up + /health 200", f"200 after {attempts} attempt(s)"),
                        _pass("/health body", "status=ok"),
                    )
                return (
                    _pass("warm-up + /health 200", f"200 after {attempts} attempt(s)"),
                    _fail("/health body", f"expected status=ok (observed: {body!r})"),
                )
            last_observation = f"answered HTTP {response.status}"
        if time.monotonic() >= deadline:
            return (
                _fail(
                    "warm-up + /health 200",
                    f"/health never answered 200 within the window (last: {last_observation})",
                ),
            )
        time.sleep(WARMUP_POLL_SECONDS)


def _register(
    backend: str,
    origin: str,
    phone: str,
    *,
    responses: list[HttpResponse],
    no_retry: bool,
    expect_login: bool,
) -> CheckResult:
    """Register the seeded demo phone; a cooldown answer waits the window out.

    The seeded phone exists, so register goes through the existing-phone login
    branch, which honours the 60 s resend cooldown (PHASE-2 REM T3): a
    `cooldown` outcome means a prior OTP send (e.g. a deploy rerun right after
    a failed run) is still inside the window, so the smoke waits
    `cooldown_remaining_seconds` and retries rather than failing (mirrors
    `tests/e2e/auth-loop.spec.ts`). Each retry is paced a full window apart,
    so the per-IP /v1/auth/* limiter cap (10 req / 60 s) is never approached.
    With ``expect_login`` (the default demo phone) a sent code must also have
    come from the existing-phone login branch - proving the seed is present and
    the cooldown-capable branch is the one under test.
    """
    label = f"register +91{phone}"
    for attempt in range(1, MAX_REGISTER_ATTEMPTS + 1):
        response = _request(
            "POST",
            f"{backend}/v1/auth/register",
            origin=origin,
            payload={"phone": phone},
        )
        responses.append(response)
        body = response.json_body()
        if response.status != 200:
            return _fail(label, f"HTTP {response.status} (observed: {body!r})")
        outcome = body.get("outcome")
        if outcome == "sent":
            if expect_login and (
                body.get("flow") != "login" or body.get("is_existing") is not True
            ):
                return _fail(
                    label,
                    "expected the existing-phone login branch "
                    f"(observed flow={body.get('flow')!r}, "
                    f"is_existing={body.get('is_existing')!r})",
                )
            return _pass(label, f"outcome sent (attempt {attempt})")
        if outcome == "cooldown":
            if no_retry:
                return _fail(label, "outcome cooldown (--no-retry)")
            cooldown = body.get("cooldown_remaining_seconds")
            wait = (
                int(cooldown) if isinstance(cooldown, int) else 60
            ) + COOLDOWN_WAIT_BUFFER_SECONDS
            print(
                f"live smoke: register in resend cooldown; waiting {wait}s "
                f"(attempt {attempt}/{MAX_REGISTER_ATTEMPTS})",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue
        return _fail(label, f"unexpected outcome {outcome!r} (observed: {body!r})")
    return _fail(label, f"still in cooldown after {MAX_REGISTER_ATTEMPTS} attempts")


def _flow_failures(results: list[CheckResult], note: str) -> tuple[CheckResult, ...]:
    """Append a note that the downstream auth steps were skipped, then return."""
    results.append(_fail("remaining demo-flow steps", note))
    return tuple(results)


def check_demo_flow(
    backend: str,
    origin: str,
    phone: str,
    *,
    responses: list[HttpResponse],
    no_retry: bool,
) -> tuple[CheckResult, ...]:
    """Step 2: register -> dev/otp -> verify -> session -> /v1/me."""
    results: list[CheckResult] = []

    register = _register(
        backend,
        origin,
        phone,
        responses=responses,
        no_retry=no_retry,
        expect_login=phone == DEMO_PHONE_DIGITS,
    )
    results.append(register)
    if not register.ok:
        return _flow_failures(results, "register did not send a code; verify/session/me skipped")

    otp_url = f"{backend}/v1/auth/dev/otp?{urllib.parse.urlencode({'phone': _phone_e164(phone)})}"
    otp_response = _request("GET", otp_url, origin=origin)
    responses.append(otp_response)
    otp_body = otp_response.json_body()
    code = otp_body.get("code") if otp_response.status == 200 else None
    if not isinstance(code, str) or not code:
        results.append(
            _fail(
                "GET /v1/auth/dev/otp",
                f"HTTP {otp_response.status}, no code (observed: {otp_body!r})",
            ),
        )
        return _flow_failures(results, "OTP read-back failed; verify/session/me skipped")
    results.append(_pass("GET /v1/auth/dev/otp", "code read back"))

    verify_response = _request(
        "POST",
        f"{backend}/v1/auth/verify",
        origin=origin,
        payload={"phone": phone, "otp": code},
    )
    responses.append(verify_response)
    verify_body = verify_response.json_body()
    if verify_response.status != 200 or verify_body.get("outcome") != "verified":
        results.append(
            _fail(
                "POST /v1/auth/verify",
                f"HTTP {verify_response.status}, outcome {verify_body.get('outcome')!r} "
                f"(observed: {verify_body!r})",
            ),
        )
        return _flow_failures(results, "verify did not land; session/me skipped")
    results.append(_pass("POST /v1/auth/verify", "outcome verified"))

    session_response = _request(
        "POST",
        f"{backend}/v1/auth/session",
        origin=origin,
        payload={"phone": phone},
    )
    responses.append(session_response)
    session_body = session_response.json_body()
    jwt = session_body.get("jwt")
    if session_response.status != 200 or not isinstance(jwt, str) or not jwt:
        results.append(
            _fail(
                "POST /v1/auth/session",
                f"HTTP {session_response.status}, no JWT minted (observed: {session_body!r})",
            ),
        )
        return _flow_failures(results, "session did not mint a JWT; /v1/me skipped")
    results.append(_pass("POST /v1/auth/session", "JWT minted"))

    me_response = _request("GET", f"{backend}/v1/me", origin=origin, bearer=jwt)
    responses.append(me_response)
    me_body = me_response.json_body()
    if me_response.status != 200:
        results.append(
            _fail("GET /v1/me with Bearer", f"HTTP {me_response.status} (observed: {me_body!r})"),
        )
        return tuple(results)
    roles = me_body.get("roles")
    if roles != ["patient"]:
        results.append(_fail("GET /v1/me roles", f"expected ['patient'] (observed: {roles!r})"))
        return tuple(results)
    results.append(
        _pass("GET /v1/me with Bearer", f"subject {me_body.get('subject_id')!r}, roles {roles!r}"),
    )
    return tuple(results)


def check_cors(origin: str, *, responses: Sequence[HttpResponse]) -> tuple[CheckResult, ...]:
    """Step 3: access-control-allow-origin echoes the Vercel origin everywhere.

    Starlette echoes the allow-origin header only when the request ``Origin``
    is in the deployed ``CORS_ALLOWED_ORIGINS`` allowlist (DEPLOY-1), so a
    missing/mismatched header here means the Vercel origin is not in the
    backend's allowlist - a deployment-config regression, not a middleware one
    (handoff note in the TEST-D brief).
    """
    if not responses:
        return (_fail("CORS access-control-allow-origin echo", "no responses observed to check"),)
    failing = [
        response
        for response in responses
        if _header(response.headers, "access-control-allow-origin") != origin
    ]
    if not failing:
        return (
            _pass(
                "CORS access-control-allow-origin echo",
                f"{origin} on all {len(responses)} responses",
            ),
        )
    observed = _header(failing[0].headers, "access-control-allow-origin")
    return (
        _fail(
            "CORS access-control-allow-origin echo",
            f"missing/mismatched on {len(failing)} of {len(responses)} responses "
            f"(first failure observed: {observed!r})",
        ),
    )


def check_error_envelope(
    backend: str,
    origin: str,
    *,
    responses: list[HttpResponse],
) -> tuple[CheckResult, ...]:
    """Step 4: an unauthenticated /v1/me answers a 401 envelope.

    Probes the observability contract (api-standards section 2) with a
    deterministic gateway rejection - no token on the protected route - so the
    envelope shape is checked without consuming auth-surface limiter budget
    (``/v1/me`` is outside the ``/v1/auth/*`` prefix). The response is also
    checked for the CORS echo, covering step 3's "every response" claim for
    this one.
    """
    try:
        response = _request("GET", f"{backend}/v1/me", origin=origin)
    except OSError as exc:
        return (_fail("error envelope (unauthenticated /v1/me)", f"connection failed: {exc}"),)
    responses.append(response)
    body = response.json_body()
    missing = [
        key
        for key in ("code", "message", "trace_id")
        if not isinstance(body.get(key), str) or not body[key]
    ]
    envelope_results: list[CheckResult] = []
    if response.status != 401:
        envelope_results.append(
            _fail(
                "error envelope (unauthenticated /v1/me)",
                f"expected 401 (observed: {response.status})",
            ),
        )
    elif missing:
        envelope_results.append(
            _fail(
                "error envelope carries code/message/trace_id",
                f"missing/empty: {missing} (observed: {body!r})",
            ),
        )
    else:
        envelope_results.append(
            _pass(
                "error envelope carries code/message/trace_id",
                f"401 with code={body.get('code')!r}, trace_id={body.get('trace_id')!r}",
            ),
        )
    if _header(response.headers, "access-control-allow-origin") != origin:
        envelope_results.append(
            _fail(
                "CORS access-control-allow-origin on the 401 envelope",
                "not echoed on the unauthenticated /v1/me response",
            ),
        )
    else:
        envelope_results.append(
            _pass("CORS access-control-allow-origin on the 401 envelope", origin)
        )
    return tuple(envelope_results)


def _script_srcs(html: str) -> list[str]:
    return _SCRIPT_SRC.findall(html)


def check_frontend(frontend: str, backend: str, *, no_retry: bool) -> tuple[CheckResult, ...]:
    """Step 5: /patient serves 200, titles CareSetu, and inlines the right JS.

    Polls until the Vercel build settles (the frontend rebuild lands
    asynchronously from `deploy-render`), then fetches every JS chunk the page
    references and asserts the two DEPLOY-7 regressions cannot silently return:
    the backend base URL is inlined (guards a missing NEXT_PUBLIC_API_BASE_URL
    falling back to localhost:8000) and the demo-banner string is present
    (guards the trailing-slash / env-inlining bugs). The base-URL comparison
    strips trailing slashes so a URL written with or without one both match.
    """
    deadline = time.monotonic() + (0 if no_retry else FRONTEND_SETTLE_WINDOW_SECONDS)
    page: HttpResponse | None = None
    last_observation = "no response yet"
    while page is None and time.monotonic() < deadline:
        try:
            response = _request("GET", f"{frontend}/patient", origin=None)
        except OSError as exc:
            last_observation = f"connection failed: {exc}"
        else:
            if response.status == 200:
                page = response
            else:
                last_observation = f"answered HTTP {response.status}"
        if page is None:
            time.sleep(FRONTEND_POLL_SECONDS)
    if page is None:
        return (
            _fail(
                "Vercel /patient serves 200",
                f"not served within the settle window (last: {last_observation})",
            ),
        )

    results: list[CheckResult] = [_pass("Vercel /patient serves 200", "200 answered")]
    html = page.text
    if "<title>CareSetu</title>" not in html:
        results.append(
            _fail("page title is CareSetu", "no <title>CareSetu</title> in the served HTML")
        )
    else:
        results.append(_pass("page title is CareSetu", "<title>CareSetu</title>"))

    scripts = _script_srcs(html)
    if not scripts:
        results.append(_fail("served JS chunk", "no script src found in the /patient HTML"))
        return tuple(results)
    chunks: list[str] = []
    for src in scripts:
        url = urllib.parse.urljoin(frontend, src)
        try:
            chunk = _request("GET", url, origin=None)
        except OSError as exc:
            results.append(_fail(f"JS chunk {src}", f"connection failed: {exc}"))
            continue
        if chunk.status != 200:
            results.append(_fail(f"JS chunk {src}", f"HTTP {chunk.status}"))
            continue
        chunks.append(chunk.text)
    if not chunks:
        return tuple(results)

    joined = "\n".join(chunks)
    backend_normalized = backend.rstrip("/")
    if backend_normalized not in joined:
        results.append(
            _fail(
                "JS inlines the backend base URL", f"{backend_normalized!r} not found in any chunk"
            )
        )
    else:
        results.append(_pass("JS inlines the backend base URL", f"found {backend_normalized!r}"))
    if "Demo OTP:" not in joined:
        results.append(
            _fail("JS inlines the demo-banner string", "'Demo OTP:' not found in any chunk")
        )
    else:
        results.append(_pass("JS inlines the demo-banner string", "found 'Demo OTP:'"))
    return tuple(results)


def _resolve_urls(args: argparse.Namespace) -> tuple[str, str, str, str]:
    """The live URLs/origin from flags or the TEST-A2 repo variables."""
    backend = args.backend_url or os.environ.get("LIVE_BACKEND_URL")
    frontend = args.frontend_url or os.environ.get("LIVE_FRONTEND_URL")
    if not backend:
        raise SystemExit(
            "live smoke FAILED: missing LIVE_BACKEND_URL "
            "(set the TEST-A2 repo variable or pass --backend-url)",
        )
    if not frontend:
        raise SystemExit(
            "live smoke FAILED: missing LIVE_FRONTEND_URL "
            "(set the TEST-A2 repo variable or pass --frontend-url)",
        )
    origin = args.origin
    if origin is None:
        parsed = urllib.parse.urlsplit(frontend)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if not origin:
        raise SystemExit(
            f"live smoke FAILED: could not derive the Origin from {frontend!r} (pass --origin)",
        )
    return backend, frontend, origin, args.phone or DEMO_PHONE_DIGITS


def _report(results: Sequence[CheckResult]) -> None:
    for result in results:
        verdict = "PASS" if result.ok else "FAIL"
        print(f"  {verdict} {result.label}: {result.observed}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the five-step live smoke; exit 0 only when every step passes."""
    parser = argparse.ArgumentParser(
        description="TEST-D (#137): post-deploy live smoke gate (test-suite plan 3.D).",
    )
    parser.add_argument(
        "--backend-url", default=None, help="live backend URL (default: LIVE_BACKEND_URL env)"
    )
    parser.add_argument(
        "--frontend-url",
        default=None,
        help="live Vercel frontend URL (default: LIVE_FRONTEND_URL env)",
    )
    parser.add_argument(
        "--origin",
        default=None,
        help="Origin header to send and assert echoed (default: frontend origin)",
    )
    parser.add_argument(
        "--phone", default=None, help=f"10-digit demo phone (default: {DEMO_PHONE_DIGITS})"
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="fail on the first attempt instead of waiting out cooldown/warm-up/settle windows",
    )
    args = parser.parse_args(argv)

    backend, frontend, origin, phone = _resolve_urls(args)
    responses: list[HttpResponse] = []
    results: list[CheckResult] = []

    print(f"live smoke: backend={backend} frontend={frontend} origin={origin} phone=+91{phone}")
    print("step 1/5: warm up + /health")
    results.extend(check_health(backend, origin, responses=responses, no_retry=args.no_retry))
    print("step 2/5: live demo flow (register -> dev/otp -> verify -> session -> /v1/me)")
    results.extend(
        check_demo_flow(backend, origin, phone, responses=responses, no_retry=args.no_retry)
    )
    print("step 3/5: CORS access-control-allow-origin echo")
    results.extend(check_cors(origin, responses=responses))
    print("step 4/5: error envelope code/message/trace_id")
    results.extend(check_error_envelope(backend, origin, responses=responses))
    print("step 5/5: Vercel /patient page + inlined JS")
    results.extend(check_frontend(frontend, backend, no_retry=args.no_retry))

    _report(results)
    if all(result.ok for result in results):
        print("live smoke OK: all five steps passed against the live demo stack")
        return 0
    print("live smoke FAILED: one or more steps failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
