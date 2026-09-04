# Brief - T4 Consumer handler for audit events

**Ticket:** #239 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Wire up MOD-011's event subscriber to consume `audit.event` from all modules, filter regulated acts, compute the hash chain, and append to `audit_events`. This is the core audit engine that ties together the schema (#235), hash chain (#236), and filter (#237) logic.

Acceptance criteria: see #239 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/audit/adapters/__init__.py` - current empty `register_handlers()` (~0.3K)
2. `apps/backend/modules/audit/facade.py` - current empty `AuditFacade` (~0.2K)
3. `apps/backend/modules/audit/schema/models.py` - schema models from T1 (~0.5K)
4. `apps/backend/modules/health/adapters/__init__.py` - canonical subscriber pattern, the reference implementation (~2K)
5. `apps/backend/bus/ledger.py` - `record_consumed_event()` helper (~0.5K)
6. `apps/backend/bus/registry.py` - `HandlerRegistry` interface (~0.5K)
7. `apps/backend/bus/outbox_writer.py` - `write_outbox()` for any outbound events (~0.3K)
8. `apps/backend/worker/main.py` - composition root, already imports audit handlers (~0.5K)
9. T2's `compute_audit_hash()` and `GENESIS_HASH` - read from the file T2 creates (~0.5K)
10. T3's `is_regulated_act()` - read from the file T3 creates (~0.3K)

## Do NOT read

- Other module code beyond health's adapter pattern, bus infrastructure internals, docs/archive/.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all consumer handler tests green)

## Handoff notes

- Register handler for `EVENT_AUDIT_EVENT = "audit.event"` in `register_handlers()`.
- Handler flow: `record_consumed_event()` -> check `delivered` -> `is_regulated_act()` -> if operational, skip -> if regulated, compute hash -> append to `audit_events`.
- For the hash: the handler needs the `prev_hash` of the most recent row. Query `SELECT hash FROM audit.audit_events ORDER BY timestamp DESC LIMIT 1` (or use a cached in-memory value if single-threaded).
- First row uses `GENESIS_HASH` as `prev_hash`.
- Idempotency: `consumed_events` ledger with `ON CONFLICT DO NOTHING` -- same pattern as every other module.
- The handler does NOT publish `audit.tamper_detected` events (that's a future concern). Focus on consuming and appending only.
- Worker composition root already has `audit_register_handlers` in `_MODULE_REGISTRIES` -- no changes needed there.
