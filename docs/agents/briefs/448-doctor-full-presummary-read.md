# Brief - 448 BE: doctor full pre-summary read

**Ticket:** #448 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.2K tokens (budget 10K) - within budget

## Scope

A doctor-scoped read that returns the full pre-summary content - structured summary, symptoms, confidence flag, review state - to the doctor to whom the intake is assigned. Today every pre-summary read is patient-only and the care-case view returns only the pre-summary id.

AC:

- [ ] The assigned doctor reads the full pre-summary for their intake (structured summary, symptoms, confidence flag, review state)
- [ ] Other actors and unassigned doctors are rejected
- [ ] Route tests assert status/envelope/payload; no other pre-summary reads are affected

## Read-list (in order)

1. `modules/intake/facade.py` - the existing patient-only pre-summary read and the assigned-partner scoping seam (from #443); the doctor-scoped sibling to add (~700 tokens)
2. `modules/intake/domain/presummary_machine.py` - `PreSummaryStatus` and `is_low_confidence` for the review-state + confidence payload (~250 tokens)
3. `modules/care` case view that currently returns only the pre-summary id - the contrast proving why this read is new (~250 tokens)
4. `modules/intake/adapters/routes.py` + doctor guard (require doctor / assignment check) - route mounting and RBAC (~450 tokens)
5. `tests/unit/test_doctor_review_route.py` / `test_patient_intake_routes.py` - route seam-A test pattern (~600 tokens)
6. Issue #438 "backend delta 3" and user story 13 (~250 tokens)

## Do NOT read

- Care rx internals, consent internals, partner directory, frontend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect only the 3 known pre-existing dev-OTP env failures in `test_app_shell.py`/`test_seed_demo.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new route tests: assigned doctor reads full content; other doctors and non-doctors rejected; patient-facing pre-summary read unchanged.

## Handoff notes

- Depends on #443 (assignment scoping). The endpoint is a new surface, not a change to existing patient reads.
- The review action lives in #442; this read only returns state - it does not mutate.
