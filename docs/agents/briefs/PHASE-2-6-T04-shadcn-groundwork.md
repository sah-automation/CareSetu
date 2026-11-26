# Brief - T04 shadcn/ui groundwork primitives

**Ticket:** #195 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

Component-library groundwork: adopt shadcn/ui standardized on the Tailwind v3 registry, lazily - only the primitives the shell family needs: **button**, **dropdown-menu**, **sheet**, **skeleton**. Primitives are themed by the resolved tokens (ticket 02), so no hardcoded palette lands inside them. Lucide outline icons permitted alongside the existing hand-drawn set; hand-rolled Tailwind remains the leaf-component pattern. React Aria Components only if a later Intl-sensitive widget demands it (none expected this phase).

Acceptance criteria (verbatim):

- [ ] shadcn/ui installed on the Tailwind v3 registry and bridged to token variables
- [ ] Button, dropdown-menu, sheet, skeleton primitives available with unit suites (render + basic interaction)
- [ ] Bundle/page-weight budget still passing after adoption
- [ ] `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend` green

## Read-list (in order)

1. `docs/research/ui-component-library.md` - evidence + migration notes behind the adoption recommendation (~2K tokens)
2. UI blueprint §1.1 - the standardization decision this implements (~0.3K)
3. Current `tailwind.config` + global stylesheet - where the token bridge lands (~0.7K)
4. shadcn/ui Tailwind-v3 registry init mechanics (official docs) - install/config shape (~0.5K)

## Do NOT read

- Prototype views, `docs/archive/`, backend, existing leaf components beyond confirming icon conventions.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 8 files / 72 tests, `node scripts/measure-pages.cjs` PASSED (all 3 channels within 1.5 MB).

## Done-verify (acceptance criteria → commands)

- Baseline four commands green after adoption
- New primitive suites render + interact (dropdown opens/closes, sheet overlays, skeleton pulses under reduced-motion off)

## Handoff notes

- No `components.json` exists yet - this ticket creates it (Tailwind v3 registry, per decision 4 of #191).
- Theme bridge consumes ticket 02's tokens; sequence after it (native blocker edge wired).
- Primitives land unused-by-default; tickets 06/08/12 consume them. Do not refactor existing hand-drawn components onto them this ticket.
