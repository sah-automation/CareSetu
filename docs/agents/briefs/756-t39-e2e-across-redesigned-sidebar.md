# Brief - #756 End-to-end pass across the redesigned sidebar

**Ticket:** #756 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Prove the whole thing end to end: an operator signs in and reaches every new destination from the redesigned sidebar, on a phone-width viewport and on a desktop viewport. The redesign's whole claim is that every destination is reachable and every group navigates - including when the sidebar is collapsed and when the phone has only a bottom bar.

- [ ] An end-to-end pass signs in as an operator and reaches each new destination - Overview, Business, Product, Reliability, the four existing AI panels and Settings - from the redesigned sidebar.
- [ ] The pass runs on a phone-width viewport and a desktop viewport.
- [ ] The More sheet reaches every sub-destination on a phone-width viewport.
- [ ] The collapsed icon rail still offers a way into the Observability group on a desktop viewport.
- [ ] The Business, Product and Reliability destinations each render their panels rather than an empty shell.
- [ ] The pass runs as part of the repository's end-to-end harness.

## Read-list (in order)

1. Spec #717 - the sidebar and mobile user stories; Testing Decisions (the verification harness). (~0.8K)
2. The end-to-end harness configuration and its viewport projects, plus how an operator signs in. (~1K)
3. An existing operator end-to-end spec that signs in and navigates, as the shape to copy. (~1K)
4. The shell's collapse behaviour and viewport breakpoints under test - how the rail is collapsed and restored, and what the test ids are for the toggle and the flyout. (~0.7K)
5. The operator observability routes the destinations resolve to, including the settings placeholder. (~0.4K)
6. The stable test ids the lens pages expose for their panel sections, so "renders panels" is assertable rather than assumed. (~0.5K)

## Do NOT read

- `docs/archive/`.
- The read query internals, the intake and care modules.
- The component internals of the sidebar and the sheet - #745 and #746 own them; you drive them as a user does.

## Baseline verify (must pass before the first edit)

- `npm run test:e2e`

## Done-verify (acceptance criteria → commands)

- `npm run test:e2e`

## Handoff notes

- **Drive it the way an operator would.** Hover or focus the group, expand it, click the destination. If the test reaches a destination by typing a URL, it proves nothing about the redesign.
- Two viewports is the criterion, not a nicety: the desktop rail and the phone bar are two different navigation surfaces, and a destination reachable on one but not the other is exactly the bug this ticket exists to catch.
- The collapsed rail's flyout is the awkward path (hover opens a positioned flyout, then you must click through it). Expect this to be the test that needs a retry or an explicit wait; a flaky test here is better than no coverage.
- "Renders panels, not an empty shell" needs a test id from the lens pages. If the pages do not expose one, add it there rather than asserting on visible text.
