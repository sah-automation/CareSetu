# Brief - 675 Case workspace: Pre-summary Confidence alignment and tab focus-visible ring

**Ticket:** #675 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~1.7K tokens (budget 10K) - within budget

## Scope

Two small case-workspace fixes. In the Pre-summary tab, the Confidence row moves into the same two-column key/value layout used by Duration and the other fields so the label-to-value spacing matches; the low-confidence verify chip stays in the value cell and the confidence element keeps its existing test id. The workspace tab buttons change from a `focus`-triggered ring to a `focus-visible`-triggered one, so a mouse click leaves no border while keyboard focus still shows an indicator; the selected-tab underline is unchanged.

## Acceptance criteria

- [ ] The Confidence label and percentage sit in the same key/value alignment as Duration and the other fields
- [ ] The low-confidence verify chip remains next to the confidence value
- [ ] The confidence element keeps its existing test id
- [ ] Clicking a tab with a mouse leaves no border or ring; keyboard focus still shows a visible focus indicator
- [ ] The selected-tab underline indicator is unchanged
- [ ] The Pre-summary and other tabs are otherwise unaffected; existing tests pass
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The case-workspace Pre-summary confidence-row region and the Duration and other key/value rows - the two-column layout the Confidence row must join. Note the current `flex items-center gap-4` wrapper and the `ml-1` value spacing that cause the mismatch. (~500 tokens)
2. The workspace `WorkspaceTabs` component and its tab-button classes - the `focus:ring-*` utility to convert to `focus-visible:ring-*`. (~300)
3. The workspace test blocks that assert the confidence test id and the tabs - keep them green. (~500)
4. The design system's button focus discipline (button primitive / `ui-blueprint.md`) - the `focus-visible` convention this tab must match. (~300)

## Do NOT read

- The backend.
- The other workspace tabs beyond the confidence row and the tablist.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - confidence-alignment and tab focus-state assertions, existing tabs suite still green.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **`focus-visible`, not `focus`.** The fix is the design system's button discipline: a mouse click leaves no ring, keyboard focus still shows one (user story 31). Do not remove the ring entirely.
- **Keep the confidence test id** and the verify chip's position in the value cell; the low-confidence warning must stay visible (user stories 28-29).
- **The underline indicator is untouched** - it is the selected state, not the focus state.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
