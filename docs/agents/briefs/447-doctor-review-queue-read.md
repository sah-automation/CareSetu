# Brief - 447 BE: doctor review queue read

**Ticket:** #447 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.2K tokens (budget 10K) - within budget

## Scope

A doctor-scoped endpoint that lists pre-summaries assigned to the calling doctor that are still awaiting review, surfaced low-confidence first and each with a confidence flag. Open care cases continue to come from the existing doctor-scoped case list; the console merges the two.

AC:

- [ ] Doctor sees assigned pre-summaries awaiting review, ordered low-confidence first
- [ ] Each queue item carries the confidence flag
- [ ] Unassigned doctors and non-doctor actors are rejected with the correct envelope code
- [ ] Route tests assert status/envelope/payload - never internal calls

## Read-list (in order)

1. `modules/intake/facade.py` - the assigned-partner scoping seam (from #443) and where an assigned-awaiting-review list is derived; the confidence flag source (~600 tokens)
2. `modules/intake/domain/presummary_machine.py` `is_low_confidence` derivation - what "low-confidence first" sorts on (~250 tokens)
3. `modules/intake/adapters/routes.py` + `require_partner`/doctor guard (`_require_doctor`) - route mounting and RBAC (~400 tokens)
4. `tests/unit/test_doctor_review_route.py` and `test_patient_intake_routes.py` - route seam-A test pattern (~700 tokens)
5. Issue #438 "backend delta 2" and user stories 11-12 (~250 tokens)

## Do NOT read

- Care consult/rx internals, consent internals, partner directory, frontend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect only the 3 known pre-existing dev-OTP env failures in `test_app_shell.py`/`test_seed_demo.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new route tests: queue returns assigned-awaiting-review ordered low-confidence first with confidence flags; unassigned doctor and non-doctor rejected.

## Handoff notes

- Depends on #443's assignment write - without it there is no assignment data; if #443 is not merged yet, this ticket cannot start (blocker is wired).
- Do not merge the case list into this endpoint; the console merges the two lists client-side.
