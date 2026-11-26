# Brief - #744 Nav configuration children and prefix-matched parent active state

**Ticket:** #744 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Let the nav configuration express groups: an optional children list on a nav item, with sub-membership declared once and read by every renderer. Then make a parent highlight when any of its children is the current destination, so a disclosure parent never looks inactive while the operator is inside it. No other role shell changes.

- [ ] The nav item definition gains an optional children list; sub-membership is one configuration that the sidebar and the mobile overflow sheet both read, never a second hand-maintained list.
- [ ] Parent active state uses prefix matching in all three nav renderers, so a disclosure parent is active when the current path equals its own destination or is prefixed by it.
- [ ] Existing section grouping for the non-operator roles is retained unchanged.
- [ ] Href uniqueness covers nested destinations, and the every-full-shell-item-has-a-group invariant still holds.
- [ ] Bilingual label resolution covers nested labels, and every new and existing nested label has dictionary entries in both locales - a missing key in either locale fails the build.
- [ ] The nav configuration's own contract tests are extended rather than duplicated.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 27, 29, 34; the sidebar user stories. (~1K)
2. `docs/design/ui-blueprint.md` - the navigation model and the design-system rules this configuration encodes. (~1K)
3. The nav configuration module: the item type, the per-role configuration, the section helper, the mobile split helper, and the storage-key helper. (~1.6K)
4. The three nav renderers' active-state logic - the sidebar item, the collapsed-rail item and the bottom tab - which today all use exact path equality. Change all three or a parent highlights in one surface only. (~1K)
5. The nav configuration contract tests: href uniqueness, bilingual label resolution, exactly-one-center, section grouping and the every-full-shell-item-has-a-group invariant. (~1K)
6. The dictionary's nav namespace and the recursive bilingual parity test. (~0.8K)

## Do NOT read

- The sidebar's disclosure rendering, the collapsed-rail flyout layout, the mobile sheet layout - #745 and #746 own those; you change only the configuration and the active-state predicate.
- Backend sources, `docs/archive/`, chart and panel components.
- The other three role shells beyond their section grouping, which must stay unchanged.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- **Prefix matching has a trap.** A parent whose destination is a prefix of a _sibling's_ destination will highlight when the sibling is active. Bound the match at a path-segment boundary, not a raw string prefix.
- One configuration, two renderers. If you find yourself adding a child list to a second structure, that is the failure this ticket exists to prevent.
- Extend the existing contract tests; do not write a parallel suite. The uniqueness, label-resolution and group invariants are one test module.
- Bilingual parity is enforced by a recursive test that compares key presence and shape across locales. Adding a nested label without both locales fails the build - that is the gate working, not an obstacle.
- Downstream, #745 renders the disclosure and #746 the mobile sheet. Both read the `children` field you add here; their shape is now a contract.
