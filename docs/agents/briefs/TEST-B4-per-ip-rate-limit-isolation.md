# Brief - 128 TEST-B4 - Per-IP rate-limit isolation unit test

**Ticket:** #128 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

Close the one rate-limit gap the plan found: `TestClient` always presents a single client IP, so nothing proves the limiter keys per caller. Add a unit test that invokes `RateLimitMiddleware.dispatch` directly with crafted `Request` scopes carrying different `client.host` values and asserts the two source IPs get independent buckets (each exhausts its own cap; neither 429s the other). Validates NFR-SEC-004 ingress abuse protection.

The existing rate-limit contract (429 after N rapid auth calls, `Retry-After`, shared error envelope, auth-surface-only counting, garbage-token spray exhaustion) is already covered by the existing gateway unit tests - do not duplicate it.

Acceptance criteria (verbatim):

- A unit test asserts two different `client.host` values reach their caps independently (IP A exhausting its bucket does not 429 IP B, and vice versa)
- The test goes through `RateLimitMiddleware.dispatch` directly (not TestClient) with a stub `call_next`
- Existing rate-limit tests still pass unchanged

## Read-list (in order)

1. `apps/backend/app/gateway/rate_limit.py` - `RateLimitMiddleware.dispatch` signature (`request: Request, call_next: RequestResponseEndpoint`), the `/v1/auth/` path guard, `_key_for` (bucket key = `client.host`), and `error_response` behavior (~0.6K).
2. `tests/unit/test_gateway.py` - the rate-limit test section (`test_rate_limit_answers_429_with_retry_after_on_auth_route`, `test_garbage_token_spray_exhausts_ip_cap`, `test_rate_limit_prune_keeps_bucket_dict_bounded`) for the existing fixtures/pattern; note `RateLimitMiddleware` is instantiated directly at `test_gateway.py:570` for `_prune` - the precedent for direct middleware instantiation (~0.7K).
3. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.B4 - the two-IP technique (crafted `Request` scopes) (~0.2K).

## Do NOT read

- The full `test_gateway.py` (JWT/RBAC sections), any frontend code, `docs/archive/`, unrelated modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`, `npm run lint` (both green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes with the new test included and the existing rate-limit tests unchanged.

## Handoff notes

- `TestClient` hardcodes the single client IP `"testclient"`, so the new test must NOT go through TestClient - build `starlette.requests.Request(scope=...)` with differing `scope["client"] = ("1.2.3.4", ...)` / `("5.6.7.8", ...)` and call `dispatch(request, stub_call_next)` directly (async, so the test needs an async runner - pytest-asyncio is already configured with `asyncio_mode = "auto"`).
- The middleware checks `request.url.path.startswith(self.auth_path_prefix)` before keying, so the crafted scopes must use `/v1/auth/...` paths.
- `RateLimitMiddleware.__init__` accepts `enabled=True, max_requests=..., window_seconds=...` directly - no app needed, matching the existing `_prune` test pattern at `test_gateway.py:570`.
- The `stub call_next` can be a simple `async def` returning a 200 `Response`.
