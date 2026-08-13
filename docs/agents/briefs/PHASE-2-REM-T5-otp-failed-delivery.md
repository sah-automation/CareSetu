# Brief - T5 otp.failed emitted on delivery failure

**Ticket:** #81 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~9K tokens (budget ~10K) - within budget

## Scope

Lost OTPs are auditable. When SMS delivery ultimately fails (all retries exhausted), the iam module publishes `otp.failed` (reason `delivery`) to its outbox so the audit path can track phones that never received their code - not just the lockout case already emitted. The event payload gains the delivery reason, and the event registry reflects both emitters.

Acceptance criteria:

- [ ] A delivery failure that exhausts retries emits `otp.failed` with reason `delivery` to the iam outbox
- [ ] The lockout emission of `otp.failed` (reason `lockout`) is unchanged
- [ ] The event payload models both reasons; the event registry in internal-modules.md §4.2 lists both emitters
- [ ] Unit tests cover the delivery-failure emission and the unchanged lockout path

Blocked by: T1 (shared event catalog, #84), T4 (async delivery path, #86).

## Read-list (in order, token estimates)

1. The iam event payloads module (`modules.iam.domain.events`): `OtpFailedPayload` (currently `reason: Literal["lockout"]` with `lockout_until`), `otp_failed_envelope`, sibling envelope builders (`patient_auth_failed_envelope`, `otp_sent_envelope`), and the module's local `EVENT_OTP_FAILED` constant - note it redefines the name rather than importing from `bus.events` (~1.7K).
2. The outbox writer API (`bus.outbox_writer.write_outbox`): insert-pending-row contract that runs inside the caller's transaction, serialized via `Envelope` (~0.4K).
3. The delivery seam T4 wraps: the `SmsAdapter` protocol `send` operation, `SmsSendRequest`/`SmsTemplateParams`, `SmsDeliveryError`, the provider adapter's retry-exhaustion raise after `max_retries + 1` attempts, and `MockSmsAdapter.last_sent_code` for tests (~2.5K).
4. The facade call sites that move behind the delivery wrapper: `register_patient` and `resend_otp` (SMS send currently synchronous after transaction commit), plus the lockout emission block inside `verify_otp` (~2.6K).
5. internal-modules.md §4.2 async event registry - the `otp.failed` row (MOD-001 → MOD-011) (~0.5K).
6. `bus.events` - the shared event-name constants (T1 single source of truth; `EVENT_OTP_FAILED` currently reserved) (~0.2K).
7. ADR-0004 §6 - auth events flow through the outbox; the lockout emission contract that must stay unchanged (~0.3K).
8. Existing event tests: envelope/catalog/dispatch/registry unit tests and the lockout-emission assertion in the iam resend-lockout integration test (~1K).

## Do NOT read

Frontend, dispatcher internals (poll loop, dead-letter, backoff), docs/archive/, session/refresh logic (T6/T7), ledger/consumed-events internals.

## Baseline verify

- `npm run test:unit:backend` (from ticket; backend unit suite already verified green centrally: 494 passed on 2026-08-13)

## Done-verify

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- T1 (#84) shared event catalog single-source: `bus.events` is the code-side mirror of internal-modules.md §4.2 and the `check_event_names.py` gate is the repo-wide enforcer. iam currently redefines its own `EVENT_OTP_FAILED`; T5 should consume the shared catalog constant instead of the local one. The payload module docstring already points at the registry §4.2 as canonical.
- T4 (#86) async delivery: SMS send is currently synchronous in the facade (register_patient, resend_otp) after the transaction commits; T4 introduces the background delivery wrapper. T5 hooks the all-retries-exhausted point - the `SmsDeliveryError` raise in the provider adapter - to emit the delivery-reason event. No wrapper exists yet; the read-list target is the seam (adapter protocol + facade call sites), not the wrapper itself.
- ADR-0004 lockout emission unchanged: `otp_failed_envelope` is written in the same transaction as the lockout counter write-back with reason `lockout`; T5 must not regress that path. The payload `reason` widens to `Literal["lockout", "delivery"]`, and `lockout_until` should not apply to the delivery reason.
- Coverage gap to note: no unit test currently asserts `otp.failed` - the lockout emission is asserted only at integration level (one `otp.failed` row plus its fields). The delivery-failure emission unit test is genuinely new surface; the unchanged-lockout unit coverage may need an envelope-level assertion since the outbox-row write is exercised at integration.
