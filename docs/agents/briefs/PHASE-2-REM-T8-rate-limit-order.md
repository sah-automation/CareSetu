# Brief - PHASE-2 REM T8 Auth-surface rate limit counts invalid tokens

**Ticket:** #78 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~9K tokens (budget ~10K) - within budget

## Scope

The auth-surface rate limit actually protects the surface. Currently a request presenting a malformed/expired/wrongly-signed Bearer token is denied by JWT verification before the rate limiter sees it, so an attacker can spray unlimited garbage tokens at /v1/auth/\*. The middleware order flips so the limiter counts every auth request first, then verification runs; the rate-limit key on the auth surface is the caller IP (the endpoints are unauthenticated), matching api-standards §6.

Acceptance criteria:

- [ ] Every /v1/auth/\* request (valid, invalid, or missing token) is counted toward the cap before JWT verification runs
- [ ] Spraying garbage tokens at the auth surface hits 429 at the cap
- [ ] Middleware ordering comment reflects the new intent
- [ ] App-level tests cover the garbage-token-exhausts-cap case and that valid auth flows still pass

## Read-list (in order)

1. The app shell `create_app` (app/main) - the middleware registration stack and its ordering comment (~2K).
2. The `rate_limit` gateway middleware (app.gateway.rate_limit) - path-prefix gate, key selection (`_key_for` per-identity vs per-IP), in-memory window, `_MAX_TRACKED_BUCKETS` bound, 429 + `Retry-After` envelope (~1.5K).
3. The `jwt_verify` gateway middleware (app.gateway.jwt_verify) - the deny path: `_parse_bearer` + `_deny_unauthenticated` return the 401 envelope without `call_next`, so the limiter downstream never sees the request; anonymous principal on missing header (~1.5K).
4. The gateway error envelope (app.gateway.errors) - `error_response` single funnel, `RATE_LIMIT_EXCEEDED` / `AUTH_UNAUTHENTICATED` codes, `gateway_rejection` log line (~0.5K).
5. The gateway app-level unit tests (tests/unit/test_gateway.py) - jwt_verify deny cases on the protected route, rate-limit cases on `/v1/auth/*`, and the per-identity keying test that depends on the current order (~3K).
6. api-standards §6 (docs/standards) - rate-limit "per identity or per IP with 429 + Retry-After" on OTP/auth/intake (~0.3K).
7. The gateway component spec (docs/architecture/internal-modules.md §2.1/§2.2) - lists rate-limit before JWT verify as the edge contract (~0.3K).
8. The PHASE-1 T7b brief (docs/agents/briefs/PHASE-1-T7b-gateway-stubs.md) - the original middleware-order contract the stub seam promised (~0.5K).

## Do NOT read

- IAM facade/domain internals, SMS adapter, session/refresh logic (T6/T7), frontend, dispatcher, `docs/archive/`, `phase0/`.

## Baseline verify

- `npm run test:unit:backend` (backend unit suite already verified green centrally: 494 passed on 2026-08-13)

## Done-verify

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Parent #75 finding: rate-limit bypass via garbage tokens - invalid tokens must count toward the limit before auth short-circuits.
- Current request path (outer to inner) is CORS -> `jwt_verify` -> `rate_limit` -> router: FastAPI/Starlette last-added is outermost, and `app.main` registers `RateLimitMiddleware` before `JWTVerifyMiddleware`. A presented-but-unusable token is answered 401 by `jwt_verify` without ever reaching `rate_limit`. The fix flips the pair so `rate_limit` is the outermost of the two (register `JWTVerifyMiddleware` first, `RateLimitMiddleware` second in `create_app`).
- The ordering comment in `create_app` currently states "jwt_verify, outermost ... so later limits can key off the Principal" - it must be rewritten for the new intent (limiter first, keyed by IP on the auth surface), per AC 3.
- Once the limiter runs first, `request.state.principal` is never attached on `/v1/auth/*`, so `_key_for` always returns the IP bucket there; the per-identity branch becomes unreachable on the auth surface. This matches the ticket's AC and api-standards §6.
- Test conflict to reconcile: `test_rate_limit_is_per_identity_when_authenticated` in the gateway unit tests currently depends on JWT running before the limiter (principal attached when the limiter keys). Under the flipped order it no longer holds - replace/augment it with the two AC 4 tests: garbage-token spray exhausts the IP cap at 429, and valid auth flows (missing-header anonymous register/verify, and a valid Bearer on the protected route) still pass.
- The iam route tests (test_iam_register/verify/resend/session_route) only assert `RateLimitMiddleware in middlewares` presence, not order - unaffected by the flip.
- The dev/test OTP read-back route `/v1/auth/dev/otp` sits under the auth path prefix, so it is counted too; keep the E2E cap (10/60s) in mind so the Playwright loop still fits under it.
