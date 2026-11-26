# Brief - 695 A2 - Trace-context propagation API -> outbox -> worker

**Ticket:** #695 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Carry a W3C `traceparent` across the async seam so the worker's log/trace context links back to the originating API request. The API already mints a trace id; the outbox does not carry one today. Add a nullable `traceparent` to the shared outbox DDL (one additive migration across all module outbox tables), have the outbox writer populate it from the request context, and have the dispatcher/worker adopt it when processing the row. Demonstrable end to end by asserting the same trace id appears in the API request and the worker's handling of the resulting event.

Acceptance criteria (verbatim):

- [ ] Shared outbox DDL adds a nullable `traceparent`; a single additive migration adds it to every existing outbox table (single-head gate stays green).
- [ ] The outbox writer writes the current request's `traceparent`; a row with none stays null.
- [ ] The worker/dispatcher restores the propagated context before handling, so the id is visible on worker-side log lines.
- [ ] A round-trip test asserts the propagated id survives API -> outbox -> dispatcher.
- [ ] `npm run migration-check`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. `bus/outbox_ddl.py` `outbox_table(table_name, schema, metadata)` - the single shared outbox column contract to extend with a nullable `traceparent`; `tests/unit/test_outbox_ddl.py` pins the exact column set and must be updated with it (~1K).
2. `bus/outbox_writer.py` `write_outbox(connection, schema, table_name, envelope)` - the write point that must populate `traceparent` from the current request context (and leave it null when none) (~0.4K).
3. `bus/envelope.py` `Envelope` - the typed-seam contract; decide whether the id rides a new envelope field or a separate context accessor, without breaking the "typed payload, no raw dicts" rule (~0.8K).
4. `bus/dispatcher.py` `OutboxRow`, `claim_pending_rows` (its `RETURNING` list), `envelope_from_row`, and `process_outbox_table` - the claim/reconstruct points that must carry `traceparent` and restore the context around `dispatch` before handlers run (~2.5K of a ~4.6K file).
5. `app/gateway/trace.py` `resolve_trace_id` / `TraceMiddleware` - the API-side trace id source; derive a valid W3C `traceparent` (the minted id is a 32-hex token) from it (~0.7K).
6. A schema-init migration for precedent - `v2_0__init_health` shows the raw `op.execute` DDL idiom and the per-module outbox shape; the naming scheme is `vN_M__label` and `npm run migration-check` enforces a single head + no cross-schema FK (~1.3K).
7. `tests/integration/test_round_trip.py` and `tests/unit/test_outbox_writer.py` / `tests/unit/test_dispatcher.py` - the round-trip and row-contract harness the new propagation test extends (~1.3K).
8. Parent plan `docs/plans/plan-phase14-observability.md` §5 (trace propagation into the worker - the key gap) and §15 (migration complexity risk) (~0.6K).

## Do NOT read

- Domain module internals, facades, or adapters.
- Frontend.
- Unrelated migrations.
- The OTel SDK code (A3) - this ticket only carries the id; A3 consumes it.

## Baseline verify (must pass before the first edit)

- `npm run migration-check` - PASS on the current tree (single head + cross-schema-FK scan clean).
- `npm run test:unit:backend` - PASS (2925 passed).
- (Harness context: `npm run test:unit:frontend` - all 1910 tests in 133 files pass, but vitest exits non-zero with a worker-timeout error; environment flake, not a test failure. Not needed for this ticket.)

## Done-verify (acceptance criteria -> commands)

- `npm run migration-check` - single head, migration applies/adds the column to every outbox table, FK scan clean.
- `npm run test:unit:backend` - green, including the updated outbox-DDL column contract and the new propagation round-trip test.
- Round-trip: assert the trace id written in the API request is the id visible when the dispatcher handles the resulting row.

## Handoff notes

- **Blocked by A1 (#694):** the propagated id is only observable on worker log lines once structlog carries `trace_id`. Build A1 first.
- **One additive migration, every outbox table.** The outbox shape is materialized identically in each `<module>_outbox` table across `MODULE_SCHEMAS` (`bus/bootstrap.py`). A single migration must `ALTER TABLE <schema>.<module>_outbox ADD COLUMN traceparent TEXT` for every existing outbox table; add it to the shared `outbox_table(...)` DDL at the same time so future tables get it too. Keep it nullable - a row written with no request context stays null.
- **Precedent shape:** migrations recreate DDL rather than importing source (migration-immutability rule); follow the raw `op.execute` style of `v2_0__init_health`. Rows/tables are discovered by the `<module>_outbox` naming pattern; enumerate them deliberately, not dynamically at migration time.
- **Do not make `traceparent` non-null.** The contract explicitly allows a null (no request context); the writer sets it only when a trace context exists.
- **Restore before handlers run, not after.** The dispatcher reconstructs a typed envelope from the claimed row and calls `bus.dispatch.dispatch`. Bind the restored trace context (a `ContextVar` or equivalent, shared with A1's logging bridge) around the dispatch call so the handler's log lines and any downstream work inherit the originating request's id.
- **W3C format.** A valid `traceparent` is `00-<32 hex trace-id>-<16 hex parent-id>-<01>`; the existing `resolve_trace_id` output is a 32-hex value suitable as the trace-id segment. Validate/guard it like the existing `_is_safe_trace_id` helper so a malformed id never enters the seam.
- **Single-head gate.** New migration revision links to the current head (`v8_18`-era); `npm run migration-check` must stay green (linear history, no cross-schema FK).
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
