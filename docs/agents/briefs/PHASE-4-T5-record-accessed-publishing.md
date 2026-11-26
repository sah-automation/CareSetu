# Brief - T5 record.accessed event publishing (MOD-003)

**Ticket:** #238 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Add `record.accessed` event publishing from MOD-003 (Health) so that every record read triggers an audit event for MOD-011's hash chain AND a direct write to `health.record_access_history` for the patient view. This is the dual-write pattern: outbox event for the audit chain, local table for fast patient queries.

Acceptance criteria: see #238 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/health/facade.py` - current `HealthFacade` with `_log_access()` and record read methods (~3K)
2. `apps/backend/modules/health/adapters/__init__.py` - existing subscriber pattern for reference (~1.5K)
3. `apps/backend/bus/events.py` - existing event constants (~0.3K)
4. `apps/backend/bus/envelope.py` - `Envelope` type for event publishing (~0.5K)
5. `apps/backend/bus/outbox_writer.py` - `write_outbox()` helper (~0.3K)
6. `docs/architecture/internal-modules.md` - MOD-003 section and event registry (~1K)

## Do NOT read

- MOD-011 code (beyond the schema from T1), other module code, bus infrastructure internals, docs/archive/.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (record.accessed tests green)

## Handoff notes

- Add `EVENT_RECORD_ACCESSED = "record.accessed"` to `bus/events.py`.
- In MOD-003 facade's record read paths (`get_own_record()`, `read_consented_history()`, or the internal `_log_access()` helper): write an `audit.event` envelope to MOD-003's outbox in the SAME transaction as the record read.
- The `health_record_access_history` direct write already exists in `_log_access()` -- verify it populates the new T1 table columns correctly.
- Event payload: `record_id`, `actor_id`, `actor_type`, `scope`, `accessed_at`, with `metadata` containing optional `denied` and `denial_reason` for denied attempts.
- `record_view_denied` is a separate event type for denied access attempts -- publish it when a read is denied.
- No cross-schema imports; the outbox event is consumed by MOD-011 through the dispatcher.
