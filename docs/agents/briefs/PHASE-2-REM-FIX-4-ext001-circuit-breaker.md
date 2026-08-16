# Brief - FIX 4 Circuit breaker for EXT-001

**Ticket:** #104 · **Parent:** #51 · **Refreshed:** 2026-08-14
**Reading surface:** ~8.5K tokens (budget ~10K) - within budget

## Scope

Real-provider SMS sends are guarded by an in-process circuit breaker at the adapter seam. After N outage failures the breaker opens and sends fast-fail until a cooldown, then a half-open probe decides recovery. The mock (dev/E2E) path is untouched and the breaker only counts genuine provider outages (network/timeout/5xx/429), never 4xx contract rejections.

Acceptance criteria:

- [ ] `CircuitBreaker` is a pure state machine (closed/open/half-open) with an injectable clock; `CircuitBreakerSmsAdapter` wraps the provider adapter only, mock stays unwrapped.
- [ ] Closed -> open after N outage failures; only `SmsDeliveryError(retries_exhausted=True)` trips it.
- [ ] While open, `send()` raises immediately without calling the wrapped adapter and the failure flows through the existing queue degradation path (audit event).
- [ ] Half-open probe: success -> closed (recovery logged), failure -> open again.
- [ ] `build_sms_adapter` wraps the provider branch; config gains `sms_circuit_breaker_threshold` (5) and `sms_circuit_breaker_cooldown_seconds` (30.0), validated positive.
- [ ] Module docstring states the breaker contract (drops the later-phase-concern sentence).
- [ ] `npm run test:unit:backend` and `npm run typecheck` pass.

## Read-list (in order, token estimates)

1. `modules.iam.adapters.sms` - the whole seam: `SmsAdapter` protocol, `SmsSendRequest`/`SmsSendResult`, `SmsProviderAdapter.send` (where `retries_exhausted` True/False originates), `SmsDeliveryQueue._deliver` (the degradation path the open-state raise flows into - no queue change), `build_sms_adapter` (provider branch to wrap), and the module docstring to update (~3.5K).
2. `app.config` `Settings` + `get_settings` - the `sms_*` field cluster and `__post_init__` validation pattern the two new breaker settings join (env-read via the `_env_*` helpers) (~1.5K).
3. `tests/unit/test_iam_sms_adapter.py` - only the `SmsProviderAdapter` retry/error tests + the `build_sms_adapter` test + the fixture helpers (the `SmsDeliveryError` construction pattern to reuse); slice, don't read the whole file (~2.5K).
4. `docs/standards/third-party-integration-standards.md` §1 - the EXT-001 call discipline the breaker column completes (timeout/retry + breaker) (~0.5K).

## Do NOT read

- The facade, routes, outbox internals, the gateway, frontend, `docs/archive/`. No DB schema, no queue change, no mock changes.

## Baseline verify (from ticket)

- `npm run test:unit:backend` (green this session: 545 passed)
- `npm run typecheck:backend` (green)
- `npm run lint` (green)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck:backend`

## Handoff notes

- Parent #75 finding: the breaker column of third-party-integration-standards §1 is unimplemented - a provider outage hammers every send with full retries.
- Only `retries_exhausted=True` trips the breaker (network/timeout/5xx/429); `retries_exhausted=False` (4xx reject, bad payload) never does - that is a contract error, not an outage.
- While open, `send()` must raise `SmsDeliveryError(retries_exhausted=True)` so `SmsDeliveryQueue._deliver` warns and fires `_on_delivery_failed` -> `otp.failed(delivery)` unchanged (FIX 5/REM T5 #81 audit path).
- Breaker state resets on restart - documented, same posture as idempotency/rate-limit in-process state.
- `SmsDeliveryError` lives in `modules.iam.domain.exceptions`; the `mask_phone` redaction is the log surface for the open-state marker.
