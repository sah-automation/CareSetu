# Brief - 08 Homepage rail reaches record-page parity

**Ticket:** #671 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The patient homepage's right-side rail reaches record-page parity: an aside containing, in order, "At a glance", the health snapshot card, and "Who accessed my record", with the record rail's sticky offset and spacing. The homepage fetches the patient's own record once through a small shared hook and feeds the new sections from that single response; the record page keeps passing its already-loaded timeline. On small screens the rail sections stack after the main cards in the same reading order. Both surfaces render the shared components from #666/#669, and the accordion's consent-log link works from the homepage.

Acceptance criteria:

- [ ] The homepage rail aside renders three sections in order: At a glance, health snapshot, Who accessed my record
- [ ] The rail carries the record rail's sticky offset and spacing contract; on small screens the sections stack after the main cards in the same order
- [ ] The homepage fetches own record once and shares the response between the new sections; the record page still passes its loaded timeline without re-fetching
- [ ] The Who-accessed accordion expands to the latest five accesses with the full count badge and its consent-log link navigates to the consent log
- [ ] Existing homepage rail test hooks are preserved and extended to the three-section expectation; record page test hooks still resolve
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Blocked by

#666 (Extract the rail At a glance summary), #669 (Extract the Who accessed my record accordion) - both shared components must exist first.

## Read-list (in order)

1. Spec #662 §Solution "Homepage rail parity" in full + user stories 26-35 + Testing Decisions (homepage assertions, shared hook, test-hook preservation) (~3K)
2. The patient homepage shell (apps/frontend/src/app/(patient)/patient/page.tsx) - the grid, the current `patient-home-rail` aside with only the health snapshot, and the page's data hooks (~1K)
3. The shared components from #666/#669 - their prop contracts and self-owned fetch behavior (as landed) (~2.5K)
4. `HealthSnapshotCard` - already shared; how it self-fetches and hides on failure (keep behavior) (~1K, skim)
5. Homepage test blocks: shell/rail-above-feed ordering, health-snapshot rail sticky assertions (apps/frontend/src/app/(patient)/patient/page.test.tsx) - hooks to preserve and the sticky class-contract precedent to mirror (~2K)
6. The record page rail composition - the sticky offset/spacing contract the homepage must match (~0.5K)

## Do NOT read

- Backend; timeline group rendering (ticket #667); access-label rendering (ticket #670 - comes through the shared component)
- The extracted components' pre-refactor page-internals history
- i18n beyond strings the components already carry; `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 2148 passed (2026-10-08)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - homepage three-section order + sticky contract + consent-log link + preserved hooks; record page suite still green
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Single-fetch rule (story 33): one `fetchOwnRecord` per homepage visit feeding the new sections - do not let each section fetch the record separately. Note `HealthSnapshotCard` already self-fetches today; the spec keeps its behavior, the shared hook covers the new sections (summary counts + accordion's patient id). Read the spec's Implementation Decisions paragraph and follow it exactly.
- Order is part of the contract: At a glance -> health snapshot -> Who accessed, on both surfaces; assert it in tests.
- Grid/aside: keep `patient-home-rail` testid, add the sections inside it; small screens stack the aside after the main cards (current health-snapshot behavior preserved).
- Sticky class-contract precedent already exists in the homepage health-snapshot tests (`lg:sticky` assertion) - follow it for the spacing contract.
