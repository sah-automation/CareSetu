# Brief - T4 SMS delivery leaves the request path

**Ticket:** #86 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~10K tokens (budget ~10K) - within budget

## Scope

Issuing an OTP no longer blocks the HTTP request on the EXT-001 provider. The register and resend flows commit the challenge and events, then dispatch SMS delivery as a background task so a slow or retrying provider never holds the patient's request (third-party-integration-standards §1: never in the user-critical path). The OTP value stays hashed at rest and in-process only; the mock adapter still records sent codes for tests/E2E deterministically via a flush hook.

Acceptance criteria:

- [ ] register/resend respond without awaiting the provider send (no request blocks through retries/backoff)
- [ ] Delivery still happens (background), is tracked, and a flush hook lets tests/E2E await pending sends deterministically
- [ ] The dev/test OTP read-back for the E2E suite is safe against the async delivery race
- [ ] OTP values remain hashed at rest and never logged; the adapter's no-OTP-in-logs discipline holds
- [ ] Unit tests cover "response returned before delivery completes", flush, and the failed-send log marker; E2E auth loop stays green

## Read-list (in order)

1. The EXT-001 SMS adapter contract - `SmsAdapter` protocol, `MockSmsAdapter` (`last_sent_code`, `sent_count`), `SmsProviderAdapter` (timeout ≤10 s, up to 3 retries with `backoff_delay` exponential+jitter, `patient.auth_failed` error-log marker on persistent failure), `build_sms_adapter` (mock/provider gating by `Settings`) in `apps/backend/modules/iam/adapters/sms.py` (~2.5K).
2. The two OTP-issuing facade paths - `register_patient` and `resend_otp` in `apps/backend/modules/iam/facade.py`: challenge insert with `hash_otp`, `write_outbox` of `otp_sent` in the same transaction, then the post-commit inline `self._sms.send(...)` - the send currently in the request path (~2.5K).
3. The `otp.sent` event contract - `OtpSentPayload` + `otp_sent_envelope` in `apps/backend/modules/iam/domain/events.py` (payload names identity + challenge only, never the code) (~0.6K).
4. The outbox writer + handler seam - `write_outbox` in `bus/outbox_writer.py`, `HandlerRegistry` in `bus/registry.py`, and the fan-out `dispatch` in `bus/dispatch.py` (the seam a background delivery handler registers on) (~1.0K).
5. Dispatcher retry/dead-letter slice - `process_outbox_table` in `bus/dispatcher.py`: failed deliveries retry up to `max_attempts` then dead-letter; targeted slice only, not the poll-loop internals (~1.2K).
6. The worker composition root - `worker/main.py`: `build_registry`, `run_worker_until_stopped`, and the `register_handlers` seam (iam `register_handlers` is currently a no-op; the delivery handler lands here) (~0.8K).
7. The app-shell wiring - `apps/backend/app/main.py`: mock adapter stored on `app.state.mock_sms_adapter` (dev/test only) and the `GET /v1/auth/dev/otp` read-back route the E2E suite polls (~0.8K).
8. Mock SMS contract in tests + E2E auth loop - `tests/unit/test_iam_sms_adapter.py` (mock read surface, retry/no-OTP-in-logs), `tests/e2e/auth-loop.spec.ts` (register -> read mock OTP -> verify), and the `FailingSmsAdapter`/`ExplodingSmsAdapter` patterns in the iam integration suites (~1.4K).
9. `docs/standards/third-party-integration-standards.md` §1 + §2 - EXT-001 call discipline and "never in the user-critical path" (~0.3K).

## Do NOT read

- Dispatcher poll-loop internals (claiming, inflight windows, fan-out isolation) - only the retry/dead-letter slice above.
- Other modules, session/refresh logic, frontend, `docs/archive/`, `phase0/`.

## Baseline verify

- `npm run test:unit:backend` (backend unit suite already verified green centrally: 494 passed on 2026-08-13)
- `npm run test:e2e` (Playwright auth loop against mock SMS)

## Done-verify

- `npm run test:unit:backend` (response-before-delivery, flush, failed-send marker)
- `npm run test:e2e` (auth loop stays green against the async delivery)
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Parent #75 finding: SMS is in the user-critical path. Both `register_patient` (facade.py:290) and `resend_otp` (facade.py:636) await `self._sms.send(...)` inline after the outbox commit; a provider retrying through `SmsProviderAdapter.send` (3 retries, exponential+jitter) blocks the request past the 10 s timeout.
- The background delivery wrapper does NOT exist yet. The seam is confirmed: iam `register_handlers` in `apps/backend/modules/iam/adapters/__init__.py` is an empty no-op, and the worker composition root already imports it. The send moves into a handler on `otp.sent` executed by the worker's dispatcher; the facade keeps only the commit of the challenge + outbox event.
- Retry/dead-letter machinery confirmed: `process_outbox_table` in `bus/dispatcher.py` dead-letters a row after `max_attempts` and leaves it for reclaim on handler failure - the background send inherits that durability for free.
- EXT-001 discipline to preserve (sms.py): OTP value never reaches a log line (`mask_phone`, no raw payloads); `patient.auth_failed` marker on persistent failure; server-side key from `Settings` only; mock is the CI/dev default.
- The dev/test OTP read-back (`/v1/auth/dev/otp`) reads `MockSmsAdapter.last_sent_code(phone)` from app state; once the send is async this read-back races, so the flush hook must be surfaced through the same mock-adapter contract (or a test-only await) to keep the E2E auth loop deterministic.
- `OtpSentPayload` already omits the code; the background handler needs the phone + code routed in-process without widening the event payload or logging the value.
