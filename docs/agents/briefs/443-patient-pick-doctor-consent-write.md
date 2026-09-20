# Brief - 443 BE: patient pick-a-doctor + consent write

**Ticket:** #443 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.8K tokens (budget 10K) - within budget

## Scope

The patient pick-a-doctor write: a patient-scoped endpoint accepts a chosen partner id against an intake, records the choice and the consent grant atomically (consent-at-pick, MOD-004), and thereafter the pre-summary is assigned to that doctor so only that doctor sees the patient's health information.

AC:

- [ ] An authenticated patient can pick exactly one doctor for an intake
- [ ] The pick and the consent grant are recorded in the same transaction, in one step, with no second gate
- [ ] After the pick, the pre-summary is assigned to the chosen doctor; cross-actor and unassigned-doctor reads are rejected
- [ ] Route tests assert only the observable contract: status code, envelope code, and payload - never internal calls

## Read-list (in order)

1. `modules/intake/facade.py` review surface - the existing patient-facing seams this new pick writes alongside; where `assigned-partner scoping` gets recorded (~600 tokens)
2. `modules/consent/facade.py` `ConsentFacade.grant_consent` and the MOD-004 consent-gate design - the grant lineage/version contract the pick must satisfy atomically (~500 tokens)
3. `CONTEXT.md` standing grant / grant lineage / consent version glossary (~250 tokens)
4. `modules/intake/adapters/routes.py` patient route set + `app/main.py` gateway principals/RBAC deps (`require_*`) - auth surface for the new route (~500 tokens)
5. `tests/unit/test_patient_intake_routes.py` (and `test_consent*` if present) - the app-shell route-test pattern to follow (~800 tokens)
6. Issue #438 "backend delta 1", "consent at pick (MOD-004)", and user stories 5-7 (~300 tokens)

## Do NOT read

- Care rx internals, partner directory, frontend, roadmap/PRD docs beyond the #438 excerpt, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect only the 3 known pre-existing dev-OTP env failures in `test_app_shell.py`/`test_seed_demo.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new route tests (pick writes choice + consent, cross-actor rejected, unassigned-doctor reads rejected) pass; existing patient-intake and consent tests stay green.

## Handoff notes

- This is the assignment seam blockers #447/#448 depend on; keep the assignment write idempotent/replay-safe per the app-shell idempotency contract if a client may retry.
- Consent is recorded in the same transaction as the pick - check the existing grant lineage/version mechanics (`grant_consent`) rather than inventing a parallel consent path.
