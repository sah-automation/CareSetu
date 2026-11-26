# Brief - #718 Consolidate observability integration fixtures

**Ticket:** #718 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The three observability round-trip integration tests each carry their own module-scoped alembic migration fixture and their own inline truncation list. Consolidate them into the shared integration conftest, so the Batch 3 round trips extend one fixture instead of adding a fourth copy.

- [ ] The migration fixture and the table-cleaning helper live in the shared integration conftest; the three existing round-trip files consume them.
- [ ] None of the three files declares its own migration fixture or truncation constant any more.
- [ ] Coverage is unchanged: every existing test in the three files still passes and still asserts the same thing.
- [ ] `npm run test:integration` is green before and after.

## Read-list (in order)

1. `tests/integration/conftest.py` - the session fixtures (`database_url`, `db_engine`, `reachable_db`, `throwaway_schema`) and the skip-when-unreachable convention. (~0.6K)
2. The three round-trip files - `test_observability_consumer_round_trip.py`, `test_observability_rollup_round_trip.py`, `test_observability_read_routes_round_trip.py`: each declares a module-scoped migration fixture that upgrades to head and downgrades to base, plus a truncation constant/fixture. Note they truncate _different_ table sets today. (~2.5K)
3. `tests/integration/README.md` - the documented reason integration tests skip when PostgreSQL is unreachable. (~0.3K)
4. The migration gate contract - `scripts/migration-check.cjs` and the cross-schema FK scanner it calls, so the fixture you lift preserves the same migration path. (~0.6K)
5. Spec #717, Testing Decisions + Implementation Decision 46 (consolidated integration fixtures). (~0.8K)

## Do NOT read

- `tests/unit/**` - no unit suite changes here.
- Frontend sources.
- `docs/archive/`.
- The observability read queries, the rollup domain, and the consumer handlers - you are moving fixtures, not behaviour.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration` (skips cleanly when PostgreSQL is unreachable; that skip is an acceptable baseline, but a _failure_ is not)
- `npm run migration-check`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` - same tests, same assertions, one fixture.
- `npm run test:unit:backend`
- `npm run lint`

## Handoff notes

- If a named interface no longer resolves, re-grep by name (`migrated_schema`, `clean_tables`, `_TRUNCATE`) and refresh this brief rather than guessing.
- Keep the per-file table-set differences expressible: the three files truncate different tables today. Either widen the shared helper to take a table list, or make the shared fixture truncate the union and let each file narrow it. Do not silently drop a table from any file's cleanup - that turns a green suite into a flaky one.
- This brief is the shared fixture's first consumer test surface: Batch 3 tickets #723, #726 and #739 all extend it.
