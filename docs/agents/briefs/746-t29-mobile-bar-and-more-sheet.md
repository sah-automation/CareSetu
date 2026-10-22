# Brief - #746 Mobile bottom bar and More sheet from one configuration

**Ticket:** #746 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Make every destination reachable on a phone. The mobile bar shows a small fixed set of bottom destinations plus a More sheet; the sheet lists every destination, grouped and indented exactly as the sidebar groups them, and both are driven from the same configuration so a destination can never exist in one and not the other.

- [ ] The mobile bar shows a small fixed set of bottom destinations plus a More sheet.
- [ ] The More sheet lists every destination, including sub-destinations, with group headers and indentation preserved, so no destination is unreachable on a phone.
- [ ] The mobile bar, the More sheet and the sidebar are all driven from one configuration; a destination cannot exist in one and not the other.
- [ ] The overflow destination choice is derived from the same configuration the sidebar uses, so adding a panel adds a destination automatically.
- [ ] Coming-soon destinations stay non-interactive and dimmed in the sheet as they are in the sidebar.
- [ ] The shell test suite proves the More sheet lists every destination, grouped and indented.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 27, 32, 33; the mobile sidebar user stories. (~0.8K)
2. The bottom-tabs component and its overflow sheet, including the grid-column arithmetic that decides how many destinations fit the bar. (~1.2K)
3. The nav configuration's mobile split helper and its pinned-overflow rule, plus the `children` field #744 added. (~0.8K)
4. How the sheet's rows currently render a destination, and where the non-interactive coming-soon rendering lives so the nested case reuses it. (~0.6K)
5. The operator shell test suite's full-density cases, and any existing overflow-sheet test to extend. (~0.9K)

## Do NOT read

- The sidebar's desktop disclosure layout - #745 owns that; you mirror its grouping, you do not restyle it.
- The nav configuration's contract tests - #744 owns them.
- Backend sources, `docs/archive/`, chart and panel components.
- The patient light shell beyond confirming it is untouched.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- The single-configuration criterion is the real work: the sheet must walk `children`, not a second hand-maintained array. If you find yourself typing a destination name in the sheet component, that is the failure.
- The bar has a fixed capacity and a pinned-overflow rule. Adding nine sub-destinations changes what fits - read the split helper's arithmetic before deciding what the fixed set is, and keep the patient shell's split behaviour identical.
- Group headers and indentation in the sheet must match the sidebar's grouping, or the same destination looks like two different places.
- The test that matters: every destination in the configuration appears in the sheet. Assert it by walking the configuration in the test, not by listing names - a hard-coded list in the test passes while the behaviour is broken.
