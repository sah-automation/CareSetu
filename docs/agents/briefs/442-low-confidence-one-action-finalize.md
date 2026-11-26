# Brief - 442 BE: low-confidence one-action finalize

**Ticket:** #442 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.7K tokens (budget 10K) - within budget

## Scope

Close the low-confidence dead end: a doctor's attributed review of a low-confidence pre-summary reaches `final` in that same action instead of stopping at `reviewed`. Patient editing stays the primary fix; the doctor review stays the attribution gate.

AC:

- [ ] Reviewing a low-confidence pre-summary reaches `final` in a single review action
- [ ] A low-confidence summary can only reach `final` via an attributed doctor review - no auto-finalize, no patient-only path
- [ ] State-machine and review-facade tests cover the new transition (a genuine machine change, not a route change)
- [ ] Existing state-machine, review-facade, and low-confidence tests still pass

## Read-list (in order)

1. `modules/intake/domain/presummary_machine.py` - `PreSummaryStatus` (Draft/Reviewed/Final), `is_low_confidence`, and the current finalize-from-Draft / reviewer rules; the exact guard to relax (~350 tokens)
2. `modules/intake/facade.py` review action (`mark_pre_summary_reviewed`) and the low-confidence branch - where the same-action finalize lands (~400 tokens)
3. `test_presummary_state_machine.py`, `test_intake_review_facade.py`, `test_intake_low_confidence.py` - the existing surface these tests lock (~1200 tokens)
4. `test_doctor_review_route.py` - the route-level contract this change must keep green (~500 tokens)
5. Issue #438 "backend delta 4" + `CONTEXT.md` low_confidence / forced-doctor-review glossary (~300 tokens)

## Do NOT read

- Consent, care rx internals, partner/directory code, frontend, `docs/archive/`, the review-queue read (that is #447).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect the 3 known pre-existing dev-OTP env failures in `test_app_shell.py`/`test_seed_demo.py`; they are unrelated to this slice and must stay failing identically.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` with the state-machine, review-facade, and low-confidence test files targetted: new transition tests pass; old tests still pass.
- No review-route test regressions.

## Handoff notes

- The machine change is small: the review action's selection must emit the finalize transition for low-confidence inputs (today the transition exists but nothing issues it).
- Attribution (timestamped review record) must not be weakened - the gate stays a real doctor action.
