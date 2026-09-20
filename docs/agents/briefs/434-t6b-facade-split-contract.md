# Brief - T6b PHASE-8 review-close: facade split (contract) - point wiring/tests at the two facades, delete wrapper

**Ticket:** #434 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~7.5K tokens (budget 10K) - within budget (both facade classes already loaded from T6a context)

## Scope

Phase-8 review-close T6b (facade split, contract step). App wiring and routes now construct and call the two state-machine facades directly; the thin compatibility wrapper is deleted. Test files are migrated to construct the concrete facade they exercise (consult tests use the case-console facade, rx tests the prescription facade). External behaviour is unchanged - this is purely the contract step that removes the wrapper.

Acceptance criteria (verbatim from ticket):

- [ ] The app wiring constructs both new facades on app state
- [ ] Each route reads the facade that owns its operation; no reference to the old single facade class remains anywhere
- [ ] All care test files migrate to the concrete facade they exercise; no compatibility-wrapper references remain
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run scan` green

**Blocked by:** #432 (T6a) - the two concrete facades must exist and be behaviour-identical first.

## Read-list (in order)

1. The output of T6a (#432): the two new facade classes (`CaseConsoleFacade` + `PrescriptionFacade`) with their constructor signatures and shared-helper imports - the exact constructors/call names tests and wiring must adopt. Structural/skim, already loaded in T6a. (~3.0K)
2. `app/main.py` care wiring slice (~L290-300) - replace the single `CareFacade(...)` construction with both concrete facade constructions on `app.state` (e.g. `app.state.care_console_facade`, `app.state.prescription_facade`). (~0.7K)
3. `care/adapters/routes.py` - the facade cast sites (`cast(CareFacade, request.app.state.care_facacade)` -> the owning facade per route) across all handlers. (~1.2K)
4. Care test files that construct the facade - `test_care_facade_consult.py`, `test_care_facade_rx.py`, `test_care_outbox_events.py`, `test_care_routes.py`, `test_care_lifecycle_integration.py`, `test_care_req023_gate.py`, `test_care_consent_gate.py` - migrate their constructor usages in batches (consult/outbox/lifecycle/req023 to case-console facade, rx to prescription facade; consult + rx split as appropriate). Fixture slices only, not full bodies. (~2.5K)
5. Any remaining `CareFacade`/compatibility-wrapper references across the repo (grep for the class import) - the "no reference remains" acceptance gate. (~0.1K)

## Do NOT read

- Intake/partner/iam internals, the state machines, the facade bodies beyond the two classes' public surface, `docs/archive/`.
- Anything in `docs/` - markdown-only references to the split are handled by T8b (#436), not this ticket.

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - full suite green with the migrated facade constructions
- `npm run lint`
- `npm run typecheck`
- `npm run scan`

## Handoff notes

- This is the **contract** step that deletes the T6a wrapper. Route reads, app wiring, and every test must reference only the two concrete facades; grep for the old facade class name/import to prove the "no reference remains" criterion.
- Partition rule from T6a: consult/outbox/lifecycle/req023/handshake tests -> `CaseConsoleFacade`; rx/revision/approve/reject/get-approved tests -> `PrescriptionFacade`; where a test exercises both machines (lifecycle integration), construct whichever facade owns the operation under test or both.
- Constructor seams must match T6a exactly; if a test needs both the intake dependency and health dependency, the concrete facade constructor must expose them (tie-out with #432's closing comments).
- No behavioural edits - a migration that changes a test's assertions is a flag that the split drifted; report it rather than "fixing" the test.
- `docs/architecture/internal-modules.md` §3.6/§4.1/§4.2 wording on the facade split is brought to delivered reality later by #436 (T8b); do not edit docs in this ticket.
- After deletion, confirm the module-boundary checker (in lint) still passes and no new imports across module boundaries were introduced.
