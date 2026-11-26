# Brief - 09 Record timeline month dividers gain spacing above every group

**Ticket:** #667 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

Month dividers on the record timeline get clear spacing above every group: the group-level top margin and its first-child suppression move from the group heading to the group section wrapper. Each heading is the first child of its own group section, so the old placement suppressed the margin on every group; on the wrapper (a sibling under the timeline wrapper) `first:` suppresses only the very first group. Heading label, count badge, hairline rule, and intra-group spacing are unchanged.

Acceptance criteria:

- [ ] The group section wrapper carries the top-margin + first-child-suppression contract; the heading no longer carries it
- [ ] Only the first group under the sticky filter bar is suppressed; every subsequent month divider has the gap
- [ ] A class-contract test asserts the group section carries the spacing contract and the first group carries the suppression (per codebase class-contract precedent - jsdom does not compute Tailwind styles)
- [ ] Heading internals (label, count badge, hairline) and intra-group entry spacing are untouched
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. Spec #662 §Solution "Record timeline spacing" + user stories 36-39 (~0.8K)
2. The patient record page timeline group rendering region - the group `<section>` wrapper (currently classless) vs the group heading that carries `mt-5` + `first:mt-0` (~0.7K)
3. A class-contract assertion example from the UI component tests (`toContain` on className) - the pattern to copy, plus the jsdom caveat noted in the consent-log page tests (~0.7K)
4. `groupTimeline` in the record timeline view helper - confirm grouping is untouched (read-only) (~0.3K)

## Do NOT read

- Rail, summary, accordion regions of the record page (tickets #666/#669/#670); homepage (ticket #671)
- Backend; i18n; e2e specs
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 2148 passed (2026-10-08)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - timeline grouping tests + new class-contract test green
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Root cause (spec): `first:` on the heading suppressed margin for every group because each heading is the first child of its own group section. Moving both classes to the wrapper makes `first:` scope to sibling groups correctly.
- Do not restyle anything else - story 39 pins label, count badge, and hairline as unchanged.
- Touches only the timeline group rendering region of the record page; independent of the rail/extraction tickets working elsewhere in the same file (different regions).
