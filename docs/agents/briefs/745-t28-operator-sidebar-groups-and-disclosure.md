# Brief - #745 Operator sidebar groups with the Observability disclosure

**Ticket:** #745 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Turn the operator console's single sidebar entry with five page tabs into a grouped sidebar: a Work section holding the queue, verifications, disputes and audit, and an Observability group rendered as a collapsible disclosure whose sub-menu holds Overview, the three new lenses, the four existing AI panels and a Settings destination. The disclosure is hand-rolled with its expanded state exposed to assistive technology, and the collapse-to-icon-rail behaviour is preserved.

- [ ] The operator sidebar becomes two sections - Work and Observability - with Observability a disclosure parent holding Overview, Business, Product, Reliability, the four existing AI panels and Settings.
- [ ] The disclosure is hand-rolled, no new dependency is installed, and its expanded state is exposed to assistive technology; its arrow rotates when open.
- [ ] Sub-destinations are indented under their group with a visible hairline guide rail, and groups are separated by hairline dividers.
- [ ] The navigation landmark gains a label; the rail widens enough for the longer sub-labels; the collapsed rail width is unchanged.
- [ ] Collapse-to-icon-rail is preserved, and the collapsed-rail hover flyout knows it is a group so a group stays navigable when collapsed.
- [ ] Coming-soon destinations stay non-interactive and dimmed wherever they appear, including inside sub-menus.
- [ ] Visual refinement uses existing design tokens only - no new design token is introduced.
- [ ] Only the operator shell changes; the patient, doctor and partner shells keep today's layout.
- [ ] The operator shell test suite proves sub-destinations render under their parent, the disclosure reports its expanded state, a parent highlights when a child is active, coming-soon items stay non-interactive inside sub-menus, and the collapsed rail still offers a way into a group.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 28, 30, 31, 32; the sidebar user stories; the standing rule against new design tokens. (~1.1K)
2. `docs/design/ui-blueprint.md` - the navigation model and per-surface IA for the operator console. (~0.9K)
3. `docs/research/ui-component-library.md` - the evidence behind keeping the sidebar hand-rolled rather than adopting a collapsible dependency. (~0.5K)
4. The sidebar component and its section group and collapsed-rail item sub-components, including the flyout's positioning and its coupling to the collapsed rail width. (~1.6K)
5. The doctor-profile controlled-expansion component - the existing disclosure pattern to mirror: expanded state, the toggle button's ARIA wiring, and the body toggle that avoids the `hidden` attribute. (~0.7K)
6. The token vocabulary and the hairline tokens already in use, plus the width utilities and the rule behind them. (~0.7K)
7. The operator shell test suite: the full-density cases, the collapse-persistence case and the retired-`matchMedia` case that must keep passing. (~1.1K)

## Do NOT read

- The mobile bottom bar and its overflow sheet - #746 owns those.
- The nav configuration's contract tests - #744 owns them.
- Backend sources, `docs/archive/`, chart and panel components.
- The patient light-density shell beyond confirming it is untouched.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`
- `npm run check:pages` if the settings placeholder route is added here

## Handoff notes

- **No new dependency.** The component-library research explicitly directs keeping this hand-rolled; adding a collapsible package fails a design decision, not a lint rule.
- Widen the rail, keep the collapsed width. The flyout is positioned against the collapsed rail's width - if you change one, you break the other. That coupling is asserted in the existing tests.
- Disclosure state is per-operator preference or per-navigation - decide, and note it. It is not part of this ticket's criteria either way, but an unstated default is a future bug.
- Coming-soon items inside sub-menus must stay non-interactive. The existing non-interactive rendering lives in the link component; reuse it rather than re-implementing dimming for the nested case.
- Nine sub-destinations under one group is why this is a disclosure. If the group renders as a flat list, the criterion has failed even though every destination is reachable.
