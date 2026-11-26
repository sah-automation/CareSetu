# Brief - T11 Notify module: WhatsApp/SMS fallback channel engine

**Ticket:** #246 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~9K tokens (budget 10K) - within budget (NEAR CAP - see handoff notes)

## Scope

The MOD-010 (notify) module build-out for the WhatsApp-first / SMS-fallback partner notification channel (ADR-0009). Notify is currently an empty scaffold (empty `NotifyFacade`, no handlers). After this ticket the notify module can deliver a terminal-status message to a partner: it tries WhatsApp via the EXT-003 integration, and when the EXT-003 delivery webhook reports the message failed/undeliverable (`notification.failed`), it falls back to SMS via the EXT-001 integration (which is now shared beyond OTP).

This is the transport/channel engine only. The specific partner terminal notifications (Active/Rejected with reason) that trigger on partner lifecycle events are wired in a separate ticket (T12).

Implementation:

- A `NotifyFacade` (currently empty scaffold) exposing a typed send-with-fallback method.
- The WhatsApp (EXT-003) and SMS (EXT-001) adapter ports, modeled on the existing iam SMS adapter (`modules/iam/adapters/sms.py`) - delivery queued/backgrounded, not blocking the request.
- The fallback chain: WhatsApp attempted first; on delivery failure/undeliverable (a `notification.failed` signal from the EXT-003 webhook) the message re-routes to SMS.
- The notify schema needed to track send attempts / delivery state (an outbox + any notification-state table via the module's schema).
- `register_handlers` in `modules/notify/adapters/__init__.py` wired so the `notification.failed` signal triggers the fallback.

Acceptance criteria (verbatim from #246):

- [ ] Notify facade exposes a send-with-fallback primitive that routes WhatsApp first, then SMS on delivery failure
- [ ] Delivery is non-blocking (background queued) matching the iam SMS adapter pattern
- [ ] A `notification.failed` signal on the WhatsApp channel triggers the SMS fallback
- [ ] notify schema + outbox created; `register_handlers` wired in the composition root (`worker/main.py` already imports it - confirm it wires)
- [ ] Unit tests for the fallback chain pattern (mirroring `test_iam_sms_adapter.py`)
- [ ] `npm run test:unit:backend` and `npm run typecheck` pass

## Read-list (in order)

1. `modules/iam/adapters/sms.py` - THE reference: `SmsAdapter` port, `MockSmsAdapter`, `SmsDeliveryQueue` (backgrounded, non-blocking), `CircuitBreaker`, `build_sms_adapter` config resolution - mirror this whole shape for notify's WhatsApp/SMS adapters (~2.5K)
2. `modules/notify/facade.py` + `modules/notify/outbox.py` + `modules/notify/schema/models.py` + `modules/notify/adapters/__init__.py` - the current (empty) scaffolds this ticket fills: `NotifyFacade`, `NOTIFY_OUTBOX_TABLE`, notify schema tables (add send-attempt / delivery-state model), `register_handlers` (~0.4K)
3. `bus/outbox_writer.py` + `bus/ledger.py` - `write_outbox` for inbound fallback events, `record_consumed_event` for the `notification.failed` consumer (idempotency) (~0.5K)
4. `apps/backend/bus/events.py` - `notification.failed` needs adding as a constant; confirm it is absent (~0.3K)
5. `apps/backend/worker/main.py` - the composition root already imports `notify_register_handlers` (line 45, in `_MODULE_REGISTERS`) - confirm the wiring seam, no change needed (~0.5K)
6. `docs/standards/third-party-integration-standards.md` - EXT-001/EXT-003 call discipline (timeout/retries/breaker) + webhook verification (HMAC/signature, idempotent, fast accept -> enqueue outbox) the adapters and the `notification.failed` consumer must honour (~0.5K)
7. `tests/unit/test_iam_sms_adapter.py` - the unit-test pattern to mirror for the fallback chain (read the delivery-queue + adapter test slices, not the whole 4K file) (~2K)

## Do NOT read

- partner lifecycle internals, audit internals, iam OTP/session logic beyond the sms.py adapter, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`
- `npm run migration-check` (baseline for the new notify schema addition)

## Done-verify (acceptance criteria -> commands)

- New notify fallback-chain unit test green (subset of unit suite)
- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run migration-check`

## Handoff notes

- **NEAR CAP / SIZING-GATE:** this ticket is at ~9K of a 10K budget and is the widest of the five. If the implementer's context is already partly consumed, re-cut the reading surface and STOP for a refreshed brief rather than over-reading. Keep `test_iam_sms_adapter.py` to the delivery-queue + adapter slices.
- Blocked by none - can start immediately; its own schema/outbox addition. Must land before T12 (#255) which consumes it.
- ADR-0009 is the governing decision: WhatsApp-first -> SMS fallback driven by the EXT-003 delivery webhook's `notification.failed`, NOT by guessing. Non-terminal updates are in-app only.
- `EXT-001` is now shared beyond OTP: `MOD-010` consumes SMS for partner notifications through the same backend/port as `MOD-001`. Do not duplicate the SMS adapter - model notify's SMS port on `modules/iam/adapters/sms.py` (module isolation: notify owns its own port contract, not an iam import).
- `notification.failed` is not yet an event constant - add it in `bus/events.py` (and register in the event catalog `internal-modules.md` §4.2 if that registry requires it).
- Webhook discipline (standards §4): the EXT-003 delivery webhook is HMAC/signature-verified, idempotent/replay-safe, accepts fast then enqueues via outbox - the `notification.failed` consumer runs async, ledged-idempotent.
- Existing `worker/main.py` already imports `notify_register_handlers` and places it in `_MODULE_REGISTERS` - the composition-root seam is present; this ticket just fills in `register_handlers`.
- Prior art: `modules/iam/adapters/sms.py` delivery queue + breaker; PHASE-2-REM T4/T5 (`#86`/`#81`) backgrounded delivery + `otp.failed` on delivery failure - the `notification.failed` fallback is the notify-module analogue.
