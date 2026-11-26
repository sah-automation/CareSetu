# Brief - T12 Partner terminal-status notifications (WhatsApp/SMS fallback)

**Ticket:** #255 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Terminal-status notifications for partners (ADR-0009): when a partner reaches `[Active]` or `[Rejected]` (with the specific reason on reject), they are notified WhatsApp-first via EXT-003, falling back to SMS via EXT-001 when the EXT-003 delivery webhook reports failure/undeliverable (the channel engine from T11). Non-terminal updates (`Under Verification`, re-submission confirmations) stay in-app only.

From the user's perspective: a partner is told through WhatsApp (or SMS if WhatsApp cannot reach them) the moment they are activated, or exactly why they were rejected.

Implementation:

- Subscribe (in the notify module or a notify-facing handler) to `partner.activated` and `partner.rejected`; map each to the appropriate notification template.
- Route through the T11 send-with-fallback channel (WhatsApp first, SMS on `notification.failed`).
- Terminal statuses only - no notifications for `Under Verification` or re-submission confirmations.

Acceptance criteria (verbatim from #255):

- [ ] `partner.activated` triggers a WhatsApp-first -> SMS-fallback notification
- [ ] `partner.rejected` triggers a notification carrying the specific rejection reason (WhatsApp-first -> SMS fallback)
- [ ] Non-terminal statuses (`Under Verification`, re-submission confirms) produce no terminal notification (in-app only)
- [ ] The EXT-003 `notification.failed` signal routes a message to SMS fallback
- [ ] Unit + integration test covers the event -> notify chain (mirroring the event-chain test style)

## Read-list (in order)

1. `modules/notify/facade.py` + `modules/notify/adapters/__init__.py` - the T11-built `NotifyFacade.send_with_fallback` primitive and `register_handlers`; add the `partner.activated` / `partner.rejected` subscribers here (~0.7K)
2. `apps/backend/bus/events.py` - the T04-promoted `partner.activated`, `partner.rejected` constants + the T11 `notification.failed` constant; confirm the event names and payload builders (~0.5K)
3. `modules/audit/adapters/__init__.py` - the canonical consumer pattern to mirror: `register_payload_model` + ledged-idempotent handler + `_run_handler` boilerplate (~0.8K)
4. `apps/backend/worker/main.py` - composition root; confirms `notify_register_handlers` is wired (no change) and shows where a new notify handler registers (~0.5K)
5. `docs/standards/third-party-integration-standards.md` - EXT-001/EXT-003 discipline the channel engine enforces (delivery webhook drives fallback) (~0.3K)
6. `tests/unit/test_audit_consumer.py` (handler slices) + a T11 notify test - the event-chain test pattern to mirror (~1K)

## Do NOT read

- iam internals, audit append internals, `docs/archive/`. The notify module only consumes partner events - it never touches the partner schema or emits audit events.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- New event -> notify unit/integration test green (subset of unit suite)
- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run test:integration`

## Handoff notes

- Blocked by #246 (T11 - the fallback channel engine this ticket routes through) and #252 (T08 - emits `partner.activated` / `partner.rejected`). Do not begin until both land.
- ADR-0009 governs: terminal statuses only. `Under Verification` and re-submission confirmations are in-app only - no WhatsApp/SMS cost, no notify event. Enforce this explicitly in the subscriber (ignore non-terminal events).
- The rejection notification MUST carry the specific rejection reason (FEAT-014 acceptance) - pull it from the `partner.rejected` event payload.
- Handler pattern mirrors `modules/audit/adapters/__init__.py`: register the payload model for each partner terminal event, register a ledged `record_consumed_event`-guarded handler that calls `NotifyFacade.send_with_fallback`. The notify-dedup handling follows T11's idempotency (a redelivered event is a no-op).
- Landing in notify's own `register_handlers` keeps module isolation (partner never imports notify; the notify-facing handler subscribes to partner bus events).
- Prior art: ADR-0009 fallback chain, the audit module's consumer-handler pattern (PHASE-4 T4, #239).
