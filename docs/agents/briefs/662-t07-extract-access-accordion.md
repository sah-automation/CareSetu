# Brief - 07 Extract the Who accessed my record accordion into a shared patient component

**Ticket:** #669 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

The record page's "Who accessed my record" accordion is extracted into a shared patient component that owns its fetch state, latest-five slice, expand behavior, consent-log footer link, and zone-swapped testid sets (mobile vs rail), and both the record page's rail and mobile privacy mirror render it with every existing test hook preserved. Pure prefactor: identical behavior, ready for the homepage in ticket #671.

Acceptance criteria:

- [ ] A shared patient access accordion component owns fetch state, latest-five slice, expand/collapse, consent-log footer link, and the zone-swapped testids (mobile and rail variants)
- [ ] The record page rail and mobile privacy mirror render it; every existing access-history test hook still resolves
- [ ] No behavior change on the record page - existing access-history tests pass unchanged except for import/wiring updates
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Blocked by

#666 (Extract the rail At a glance summary) - both tickets edit the same page file and its test file; sequencing avoids interleaved edits.

## Read-list (in order)

1. Spec #662 §Solution "Homepage rail parity" - extraction decisions (accordion owning fetch state, latest-five slice, expand behavior, consent-log footer link) and user stories 30-31, 34-35 (~1.5K)
2. The patient record page access-section region: the `renderAccessSection` helper, its zone prop and zone-swapped testid sets, `ACCESS_MOST_RECENT_COUNT`, the fetch call (`loadAccessHistory` gated on the timeline's patient id), expand/collapse state, consent-log link, and the mobile mirror + rail call sites (~2.5K)
3. Record page access-history test blocks - every hook the extraction must preserve: list/entry testids per zone, five-row cap, loading, consent-log link, error/retry (~1.5K)
4. The audit API client's `fetchAccessHistory` - the fetch the component will own (~0.3K)
5. The shared summary component produced by ticket #666 - placement, prop style, and import direction precedent within the extracted set (~0.5K)

## Do NOT read

- The three-step counterparty label helper and identity-line rendering (ticket #670 owns rendering changes; if #670 lands first, extract its fixed code as-is)
- Homepage page shell (ticket #671)
- Backend; timeline rendering (ticket #667)
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 2148 passed (2026-10-08)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - record page access suite green with all hooks preserved
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Zone is a prop, not two components: the same component serves mobile and rail by swapping the testid prefix (current behavior - preserve it).
- The fetch stays owned by the component (per spec), gated on the record's patient id exactly as today; the record page passes no access data.
- Ordering with #670 (label rendering): either order works. If #670 lands first, extract the already-fixed rendering; if this lands first, #670 edits the extracted component (which also benefits the homepage).
- Preserve `access-history`/`access-history-rail`, list/entry/loading/consent-log-link variants, and error/retry hooks exactly.
