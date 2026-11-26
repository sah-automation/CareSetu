# Brief - T03 Typed bilingual i18n infrastructure

**Ticket:** #194 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Typed bilingual string infrastructure app-wide, generalized from the proven patient-auth-wizard pattern (no i18n framework): typed per-locale dictionaries (en/hi) with a `LangContext` at the root; persistence = localStorage when anonymous, client-held profile-field intent when logged in (server persistence waits for the profile backend, per D1); `<html lang>` tracks the active locale. A bilingual parity unit test fails when any key is missing from either locale (REQ-006 enforced mechanically).

Proof surface: migrate the patient OTP wizard onto the engine with rendered copy byte-stable - the deployed live smoke asserts that copy literally (spec decision 16). Later tickets migrate their own surfaces onto this engine; this ticket ships the engine plus one migrated surface.

Acceptance criteria (verbatim):

- [ ] Locale toggle re-renders strings in both locales on the proof surface; choice persists across reload when anonymous
- [ ] `<html lang>` tracks the active locale
- [ ] Parity unit test fails on any key missing from either locale (demonstrate red/green)
- [ ] Wizard rendered copy byte-stable post-migration; its existing suites pass unchanged
- [ ] `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend` green

## Read-list (in order)

1. The wizard's string-table/i18n module (`otpState.ts` - the `STRINGS`/`I18n` shape) - the pattern seed to generalize (~1.5K tokens)
2. PRD REQ-006 (bilingual parity requirement section) - the rule the parity test encodes (~0.5K)
3. Spec decision D1 in #191 - language defaults (`"en"` until set; wizard asks explicitly in step 1; anonymous visitors use device preference else `"en"`) (~0.3K)
4. UI blueprint §12 sketch i18n notes (annotated ratified-with-D1-D4) - engine constraints (~1K)
5. `PatientAuthWizard` test suite - the byte-stability bar the migration must clear (~0.7K)

## Do NOT read

- `docs/archive/`, other prototype views, backend modules beyond the smoke-cited contract, dashboard components.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 8 files / 72 tests pass (wizard suite = 26 tests).

## Done-verify (acceptance criteria → commands)

- Baseline three commands green
- New parity suite red/green demonstrable (temporarily delete a key → test fails → restore)
- Wizard suite + choose-role/login suites pass unchanged (copy stability proof)

## Handoff notes

- Today the wizard's lang resets to `"en"` every reload and `<html lang>` is static - persistence and sync are net-new here.
- Dictionary keys should be grouped by surface (e.g. `auth.*`, `home.*`, `nav.*`) so later tickets add their sections without merge friction.
- Logged-in persistence is intentionally client-held profile-field intent only (D1); do NOT write a server field this phase.
