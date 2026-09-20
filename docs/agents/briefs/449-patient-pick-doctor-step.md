# Brief - 449 FE: patient pick-a-doctor step

**Ticket:** #449 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

The pre-summary continuation becomes a patient-authed pick step: a verified-doctor selection defaulted to presetType doctor and pre-filtered by a suggested specialty derived from symptoms (child → Pediatrician, pregnancy/menstrual → Gynecologist, dental → Dentist, otherwise General Physician) shown as a start-here filter, not a verdict. Cards show verified tick, practice, specialty, distance, fee (or fee-not-set), credentials summary, and link to the verified profile. Booking opens a plain-language consent sheet; Allow records pick + consent and shows a confirmation with what happens next. Low-confidence patients can edit symptoms before choosing.

AC:

- [ ] Continuation from pre-summary leads to the pick-a-doctor screen
- [ ] Suggested specialty derived from symptoms, shown as a start-here filter, not blocking choice
- [ ] Card fields include verified tick, practice, specialty, distance, fee-or-fee-not-set, credentials summary
- [ ] Booking opens consent sheet naming what the doctor sees; Allow records pick + consent in one step and shows confirmation
- [ ] Low-confidence pre-summary shows a symptom-edit link before the pick
- [ ] All new copy is bilingual en/hi

## Read-list (in order)

1. The pre-summary completion page and its current continuation target - the surface this ticket re-points (~700 tokens)
2. `DirectoryBrowser` component + the `/doctors` browse page defaulting presetType doctor - the verified list this step re-filters (~900 tokens)
3. Intake + consent API clients (including the #443 pick-write client shape once merged; #446 if merging) - mutations this screen fires (~500 tokens)
4. `lib/i18n/dictionaries.ts` en/hi pick block (skeleton from #446) - strings to fill in both languages (~300 tokens)
5. Existing page-test + component-test pattern (vitest) - the harness to follow (~600 tokens)
6. Issue #438 user stories 1-10 + "consent at pick" decision (~600 tokens)

## Do NOT read

- Backend route internals, doctor console/workspace pages, care rx flow, `docs/archive/`, blueprint/PRD docs.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - currently green (71 files, 801 tests).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - page + component tests: suggestion derivation + filter, card fields incl. fee-not-set, consent sheet flow, one-step pick + confirmation, low-confidence edit link; parity test passes.

## Handoff notes

- Blockers #443 (pick write + consent) and #444 (fee) must be merged; the pick is the consent moment - Allow performs one action.
- Fee card copy: if fee is null show fee-not-set and still allow picking (user story 10).
- Copy must be bilingual in the same pass - no English-only strings merge.
