# Brief - T6 Dormant record-entry consumers

**Ticket:** #215 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Record entries start flowing from the rest of the platform before any producer goes live: MOD-003 ships idempotent subscribers for the already-named events `report.filed`, `prescription.issued/delivered`, `settlement.recorded`, each becoming a typed record entry in the patient timeline. No producer fires until Phases 8/9/11, so proof is tests emitting synthetic outbox rows through the dispatcher. Idempotency rides the module's consumed-events ledger per the round-trip contract (replay = no-op). MOD-003 also subscribes `consent.granted/revoked` to keep its effective-sharing view current.

Acceptance criteria: see #215 body verbatim.

## Read-list (in order)

1. Internal-modules §4.2 event registry rows for the four event names + MOD-003 spec subscriber duties (~1K)
2. CONTEXT.md glossary Event bus & module seams block - outbox, dispatcher, idempotent subscriber, consumed_events, round-trip, module isolation rule (~1K)
3. Round-trip integration harness test - the proof pattern you extend (~1.5K)
4. Worker composition root seam (`worker/main.py`): `_MODULE_REGISTERS` mirror assertion, `adapters.register_handlers` contract, outbox discovery (~1K)
5. Bus plumbing interfaces: `write_outbox`, envelope grammar, `record_consumed_event` dedupe semantics (~1K)
6. `docs/standards/coding-standards.md` isolation section (~0.5K)

## Do NOT read

- Producer modules' internals (care/diagnostics/settlement are dormant); IAM OTP/session internals; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; migration-check single head; backend units 654 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:integration`, `npm run migration-check`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration` (synthetic-event -> typed entries + same-event-id replay no-op + consent.\* subscription suites green)
- Boundary checker stays green via `npm run lint`

## Handoff notes

- Register the four event names in the code-side registry following the `domain.action` grammar - the doc matrix in internal-modules §4.2 is authoritative for names/spelling; repo-wide name-lint enforces.
- This is the first ticket giving a second module real handlers - the worker's mirror assertion over `MODULE_SCHEMAS` order must keep passing.
- Entries carry enough payload structure for T7's timeline rendering (type, filed-by, filed-at, summary fields per entry kind).
- Synthetic-event tests double as the seeding pattern T11 reuses.
