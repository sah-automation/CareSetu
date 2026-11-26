# Brief - T04 CareFacade - Consultation Workflow

**Ticket:** #420 · **Parent:** #416 · **Refreshed:** 2026-09-14 (re-cut: added `get_finalized_pre_summary` seam)
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The consultation half of `CareFacade` PLUS the intake-facade seam it depends on.

**New seam (this ticket):** implement `IntakeFacade.get_finalized_pre_summary(...)` - does not exist today. Returns only `final`-state summaries; raises otherwise. Per issue #416 Further Notes, must be confirmed before wiring the handshake gate.

Methods: `mark_consult_complete`, `get_case`, `list_doctor_cases`, `submit_doctor_input`. All same-transaction outbox writes, typed Pydantic returns, doctor attribution.

### Acceptance criteria

- [ ] `IntakeFacade.get_finalized_pre_summary` returns only `final` summaries and raises otherwise
- [ ] `mark_consult_complete` rejects when pre-summary is not finalized (calls the new seam)
- [ ] `mark_consult_complete` transitions case to PrescriptionPending and publishes `case.consult_complete`
- [ ] `get_case` returns typed `CaseDetailView`; `list_doctor_cases` returns only open cases
- [ ] `submit_doctor_input` records input and validates case state
- [ ] All methods write outbox in same transaction as the domain write
- [ ] Facade unit tests pass with faked engine

## Read-list (in order)

1. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - canonical `care case`, `case stage`, `consult complete milestone`, `finalized pre-summary`, `doctor input` (~0.5K)
2. `apps/backend/modules/intake/facade.py` - reference pattern: constructor `engine: AsyncEngine`, `async with self._engine.begin()` transaction, `write_outbox()` call, typed Pydantic return; also where `get_finalized_pre_summary` must be added (~2K tokens - constructor + one full method + outbox write pattern only, skip rest)
3. `apps/backend/modules/intake/intake_models.py` + `apps/backend/modules/intake/schema/models.py` - the pre_summary table/three-state review columns (`review_state`) for the new getter (~0.8K)
4. `apps/backend/modules/care/facade.py` - current empty scaffold (~0.1K tokens)
5. `apps/backend/modules/care/schema/models.py` - care table column names for INSERT statements (~0.5K tokens)
6. `apps/backend/modules/care/domain/state_machine.py` - case machine from ticket 02: `CareCaseStatus`, `CareCaseAction`, `transition()` (~0.8K tokens)
7. `apps/backend/modules/care/care_models.py` - DTOs from ticket 01: `CaseDetailView`, `DoctorInputResult` (~0.5K tokens)
8. `apps/backend/modules/care/outbox.py` - `CARE_OUTBOX_TABLE` constant (~0.1K tokens)

## Do NOT read

- Intake routes (not needed)
- Prescription domain (separate ticket)
- Partner facade (only need `resolve_partner` signature, will grep)
- Consent facade, health facade
- Prototype HTML

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `python -m pytest tests/unit/test_care_facade_consult.py -v`

## Handoff notes

- Constructor signature: `CareFacade(engine: AsyncEngine, intake_facade: IntakeFacade, ...)` - use `TYPE_CHECKING` import for `IntakeFacade` to avoid circular deps.
- `mark_consult_complete` must call `intake_facade.get_finalized_pre_summary(pre_summary_id)` to gate on finalized state. If it raises, the handshake is blocked.
- `get_finalized_pre_summary` return shape: reuse an existing `PreSummaryView`/result model if one fits, else a small typed Pydantic result. It must throw on non-`final` (never return a working copy). The T08 ticket no longer implements this - it lives here.
- The `ConsultComplete` milestone is recorded as a row/field on `care_cases` (e.g., `consult_completed_at`, `consult_completed_by`) - not a separate table.
- Same-transaction outbox: the domain INSERT and `write_outbox()` call happen inside the same `async with engine.begin()` block.
- Doctor attribution: all writes record `doctor_id` (the `partner_id` from the authenticated doctor).
- Deferred (not this ticket): Redis caching of the doctor's pending-cases list noted in internal-modules §3.6 - out of issue #416 scope.
