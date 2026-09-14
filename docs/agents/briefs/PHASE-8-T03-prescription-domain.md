# Brief - T03 Prescription Domain - State Machine & Drafting Cap

**Ticket:** #419 · **Parent:** #416 · **Refreshed:** 2026-09-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Implement the pure prescription lifecycle state machine, drafting-cap logic, revision-freeze semantics, and prescription-domain event payload models.

Prescription machine: states `Draft | DoctorReviewed | ApprovedIssued | Fulfilled` with branch `Rejected`, actions `CREATE_DRAFT | SAVE_REVISION | APPROVE | REJECT | FULFILL`. Key invariants: approval freezes exactly the current working revision; declaration-less approval rejected; rejection requires reason; `Fulfilled` is inbound from Phase 10 (stub).

Drafting cap: max 3 attempts (2 rejections). Cap limits only AI draft generation - manual authoring always open.

### Acceptance criteria

- [ ] Prescription state machine has exhaustive status x action matrix with illegal-transition errors
- [ ] Approval requires `verification_declaration = true`; rejection requires a reason
- [ ] Drafting cap blocks 3rd AI draft but allows manual authoring at any time
- [ ] Revision-freeze invariant: issued items must match saved revision, not raw draft
- [ ] All prescription events have Pydantic payload models
- [ ] Pure tests pass

## Read-list (in order)

1. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - canonical `prescription source`, `draft snapshot`, `drafting cap`, `e-prescription` terms the machine enums must match (~0.5K)
2. `apps/backend/modules/intake/domain/state_machine.py` - reference pattern for machine structure (~1.5K tokens)
3. `apps/backend/modules/intake/domain/presummary_machine.py` - second-machine precedent in same module (~0.8K tokens)
4. `apps/backend/modules/care/domain/state_machine.py` - ticket 02's case machine for shared exception class and file layout (~1K tokens)
5. `apps/backend/modules/care/schema/models.py` - table columns for status enums: `care_prescriptions.status`, `care_prescriptions.source` (~0.3K tokens)
6. `apps/backend/modules/care/domain/events.py` - ticket 02's event models for the payload pattern (~0.5K tokens)
7. `docs/architecture/internal-modules.md` section 3.6 (lines 360-361) - prescription machine states, transitions, `edited_yn` (~0.3K tokens)

## Do NOT read

- `apps/backend/modules/care/facade.py` (empty scaffold)
- Intake facade, routes, tests
- Case domain (separate ticket, only need the exception class)
- Prototype HTML

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `python -m pytest tests/unit/test_care_prescription_state_machine.py -v`

## Handoff notes

- Place the prescription machine in `care/domain/prescription_machine.py` (or extend `state_machine.py` if that better fits the module pattern - check ticket 02's decision).
- The drafting cap is a pure function: `can_create_draft(rejected_count: int) -> bool` where `rejected_count < 2` (max 2 rejections = 3 attempts total).
- Revision-freeze is a data invariant, not a state machine transition - it is enforced at the facade layer. The state machine only models the legal status transitions.
- `edited_yn` derivation: compare `issued rx_items` against `draft_snapshot` - if any field differs, `edited_yn = true`. This is facade logic, not machine logic.
- `Fulfilled` is a terminal state that only arrives via inbound event from Phase 10 - the machine should accept the transition but no action in this ticket triggers it.
