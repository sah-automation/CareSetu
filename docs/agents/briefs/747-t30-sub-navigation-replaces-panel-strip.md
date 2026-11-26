# Brief - #747 Sub-navigation replaces the page-level panel strip

**Ticket:** #747 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Remove the duplication: once the Observability sub-menu carries the same destinations the page-level tab strip carries, the tab strip goes and the observability destinations move into the nav configuration's children. Add the Settings destination as a placeholder shell - AI configuration, notification configuration, feature flags and user management stay out of scope.

- [ ] The page-level horizontal panel strip is removed from the operator observability pages, because the sub-menu now carries the same destinations and two navigations must not duplicate each other.
- [ ] The observability destinations move into the nav configuration's children, so adding a panel adds a destination automatically and the sub-navigation is rendered by the same configuration the sidebar uses.
- [ ] A Settings destination appears in the sub-menu and its page is a placeholder shell.
- [ ] Settings carries no AI configuration, notification configuration, feature flags or user management - those remain out of scope.
- [ ] The panel page component still renders its panels; only the tab strip is removed.
- [ ] The existing panel and route tests are updated for the removed strip, not deleted.

## Read-list (in order)

1. Spec #717 - Implementation Decision 35; Implementation Decisions 27, 28; Out of Scope (the Batch 2 settings surface). (~0.9K)
2. The observability panel page component and its tab strip - the panel route list it derives, and what else the component renders besides the strip. (~1K)
3. The nav configuration's `children` field and the operator sections from #744, into which the observability destinations move. (~0.8K)
4. The existing panel page and component tests that assert the strip - the assertions to update rather than delete. (~0.7K)
5. The route layout for the operator observability pages, and the placeholder-page convention used elsewhere in the console. (~0.6K)
6. The dictionary's nav namespace for the Settings label, both locales. (~0.4K)

## Do NOT read

- The sidebar's disclosure rendering and the mobile sheet - #745, #746 own those.
- Backend sources, `docs/archive/`, chart primitives.
- The individual panel components - they are unchanged.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- This is a removal ticket and it is easy to over-remove. The panel page component still renders panels; only the navigation strip goes.
- The observability destinations move into the nav configuration, so #744's uniqueness and label-resolution tests must keep passing with a nested set. If a nested href collides with an existing one, the collision is real - fix it, do not relax the test.
- The Settings page is a shell on purpose. It must not acquire AI configuration, notification configuration, feature flags or user management - those are Batch 2 and the placeholder is where that boundary is enforced.
- Update the strip's tests to assert its absence and to assert the destinations are reachable from the configuration. Deleting a test because the feature went away loses the regression you are trying to prevent.
