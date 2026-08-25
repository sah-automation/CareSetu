# Brief - T7 Record timeline screen

**Ticket:** #216 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

My Record opens as one reverse-chronological timeline of everything, filterable by type. Filter bar follows the ratified responsive behavior: wrapped pill row desktop/tablet; below 720px a single-line row with a More dropdown that renames itself to the active filter; at 374px and under it scrolls. "Visits" is named "Consultations" everywhere including Hindi (परामर्श). Access-audit + health-tracking entries render as Soon placeholders (Phases 4/12). Fully bilingual EN/HI. Prototype `record.html` is the binding visual spec.

Acceptance criteria: see #216 body verbatim.

## Read-list (in order)

1. `prototype/phase-3/record.html` - binding visual/copy spec (~2.5K)
2. `prototype/PLAN.md` PHASE-3 row + review outcomes - chip typography rule, filter-bar breakpoints, Consultations renaming (~1K)
3. UI blueprint patient-surface section - navigation model + cross-cutting patterns the screen must respect (~1K)
4. Nav config + shell/tab components family - how screens register in nav; Record slot from T1's five-column layout (~1.5K)
5. Dictionaries + LangContext pattern - typed EN/HI keys + runtime parity test (~1K)
6. Existing patient page + vitest component-test patterns (~0.7K)
7. Record endpoint contract as T2 landed it (~0.5K)

## Do NOT read

- Consent screens (T9/T10); backend modules beyond the endpoint contract; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` (timeline render, filter behavior incl. More-dropdown rename, placeholder + bilingual suites green)
- `npm run typecheck`

## Handoff notes

- The More dropdown renaming itself to the active filter is a ratified review outcome - test it explicitly.
- Breakpoints are binding: <720px single-line + dropdown; <=374px horizontal scroll.
- Chip typography rules come from PLAN.md review outcomes, not taste.
- Timeline data arrives from real API; for unit tests mock at the fetch/facade-client seam per existing patterns.
