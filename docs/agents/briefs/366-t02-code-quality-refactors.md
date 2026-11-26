# Brief - 366 T02 Code quality refactors: typed models, breaker helper, status guard

**Ticket:** #366 · **Parent:** #364 · **Refreshed:** 2026-09-09
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Three independent code-quality refactors batched as one slice. All pure refactors - no behavioral change.

1. **Typed models (S1)** - typed Pydantic models replace `dict[str, Any]` at cross-module boundaries.
2. **Circuit-breaker helper (S2)** - the three copy-pasted methods on `CircuitBreakerAiGateway` deduplicate into one generic helper.
3. **Status guard (S8)** - `re_record_intake` explicitly checks the intake is in `re_record` status before transitioning.

Acceptance criteria (from ticket):

### Typed models (S1)

- [ ] New `StructuredFields(chief_complaints: list[str], symptoms: list[str], duration: str | None)` model in `intake_models.py`
- [ ] New `ClinicalEdits = dict[str, str | list[str]]` type alias
- [ ] Five `dict[str, Any]` fields replaced: `PreSummaryView.structured_fields`, `.patient_edits`, `.doctor_corrections`, `PatientEditsResult.patient_edits`, `PreSummaryReviewResult.reviewed_copy`
- [ ] Pipeline adapter constructs `StructuredFields(...)` instead of a raw dict
- [ ] Frontend `api.ts` types updated to match

### Circuit breaker helper (S2)

- [ ] `_run_with_breaker(name, fn)` generic helper on `CircuitBreakerAiGateway`
- [ ] `transcribe()`, `structure()`, `draft_rx()` are one-liner delegations through the helper
- [ ] `@observe` decorators preserved on each public method
- [ ] Existing `test_ai_gateway_mock.py` tests pass unchanged

### Status guard (S8)

- [ ] `re_record_intake` checks `current.status is not IntakeStatus.RE_RECORD` after reading the intake row, raises `IllegalIntakeTransitionError` with a message naming the current status
- [ ] Guard runs before the attempt-cap check
- [ ] Unit test: call `re_record_intake` on an intake in `captured` status -> `IllegalIntakeTransitionError`

### Cross-cutting

- [ ] `npm run typecheck` passes (mypy strict + tsc)
- [ ] `npm run test:unit:backend` passes

## Read-list (in order)

1. `apps/backend/modules/intake/intake_models.py` - `PreSummaryView` (lines 115-138), `PatientEditsResult` (140-153), `PreSummaryReviewResult` (155-178); the five `dict[str, Any]` fields (~1.5K tokens)
2. `apps/backend/modules/intake/adapters/ai_provider_ext.py` - `CircuitBreakerAiGateway` class (lines 209-306), its `_allow`/`_record`/`transcribe`/`structure`/`draft_rx` and the `@observe` decorators (~2.5K tokens)
3. `apps/backend/modules/intake/facade.py` - `re_record_intake` (lines 248-358) to add the status guard before the cap check (~1.7K tokens)
4. `apps/backend/modules/intake/domain/state_machine.py` - `IntakeStatus` enum (RE_RECORD) and `MAX_RECORD_ATTEMPTS` (~1K tokens)
5. `apps/backend/modules/intake/domain/exceptions.py` - `IllegalIntakeTransitionError` (~0.4K tokens)
6. `apps/frontend/src/lib/intake/api.ts` - the API client types for `structured_fields`/`pre_summary` to align (~1.5K tokens)
7. Where `structured_fields` is constructed: `adapters/pipeline.py` (post-T01) - the `StructuredFields(...)` construction site (~0.5K tokens)

## Do NOT read

- Event definitions (`domain/events.py`), routes, media store, budget meter
- `docs/archive/`, other modules

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck:backend` clean (mypy strict) + `npm run typecheck -w @caresetu/frontend` (tsc; the api.ts type change is verified here - note full `typecheck` also runs the stale `.next` artifact which is unrelated)
- `npm run test:unit:backend` - existing `test_ai_gateway_mock.py`, facade, and intake_models tests pass
- New unit test asserting `re_record_intake` on a non-`re_record` intake raises `IllegalIntakeTransitionError`

## Handoff notes

- Independent - has no blockers; can start immediately (parallel with T01/T07).
- The three sub-fixes are independent of each other; land them in whichever order is cleanest, but do not change behavior.
- `@observe` decorators must survive on `transcribe()`, `structure()`, `draft_rx()` (Langfuse tracing gate, AI engineering standards A7) - the helper itself needs no `@observe`.
- Frontend change is type-alignment-only in `api.ts`; do not alter the re-record/polling UI flow.
- The `structured_fields` construction currently lives in the pipeline adapter; after T01 lands it lives in `pipeline.py`.
