# Brief - 402 T05 Pre-summary review_state three-state reconciliation

**Ticket:** #402 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The pre-summary schema stops admitting the phantom fourth state. A corrective alembic migration (a NEW revision - the v7.0 migration is not rewritten because the live DB already migrated under #373) relaxes the `intake_pre_summaries.review_state` CHECK to exactly `('draft','reviewed','final')`. Stale model comments describing `review_required` are corrected, the schema test asserts exactly three states, and `npm run migration-check` passes. Acceptances: new revision relaxes the CHECK; model comments corrected + schema test asserts exactly three values; `npm run migration-check` passes.

## Read-list (in order)

1. `modules/intake/schema/models.py` - `intake_pre_summaries.review_state` CHECK `ck_intake_pre_summaries_review_state` (:127-130) + stale comments (:108-110) (~1K)
2. The latest migration head pattern - `apps/backend/alembic/versions/9f3c7cd8a409_v7_1__intake_reviewed_by.py` (how a corrective revision is written); v7.0 `6cb15f638bec_v7_0__init_intake.py` (:93-96) to see the CHECK in DDL (~1K)
3. `modules/intake/domain/presummary_machine.py` - the three-state truth (`PreSummaryStatus`: draft/reviewed/final only, ADR-0001) (~0.7K)
4. `tests/unit/test_intake_schema.py` - `test_pre_summaries_review_state_check` (:83-86, currently pins the phantom) (~0.5K)

## Do NOT read

- Pipeline/adapters/facade code, frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run migration-check` - single head 9f3c7cd8a409 OK (verified 2026-09-13)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run migration-check` - single head on the new revision, cross-schema-FK gate OK
- `npm run test:unit:backend` - schema test asserts exactly three `review_state` values

## Handoff notes

- Corrective revision, never an edit to v7.0 - the live database already applied v7.0
- `review_required` must end up in exactly zero places: migration, model, comments, tests
- The three-state machine and ADR-0001 (forced doctor review via `low_confidence` flag) are binding; do not touch `domain/presummary_machine.py` transitions
