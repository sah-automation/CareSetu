# Brief - 500 Patient home: slim dismissible profile completeness banner

**Ticket:** #500 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

A patient whose profile is missing any of name/age/gender sees a slim, one-line, dismissible banner on the home (not a blocking gate). Dismissing it persists per device so it stays gone on later visits. A patient with a complete profile sees no banner at all. The banner supersedes the old nudge cards on the home; the meter and editing stay on the separately-planned profile surface.

- [ ] Banner renders when basics (name, age, gender) are incomplete and not dismissed.
- [ ] Dismissing the banner persists; it does not reappear on re-render of the home.
- [ ] Banner does not render when basics are complete.
- [ ] Banner strings live under `patientHome.*` in en + hi with parity enforced.

## Read-list (in order)

1. The PROTO-2.7 banner markup and its returning/fresh states in the binding `shell-light.html` spec (grep `profile-banner`, ~196-214) (~0.5K).
2. The profile state basics helper (`basicsComplete`) and the existing nudge-dismissal persistence precedent in the profile state module - reuse its localStorage pattern for the banner dismissal (~0.6K).
3. The `patientHome.*` dictionary section added by #499 plus the dictionary parity mechanism in `dictionaries.test.ts` (~0.5K).
4. The composed home `page.test.tsx` seam established by #499 - the pattern to extend for banner tests (~0.8K).
5. The blocking ticket #499 closing comment, if any, for handoff deltas (~0.2K).

## Do NOT read

- The profile editing/complete pages, the meter component internals beyond what the banner replaces, backend modules, unrelated dictionary sections, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #499 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - banner appears/dismisses/hides per profile state at the composed seam.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- One-line, dismissible, never a blocking gate: it sits under the greeting strip and is a _separate_ element from the (removed) nudge cards.
- Dismissal persistence should mirror the existing nudge-dismissal key scheme (`isNudgeDismissed`/`dismissNudge`), namespaced for the profile banner.
- If `basicsComplete` returns true, the banner element must not render at all (assert on the testid absent, not hidden).
