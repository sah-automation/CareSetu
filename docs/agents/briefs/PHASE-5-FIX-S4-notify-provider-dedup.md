# Brief - 258 Phase-5 fix: dedupe notify WhatsApp/SMS provider code (S4)

**Ticket:** #258 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The `notify` module's WhatsApp and SMS provider adapters are mirror-image near-duplicates (the review finding S4). Dedupe the encode/send/backoff/ack pipeline into one shared transport-provider helper so `whatsapp.py` and `sms.py` become thin typed shells over their channel-specific bits. No behavior change - same message shapes, callbacks, retry counts.

Acceptance criteria (from #258):

- [ ] One shared provider-crossing helper (or base) holds the send/backoff/ack pipeline; `whatsapp.py` and `sms.py` only supply channel-specific encode/decode + transport calls.
- [ ] No behavioral change: existing notify unit + integration tests pass unchanged.
- [ ] A provider-facing fix now exists in exactly one place (grep-verifiable).

## Read-list (in order)

1. `apps/backend/modules/notify/adapters/whatsapp.py` + `apps/backend/modules/notify/adapters/sms.py` - the two mirror-image adapters to de-dup: `Mock<Sms|WhatsApp>Channel`, `<X>ProviderChannel` (with `_sleep` + retry/backoff), and the `build_<x>` factory returning `CircuitBreakerChannel(...)`. Diff them against each other to find the shared pipeline (~2.5K).
2. `apps/backend/modules/notify/adapters/transport.py` - the shared transport types this is meant to host: `ChannelAdapter` protocol, the dispatcher/queue, `CircuitBreaker`, `CircuitBreakerChannel`, `mock_backoff_delay` (renamed by #270 - see handoff). The de-dup target lives beside these (~1.5K).
3. `apps/backend/modules/notify/domain/exceptions.py` - `NotificationDeliveryError` + the retry-exhausted signal the adapters raise (~0.3K).
4. `docs/standards/third-party-integration-standards.md` §1/§3 - EXT-001/EXT-003 call discipline (timeout/retries/breaker) the shared helper must not weaken (~0.5K).
5. `tests/unit/test_notify_fallback.py` + `tests/unit/test_notify_partner_terminal_consumer.py` - the notify behaviors that must stay green (find any provider-channel-specific test by grep) (~2K).

## Do NOT read

- iam's SMS adapter internals (notify owns its own port contract - module isolation), partner/audit internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Notify unit tests green (grep the exact notify test files and run those)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The two adapters are near-identical: both define a `Mock` channel (deterministic, no provider), a real `ProviderChannel` with the same `_sleep(mock_backoff_delay(attempt))` retry loop, and a `build_<x>` factory. Extract the shared pipeline into `transport.py` (or a new helper there) and let each adapter supply only its encode/decode + transport call.
- Keep the `ChannelAdapter` protocol as the seam both real channels satisfy; `CircuitBreakerChannel` already wraps either - it must stay channel-agnostic.
- Do NOT import iam's SMS adapter - notify owns its own port contract (coding-standards ADR-0003 isolation).
- Related ticket #270 (S18/S19) also edits `transport.py`: coordinator/breaker rename + backoff-helper rename. Keep this ticket's changes orthogonal to that rename to avoid merge friction (or coordinate if both land together).
- Prior art: `PHASE-5-T11` brief (#246) describes building these exact adapters - reuse its shape knowledge; the de-dup is a pure refactor of that already-landed work.
