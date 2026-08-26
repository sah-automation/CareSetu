# Brief - T8 Entry detail screen

**Ticket:** #217 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Opening any entry shows where it came from and who has seen it: filing provider + timestamp; lab results as a plain table of filed values (block-level horizontal scroll on phones); a per-entry "who has seen this" trail sourced from egress data; and when an entry was disclosed, a reference to the consent lineage + version that authorized it. Raw numbers reach the patient without app-side interpretation. Fully bilingual EN/HI. Prototype `record-entry.html` is the binding visual spec.

Acceptance criteria: see #217 body verbatim.

## Read-list (in order)

1. `prototype/phase-3/record-entry.html` - binding visual spec (~1.5K)
2. `prototype/PLAN.md` review outcomes - block-level table scroll rule on phones (~0.5K)
3. Entry-detail + disclosure-trail endpoint contracts as T5 landed them (~0.7K)
4. Timeline screen component family from T7 - shared chrome, page/route conventions (~1K)
5. Dictionaries + LangContext pattern (~0.5K)
6. Existing vitest component-test patterns (~0.5K)

## Do NOT read

- Backend consent state-machine internals beyond endpoint contracts; gateway middleware; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` (filer/timestamp render, lab-table rendering, trail present/absent cases, lineage citation, bilingual suites green)
- `npm run typecheck`

## Handoff notes

- Trail renders only when disclosures exist - omit silently rather than an empty-state block.
- Lineage citation format is human-reference: `C-YYYY-NNN` + version (`v1/v2/...`) as cited by egress rows.
- No interpretation layer on lab values: table of filed values exactly as filed.
