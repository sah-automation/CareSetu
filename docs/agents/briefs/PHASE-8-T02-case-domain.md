# Brief - T02 Case Domain - State Machine & Events

**Ticket:** #418 · **Parent:** #416 · **Refreshed:** 2026-09-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Implement the pure case lifecycle state machine, case-domain events, and registration of MOD-006 event constants in the shared event registry.

Case machine: states `PreSummary | PrescriptionPending | Closed`, actions `MARK_CONSULT_COMPLETE | CLOSE_WITHOUT_RX`, transitions enforcing the finalized-pre-summary gate on handshake, the `ConsultComplete` milestone (audited from-to transition, not a dwell state), and `CLOSE` as a deliberate terminal action requiring a close reason. A rejected draft must never auto-close.

Event constants: add `EVENT_CASE_CONSULT_COMPLETE`, `EVENT_CASE_CLOSED`, `EVENT_PRESCRIPTION_DRAFT_CREATED`, `EVENT_PRESCRIPTION_REVIEWED`, `EVENT_PRESCRIPTION_APPROVED`, `EVENT_PRESCRIPTION_REJECTED`. `EVENT_PRESCRIPTION_ISSUED` ALREADY EXISTS (line 25) - do not recreate. Promote the bare strings `"prescription.approved"` / `"prescription.rejected"` in `REGULATED_ACT_TYPES` to constants and add `EVENT_PRESCRIPTION_ISSUED` to the frozenset. `case.*` and draft/reviewed events are NOT regulated.

### Acceptance criteria

- [ ] Case state machine has exhaustive status x action matrix with `IllegalCareTransitionError` for illegal edges
- [ ] Consult-complete gate rejects when pre-summary is not finalized
- [ ] Close-without-RX is terminal and requires a reason
- [ ] All new MOD-006 event constants registered in `bus/events.py` using `EVENT_` prefix
- [ ] Bare strings in REGULATED_ACT_TYPES promoted; `EVENT_PRESCRIPTION_ISSUED` added to frozenset; `case.*`/draft/reviewed NOT added
- [ ] `check_event_names.py` and `check_module_boundaries.py` tests pass
- [ ] Case machine pure tests pass

## Read-list (in order)

1. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - canonical term names for `case stage`, `consult complete milestone`, `close-without-prescription` (~0.5K)
2. `apps/backend/modules/intake/domain/state_machine.py` - reference pattern: `IntakeStatus` enum, `IntakeAction` enum, `transition()` function, `IllegalIntakeTransitionError` (~1.5K tokens)
3. `apps/backend/modules/intake/domain/events.py` - event payload pattern: Pydantic `BaseModel`, no-PHI, envelope builders (~0.8K tokens)
4. `apps/backend/bus/events.py` - current registry: `EVENT_` prefix convention, existing `EVENT_PRESCRIPTION_ISSUED`, `REGULATED_ACT_TYPES` frozenset and its scope comment (~1K tokens)
5. `apps/backend/modules/care/domain/exceptions.py` - current scaffold: `CareError` base class (~0.2K tokens)
6. `docs/architecture/internal-modules.md` section 3.6 (lines 358-361) - case machine states and transitions (~0.3K tokens)
7. `apps/backend/modules/care/schema/models.py` - table column names for status enum values (~0.3K tokens)

## Do NOT read

- `apps/backend/modules/care/facade.py` (empty scaffold, not needed)
- Intake facade (too large, not needed for pure domain)
- Routes, tests, prototype HTML
- Prescription domain (separate ticket)

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `python -m pytest tests/unit/test_care_case_state_machine.py -v && python -m pytest tests/unit/test_event_names.py tests/unit/test_check_module_boundaries.py -v`

## Handoff notes

- The `care` domain exceptions module already has `CareError` - extend it with `IllegalCareTransitionError` following the `IllegalIntakeTransitionError` pattern.
- Follow the intake state machine file structure: frozen module-level state/action enums, `transition(current, action, **context)` function, exhaustive parametrized matrix test.
- The `ConsultComplete` milestone is an audited transition recording (from-state, to-state, timestamp, doctor), NOT a state the case dwells in.
- Event constants to add, using the `EVENT_` prefix (matching `EVENT_INTAKE_STARTED` etc.): `EVENT_CASE_CONSULT_COMPLETE`, `EVENT_CASE_CLOSED`, `EVENT_PRESCRIPTION_DRAFT_CREATED`, `EVENT_PRESCRIPTION_REVIEWED`, `EVENT_PRESCRIPTION_APPROVED`, `EVENT_PRESCRIPTION_REJECTED`. `EVENT_PRESCRIPTION_ISSUED` already exists - reference it, never redefine.
- REGULATED_ACT_TYPES: promote the bare `"prescription.approved"` / `"prescription.rejected"` (events.py lines 126-127) to the constants and add `EVENT_PRESCRIPTION_ISSUED`. Do NOT add `case.*`, `prescription.draft_created`, or `prescription.reviewed` - only issuance/rejection are regulated acts (events.py line 117 comment).
