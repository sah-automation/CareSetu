# Brief - 445 BE: doctor working prescription read

**Ticket:** #445 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.7K tokens (budget 10K) - within budget

## Scope

A doctor-scoped read that returns the current in-progress prescription revision for a care case - Draft, DoctorReviewed, or rejected revision - so a pending case can be reloaded safely. Today only the issued prescription is readable.

AC:

- [ ] A doctor assigned to the case can read the current in-progress prescription revision
- [ ] The read returns the correct revision and items regardless of Draft, DoctorReviewed, or rejected state
- [ ] The issued-prescription path remains intact for a PrescriptionPending or Closed case
- [ ] Other actors and unassigned doctors are rejected; route tests assert the observable contract

## Read-list (in order)

1. `modules/care/rx_facade.py` - the approved-prescription read and how revisions + `rx_items` are stored; the new working-read sibling (~700 tokens)
2. `modules/care/domain/prescription_machine.py` - the Draft / DoctorReviewed / Rejected states and what holding a "rejected revision" means (~500 tokens)
3. `modules/care/adapters/routes.py` doctor-case guard pattern (`_require_doctor`, case ownership) - where the new route mounts (~500 tokens)
4. `tests/unit/test_care_routes.py` and the req023 gate test - route seam A pattern for rx reads (~800 tokens)
5. `CONTEXT.md` e-prescription / draft snapshot / revision-freeze approval glossary + Issue #438 "backend delta 5" (~400 tokens)

## Do NOT read

- Intake/consent/partner modules, prescription editing mutation internals beyond the read path, frontend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect only the 3 known pre-existing dev-OTP env failures in `test_app_shell.py`/`test_seed_demo.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new route tests cover the in-progress read across Draft/DoctorReviewed/Rejected states, unassigned-doctor rejection, and that approved-rx reads are unchanged.

## Handoff notes

- This is the reload seam #452 (frontend workspace drafting) consumes; the payload is the working revision - the same row the revision-save mutation writes, not the draft snapshot.
- Preserve the existing issued-prescription read exactly; do not merge the two into one endpoint.
