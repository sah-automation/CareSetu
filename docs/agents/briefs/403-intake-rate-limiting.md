# Brief - 403 T06 Intake surface rate limiting

**Ticket:** #403 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The media-and-row-writing intake surface joins the OTP/auth route under the rate limiter. The `RateLimitMiddleware` scope widens from `/v1/auth/` to include `/v1/intake/upload-media`, `/submit`, and `/re-record` on the same strict tier, keyed per client IP (the limiter runs outermost, before identity). Exceeding the cap answers the shared 429 envelope with `Retry-After`. Acceptances: intake upload/submit/re-record count against the strict-tier limit the standards specify for intake; exhausted intake routes answer the shared 429 envelope with `Retry-After`; auth-only limiting semantics still hold.

## Read-list (in order)

1. `docs/adr/0007-split-origin-deployment-session-invariants.md` - HARD GATE before any middleware work; the split-origin topology this change must be reasoned against (~1K)
2. `app/gateway/rate_limit.py` - `RateLimitMiddleware` (`_DEFAULT_AUTH_PATH_PREFIX`, `dispatch` 429 path, `_key_for`, `_prune`) (~1.5K)
3. `app/main.py` - middleware order (JWTVerify then RateLimit outermost, ~:249-259); intake routes are downstream under their own router (~0.7K)
4. `modules/intake/adapters/routes.py` - the intake surface paths to cover (`upload-media` :191, `submit` :164, `re-record` :227) (~1.5K)
5. `app/gateway/errors.py` - `error_response` + `CODE_RATE_LIMIT_EXCEEDED` envelope; `app/config.py` tier settings (`gateway_rate_limit_auth_max_requests`/`window_seconds` defaults 10/60) (~1.2K)
6. `docs/standards/api-standards.md` §6 - the strictest-tier policy naming intake (~0.3K)

## Do NOT read

- AI pipeline/adapters, budget meter, frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - route-boundary tests (prior art `test_gateway.py` :526-676, `test_patient_intake_routes.py`): exhausted intake routes answer 429 + `Retry-After` with the shared envelope; auth-only tests still pass

## Handoff notes

- Keep the limiter outermost and per-IP keyed - intake runs before identity is attached
- A fixed window in-memory table by design (`_MAX_TRACKED_BUCKETS`, prune) - bound the new paths' buckets the same way
- Verify against the deployment topology (split-origin: Vercel frontend / Render backend), never localhost alone
