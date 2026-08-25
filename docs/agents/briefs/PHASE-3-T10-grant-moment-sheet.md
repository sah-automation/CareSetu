# Brief - T10 Grant moment on consent sheet

**Ticket:** #219 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~6.5K tokens (budget 10K) - within budget

## Scope

A patient shares on their own initiative without waiting for a provider to ask: a Share action on the consent log opens the ratified plain-language sheet - who is asking (counterparty they pick), what they will see (one clear scope from the enum), how long ("Until you revoke"). Allow writes a real standing grant through the consents API and lands on a visible consent receipt; "Not now" explains what it leaves unblocked and closes without creating anything. This wires the documented integration point in the existing PHASE-2.6 consent-sheet component to MOD-004. Fully bilingual EN/HI. Prototype `consent-grant.html` is the binding visual spec.

Acceptance criteria: see #219 body verbatim.

## Read-list (in order)

1. `prototype/phase-3/consent-grant.html` - binding visual/copy spec (~1.5K)
2. Existing ConsentSheet component + its documented later-phase integration point docstring (~1.5K)
3. UI blueprint §5.10 consent-moment pattern - anatomy + denial semantics the sheet must keep (~1K)
4. Grant endpoint contract as T3 landed it (typed request/response) (~0.5K)
5. Dictionaries consent.\* keys + LangContext (~0.7K)
6. Lab-booking consent demo component - the demo wiring this ticket replaces with real writes (~0.7K)

## Do NOT read

- Backend consent module internals beyond the endpoint contract; provider channels (Phases 8/9); check_consent internals; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` (sheet opens scoped to picked counterparty+scope, Allow -> real grant call + visible receipt, Not-now -> explanatory copy + no write, bilingual suites green)
- `npm run typecheck`

## Handoff notes

- The PHASE-2.6 sheet's focus contract (trap on open, Escape closes, focus returns to trigger) carries over unchanged - do not regress it.
- "Not now" copy must explain what declining leaves unblocked (story #12).
- Receipt after Allow is visible proof (story #13): who/scope/until-you-revoke.
- Scope picker offers exactly the five-value enum; counterparty targeting is per-purpose/per-counterparty - never free-form permissions.
