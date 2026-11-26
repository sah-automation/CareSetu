# Brief - 504 Patient home: 4-tile services grid

**Ticket:** #504 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~3K tokens (budget 10K) - well within budget

## Scope

A patient gets a fixed 4-tile services grid: Consult a doctor, Book a lab test, Start visit (the accent tile), and Order medicine - clearly marked Soon and not clickable. Top actions are one tap away from the home.

- [ ] All four tiles render in the fixed order with the correct labels.
- [ ] Order medicine renders marked Soon and does not navigate.
- [ ] Start visit is the accent tile.
- [ ] Strings under `patientHome.*`/`services.*` in en + hi with parity enforced.

## Read-list (in order)

1. The services grid in the binding `shell-light.html` spec (grep `services-grid`, ~381-401) - fixed order, Soon tile, accent tile, tile icons (~0.8K).
2. The patient navigation config - where each tile's destination points (consult, lab, start visit; Order medicine has none) (~0.5K).
3. The `patientHome.*`/`services.*` dictionary slices and the composed home `page.test.tsx` seam from #499 (~0.6K).
4. The blocking ticket #503 closing comment, if any (~0.2K).

## Do NOT read

- The booking / consult / lab flows themselves, backend modules, unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #503 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - tiles render in fixed order at the composed seam; Order medicine non-navigating; accent tile present.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- Pure presentational slice: no data seam, no new providers. Fixed order must match the prototype row exactly.
- "Soon" is copy on the tile, not a disabled mechanism - but the tile must not navigate. Start visit carries the accent styling and navigates to the live start-visit tab.
