# Brief - T13 First-login profile-completion wizard & gating matrix

**Ticket:** #204 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The bilingual first-login profile-completion wizard (blueprint §5.9): required basics (name, age, gender, language - language asked explicitly per D1), then skippable chronic-interest toggles, then skippable photo/area/emergency contact. A gating matrix is enforced client-side against local draft state: browsing Find Care / My Record is never gated; intake/booking gated on basics; medicine-delivery checkout gated on area - the wizard step presents inline at that moment, so gating explains itself exactly when relevant.

Skipped items resurface as gentle Home nudge cards and a profile completion meter - never modal nagging. Persistence and real server-side enforcement wiring are marked later-phase integration points.

Acceptance criteria: see #204 body verbatim.

## Read-list (in order)

1. Prototype view `profile-completion.html` - binding visual/step/copy spec (~2.5K tokens)
2. UI blueprint §5.9 profile-completion pattern - step anatomy + nudge/meter rules (~1.5K)
3. Spec decision D1 in #191 - language asked explicitly in step 1, default `"en"` until set (~0.3K)
4. PRD §4.x patient-profile feature rules - gating matrix source of truth (~1.5K)
5. Ticket 03 dictionary API + ticket 06/07 patient shell/route-group surfaces - where steps and nudges mount (~1K)

## Do NOT read

- Consent-sheet prototype view (ticket 12's component), backend profile endpoints (none this phase), split-auth views, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests.

## Done-verify (acceptance criteria → commands)

- Baseline three + new suites: step validation, skip flow, gating matrix (browse-free / basics-for-intake / area-for-checkout), inline-gating presentation, nudge cards + meter state

## Handoff notes

- Draft state lives client-side only (context/localStorage); persistence endpoint is a marked integration point - do not invent one.
- Nudges resurface skipped items on Home as dismissible cards; completion meter reflects draft completeness percentage.
- Gating presents the exact missing step inline at the action moment - never a redirect-to-wizard dead-end.
