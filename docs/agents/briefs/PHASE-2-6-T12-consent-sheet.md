# Brief - T12 Reusable consent-moment bottom sheet

**Ticket:** #203 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

One reusable consent-moment bottom sheet built to blueprint §5.10: requester name + verified badge, specific plain-language scope of what they will see, per-action validity statement, Allow / Not-now buttons. Denial blocks the action with a plain explanation and never re-prompts aggressively. Keyboard/focus contract: trapped focus while open, Escape closes, focus returns to the trigger - fully operable non-visually (axe-scanned).

Grant/revoke writes remain marked later-phase integration points. This ticket ships the component, its bilingual strings, and one demo integration point on a patient surface proving the trigger → sheet → decision → block-or-proceed loop end-to-end against local state.

Acceptance criteria: see #203 body verbatim.

## Read-list (in order)

1. Prototype `consent-sheet.html` - binding visual/copy spec (~1.5K tokens)
2. UI blueprint §5.10 consent-moment pattern - component anatomy + denial semantics (~1K)
3. Security standard consent-gating section - rules the copy must respect (~1K)
4. shadcn sheet primitive suite from ticket 04 - base component + its focus behavior (~0.7K)
5. Ticket 03 dictionary/LangContext API - bilingual strings home (~0.5K)

## Do NOT read

- Backend consent engine (none exists this phase), profile-completion prototype view, split-auth views, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests.

## Done-verify (acceptance criteria → commands)

- Baseline three + new consent-sheet suites: decision outcomes (Allow proceeds / Not-now blocks w/ explanation), no-aggressive-reprompt assertion, focus contract
- Axe scan of the sheet clean (extends to e2e in ticket 14)

## Handoff notes

- Focus contract is the acceptance bar: trap on open, Escape closes, focus returns to trigger element - assert all three in jsdom plus axe.
- The demo integration point should live on a patient surface behind an explicit "demo care action" affordance or test-only mount so real surfaces are not polluted.
- Denial memory: per-trigger dismissal state (session-scoped) so re-prompting stays non-aggressive without pretending persistence exists.
