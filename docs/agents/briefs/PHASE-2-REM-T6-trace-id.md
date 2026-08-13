# Brief - T6 One `trace_id` per request

**Ticket:** #77 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~4K tokens (budget ~10K) - within budget

## Scope

Every error response and its matching log line carry one request-scoped trace id, so a reported 401/403/422/5xx is reproducible from logs alone. The trace id is taken from the client's `X-Request-Id` when present, else minted once per request, and flows through the gateway rejection envelopes, the iam error envelopes, and the log lines that record them (error-handling-observability §3).

Acceptance criteria:

- [ ] A request-scoped trace id is established per incoming request (honouring `X-Request-Id`)
- [ ] Gateway rejection envelopes (401/403/429) and their `gateway_rejection` log lines carry that same trace id
- [ ] IAM error envelopes (validation, phone, SMS, session refusals) carry that same trace id
- [ ] Unit/app-level tests assert envelope trace id == log trace id for a fixed `X-Request-Id`

## Read-list (in order)

1. The gateway rejection funnel `error_response` in `app.gateway.errors` - the single envelope+log-line funnel for all three gateway shapes (401/403/429), which currently mints its own `uuid.uuid4().hex` per call so the envelope and the `gateway_rejection` log line can drift; plus `register_gateway_error_handlers` (~0.5K).
2. The gateway JWT middleware deny path - `JWTVerifyMiddleware.dispatch`, `_parse_bearer`, `_deny_unauthenticated` in `app.gateway.jwt_verify` - the presented-bad-token 401 denial that funnels through `error_response` (~0.5K).
3. The gateway rate-limit middleware deny path - `RateLimitMiddleware` in `app.gateway.rate_limit` - the 429 site, also funneled through `error_response` (~0.2K).
4. The iam HTTP adapter error envelope - `ErrorEnvelope` model + `_error_response` + `register_error_handlers` (validation / phone / SMS / session-refused / iam handlers) in `modules.iam.adapters.routes` - a fresh `uuid.uuid4().hex` per handler call, no log line tied to it (~0.7K).
5. The app shell middleware registration - `create_app` in `app.main` - the middleware stack (RateLimit, JWTVerify, CORS) where a request-scoped trace middleware slots in; also the `trace_id=uuid4().hex` sites in the dev-otp envelope (~0.6K).
6. `docs/standards/error-handling-observability.md` §2 (structured logging envelope with `trace_id`) + §3 (correlation & tracing) - the governing contract (~0.3K).
7. `docs/architecture/internal-modules.md` §4.2 - the Asynchronous Event Registry - confirms `event_id` is the async correlation key, distinct from the request `trace_id` (~0.2K).
8. The bus envelope/dispatcher correlation - `bus.envelope` event-id contract and `bus.outbox_writer` / `bus.dispatcher` `envelope_from_row` - the outbox's own correlation field that must not be conflated with `trace_id` (~0.4K).
9. Existing app-level trace assertions - `test_gateway.py`, `test_iam_register_route.py`, `test_iam_resend_route.py`, `test_iam_verify_route.py`, `test_iam_session_route.py` - the `trace_id` shape asserts that must tighten to equality against a fixed `X-Request-Id` (~0.3K).

Total ~3.7K.

## Do NOT read

- Domain logic (facade, verify/refresh machines), frontend, `docs/archive/`, dispatcher polling internals, outbox DDL/ledger internals, `test_iam_jwt.py` / `test_iam_session.py` internals (unrelated to envelope correlation).

## Baseline verify

- `npm run test:unit:backend` - already verified green centrally: 494 passed on 2026-08-13.

## Done-verify

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Parent #75 standards finding: "broken trace correlation". Today both the gateway `error_response` funnel and the iam `_error_response` mint a fresh `uuid.uuid4().hex` per error, so the envelope trace id can never match the log lines that record the same failure, and neither honours an inbound `X-Request-Id`. There is no request-scoped trace anywhere; a per-request middleware/state slot in the app shell is the intended seam.
- The outbox already carries its own correlation field: `event_id` is the dedupe/correlation key for async consumers (error-handling-observability §3, `bus.envelope` contract). Do not conflate it with the request `trace_id`; async events are out of scope for this ticket.
- No structured-JSON log formatter exists yet - logs are plain module `getLogger` loggers - so the envelope-vs-log equality assertion is the acceptance proxy for "same trace id", not a formatter change.
