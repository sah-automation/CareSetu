# Brief - T11 Idempotency-Key on the auth mutations

**Ticket:** #80 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~8K tokens (budget ~10K) - within budget

## Scope (verbatim)

The register/verify/resend mutations accept an `Idempotency-Key` header, and a repeated key returns the original result without re-executing the mutation - so a client retry after a network failure cannot double-issue an OTP or double-consume a challenge (api-standards §5). The store is in-process with a TTL and a bounded size, mirroring the rate limiter's memory discipline; a process restart degrading to at-most-once is an accepted, documented trade-off for this phase.

Acceptance criteria:

- [ ] POST /v1/auth/register, /verify, /resend read the `Idempotency-Key` header
- [ ] Replaying the same key returns the stored result; no second challenge is issued, no outbox row is duplicated, no verification re-executes
- [ ] Keys expire after the TTL; the store is bounded (no unbounded growth under key spray)
- [ ] Missing header behaves exactly as today
- [ ] Unit + route-level tests cover replay, TTL expiry, and the no-key path

## Read-list (in order, token estimates)

1. The three auth HTTP adapters - `register_patient`, `verify_otp`, `resend_otp` handlers and their Pydantic request models in `modules.iam.adapters.routes` (the thin parse → facade → return shape where the header is read and the result returned; the shared `ErrorEnvelope` + `register_error_handlers` contract that maps IAM domain errors to the envelope) (~2K).
2. The gateway edge - `RateLimitMiddleware` in `app.gateway` (in-memory fixed-window buckets keyed by identity/IP, monotonic TTL, `_MAX_TRACKED_BUCKETS` prune-then-evict discipline - the exact memory shape the idempotency store should mirror), plus `error_response` in `app.gateway.errors` and the middleware stack ordering in `app.main.create_app` (~1.5K).
3. api-standards.md §5 Idempotency & Retries (the header contract: mutations accept the key, duplicate keys return the original result) and §2 Error Envelope (conventions to mirror for any store-driven rejection) (~0.8K).
4. The facade result shapes - `RegisterPatientResult`, `VerifyOtpResult`, `ResendOtpResult` in `modules.iam.facade` (what gets stored and replayed verbatim) (~1K).
5. internal-modules.md §3.1 MOD-001 and §4.1 sync matrix row "API Gateway / Edge → MOD-001" (where the idempotency contract sits at the edge, not in the module) (~0.5K).
6. The route-level unit tests for register/verify/resend (`tests/unit/test_iam_*_route.py` - the app-level gateway-stack and envelope-wiring patterns to extend with replay/TTL/no-key cases) (~2.2K).

## Do NOT read

- Dispatcher internals, outbox writer internals, other modules, `docs/archive/`.
- Session mint/refresh internals (T6/T7) - `issue_session`/`refresh_session` facade bodies; refresh has no HTTP adapter yet, only the facade method.
- Frontend, `phase0/`, lockout/resend domain internals.

## Baseline verify (from ticket)

- `npm run test:unit:backend` (backend unit suite already verified green centrally: 494 passed on 2026-08-13)

## Done-verify (from ticket)

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Parent #75 finding: the auth mutations have no `Idempotency-Key` handling - retries can double-issue an OTP or double-consume a challenge. Add the header read to the three adapters only; `issue_session` and `refresh_session` are out of scope.
- Mirror the existing envelope/error-envelope conventions from api-standards.md §2 - any store-driven rejection must answer the shared `ErrorEnvelope` (SCREAMING_SNAKE `code`, human-safe `message`, `trace_id`, `details`), never a raw exception string.
- The idempotency store mirrors `RateLimitMiddleware`'s in-process discipline: monotonic-clock TTL per key, bounded dict with prune-then-evict under a key spray (see `_MAX_TRACKED_BUCKETS`).
- Process restart degrades to at-most-once - an accepted, documented trade-off for this phase; call it out in the store module docstring.
- No-key requests must behave exactly as today (pass-through to the facade, no store write).
