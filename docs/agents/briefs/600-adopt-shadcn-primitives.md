# Brief - 600 Adopt the six shadcn primitives over the existing design tokens

**Ticket:** #600 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~8.8K tokens (budget 10K) - within budget

## Scope

The profile redesign needs card, input, textarea, badge, switch and toggle-group to exist before any section is built, so the adopted components theme from the project's existing tokens and multi-select semantics are auditable rather than hand-rolled. Adopting them here - with no page consuming them yet - is the prefactor that makes the rest of the redesign cheap.

Acceptance criteria (from ticket):

- [ ] All six primitives exist under the frontend component-library directory and follow the conventions of the already-adopted components (badge, skeleton, sheet) rather than inventing a new house style.
- [ ] Every colour, radius and shadow resolves through the existing design-token CSS variables - no new literal colour, radius or shadow value is introduced, and the design-token gate passes unchanged.
- [ ] The two Radix-backed primitives are the only new client-side runtime dependencies and are added to the frontend package manifest.
- [ ] A suite renders each primitive and asserts it: the toggle group reports pressed state per item and is operable from the keyboard alone, and the switch reports checked state.

## Read-list (in order)

1. `CONTEXT.md` - the build-session protocol, the cross-reference rule and the "Do NOT read" section, then its "Doctor console & care loops" glossary section. Tells the implementer the doc order, which glossary terms own the doctor console, and that `docs/archive/` is never read. (~1.5K tokens)
2. `docs/research/ui-component-library.md` - the Recommendation, the Constraints recap, and the Adoption steps & guardrails sections. The evidence behind this adoption: shadcn on the Tailwind v3 registry with the Radix base, adoption strictly lazy and per feature (never a bulk addition), the string layer stays app-owned, and the NFR-003 1.5 MB page budget every addition is measured against. The Comparison table and the "Why this recommendation" prose are already-settled history, skip them. (~2.3K tokens)
3. `docs/standards/coding-standards.md` §1 Language/Runtime/Framework Lock, §6 Tests, §8 Readability & Debuggability. The framework lock, the test-layer split (unit is pure, colocated), and the traceability-by-construction rule that every copied primitive's header comment carries its ticket id and the upstream source. (~1.0K tokens)
4. The shadcn slot bridge: the `--ui-primary`, `--ui-primary-fg`, `--ui-secondary`, `--ui-secondary-fg`, `--ui-destructive`, `--ui-destructive-fg` and `--scrim` entries in the design-token stylesheet, and the `background` / `foreground` / `popover` / `primary` / `secondary` / `muted` / `destructive` / `border` / `input` / `ring` colour groups plus the `borderRadius` and `boxShadow` aliases in the Tailwind theme. This is the complete style vocabulary a new primitive may reference; the comment above the bridge block explains why the alpha-capable slots are H S% L% triplets. (~0.9K tokens)
5. The enforcing gate, in the design-token suite: the "resolved brand palette", "class-attribute colour utilities" and "shadcn/ui slot bridge" describe blocks. These are what a new primitive may not violate: a hex anywhere but the token stylesheet, a colour utility in a class list that does not resolve to a real token path (matched by full path, never by leaf or suffix), or a bridge triplet that drifted from the token it restates. Skip the large `var()`-resolution table and the detector's red/green self-test block. (~1.3K tokens)
6. The two adopted house styles: `buttonVariants`, `ButtonProps` and `Button` in the button primitive (cva variant map, `VariantProps` composition, `cn` merge, `asChild` via `Slot`, and the header comment naming every adaptation away from upstream), and `SheetOverlay` / `SheetContent` / `SheetHeader` in the sheet primitive (`"use client"` at the top of a Radix-backed file, `React.forwardRef` over `React.ElementRef` + `React.ComponentPropsWithoutRef` of the Radix part, `displayName` assignment). (~1.0K tokens)
7. `Skeleton` and its colocated suite, plus the frontend vitest config. The suite conventions to copy: colocated beside the source, no globals (explicit `describe`/`it`/`expect` imports and an explicit `afterEach(cleanup)`), and the `include` glob. (~0.4K tokens)
8. `components.json` and the frontend `package.json` dependency block. Where the new primitives land (`ui` alias) and where the two new Radix runtime dependencies are declared - the `dependencies` block, not `devDependencies`. (~0.4K tokens)

## Do NOT read

- `docs/archive/` - superseded by the PRD.
- `docs/roadmap/implementation-roadmap.md` and `docs/architecture/internal-modules.md` - this ticket lands no module, no phase and no traceability row.
- The doctor profile page and its suite, the public profile renderer, the directory browser, the i18n dictionary. Nothing consumes the six primitives yet, so no consumer needs conforming to. The one exception is noted in Handoff notes.
- `lib/utils.ts` `cn` is one screen; do not go looking for a styling abstraction that does not exist.
- Any other module's components. The adopted five plus their suites are the whole precedent.
- The other two Radix dependencies' source. `@radix-ui/react-dialog` and `@radix-ui/react-dropdown-menu` are read through their type surface as consumed by the sheet and dropdown-menu primitives, not by reading node_modules.

## Baseline verify (must pass before the first edit)

- `npm run lint` - the no-em-dash gate and prettier run here, so a brief-quality formatting slip is caught locally.
- `npm run typecheck` - `tsc --noEmit` over the frontend.
- `npm run test:unit:frontend` - this suite includes the design-token gate, so it is the real baseline for this ticket. All three were verified green on this tree immediately before this brief was written; re-run only if the tree has moved.

Not needed here: `npm run test:integration` (no backend change), `npm run test:e2e` (Playwright browsers from the shared cache, slow), `npm run check:pages` (builds and serves the Next app; the page-weight channel list is a separate ticket's job).

## Done-verify (acceptance criteria to commands)

- `npm run typecheck` - the two new Radix packages resolve and the six primitives typecheck under the strict config.
- `npm run test:unit:frontend` - proves both the new colocated suites and, critically, that the design-token gate still passes unchanged: this is the command that answers the "no new literal colour, radius or shadow value" criterion, because the class-attribute colour gate walks every TypeScript file in the tree, including the six new primitives.
- `npm run lint` - whitespace, prettier and the no-em-dash gate over the new files.
- Manual grep sanity, cheap and worth doing because the gate is easy to satisfy by accident: confirm no new `#` hex literal and no new `shadow-`/`rounded-` arbitrary value landed in any of the six primitives.

## Handoff notes

- **No blockers.** The ticket's Blocked by section is "None - can start immediately", and that is correct: nothing in the tree depends on the six primitives existing. This ticket is on the critical path _outward_ - two siblings wait on it and cannot start without it.
  - **#605** (the reusable profile section shell) is blocked on it explicitly, because the shell renders a card. It will need `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent` and `CardFooter` exported by name.
  - **#614** (adding the profile route to the page-weight budget gate) is blocked on it explicitly, with the reason spelled out: the measurement must land with the dependencies it is meant to police. It will measure the two new Radix packages.
- **What #605 and the rest of the redesign will expect by name.** The section tickets and the identity band reach for a `ToggleGroup` whose pressed state is per item, and a `Switch` for the notification toggles. Export the shadcn-standard part names (`ToggleGroup`, `ToggleGroupItem`, `Switch`) plus the variant maps (`toggleVariants`, `badgeVariants`, `cardVariants` if you add one) so a consumer can compose without reaching into a private symbol, matching how `buttonVariants` is already exported for non-component consumers.
- **Adaptation comments are the house rule, not optional.** Every one of the five adopted primitives carries a header comment naming what was changed away from upstream shadcn. Two adaptations are already forced by the token gate and must be made deliberately: the sheet's overlay uses the `scrim` token instead of upstream's hardcoded black, and the button's ghost and outline hovers use `accent-soft` / `accent-strong` because this repo's `accent` group is the solid brand teal while upstream's is a soft selected-row surface. Expect the same class of collision on the toggle item's selected state and on the switch's checked track - resolve each through the existing token vocabulary and record why in the comment.
- **Keyboard operability has no `user-event` to lean on.** `@testing-library/user-event` is not a dependency and the whole suite is written against `fireEvent` from `@testing-library/react`. Drive the toggle group's keyboard path with `fireEvent.keyDown` / `fireEvent.keyUp` and assert the observable outcome (`aria-pressed` or the Radix `data-state`), not internal state. Adding `user-event` as a devDependency is defensible but is a manifest change the ticket did not ask for; prefer `fireEvent`.
- **Judgement call, recorded: pure-Tailwind primitives need no test-time wrapper.** `card`, `input`, `textarea` and `badge` are plain Tailwind + `cva` with no Radix and no `"use client"`, following the shape of `Skeleton` and `Button`. Keep them free of the directive so a server component can render them. The two Radix-backed ones do need `"use client"` at the top of the file.
- **Judgement call, recorded: the ticket body names "badge, skeleton, sheet" as the convention exemplars, but the matching exemplars in the tree are `Button` and `Sheet`.** `badge` is one of the six being built, not an existing component, and `Skeleton` is the thinnest of the adopted five. Read-list item 6 uses the two that actually carry the variant and wrapper conventions.
- **Relevant ADRs.** None directly. The two ADRs this parent work writes are reserved as **0021** (a profile save moves the public directory position) and **0022** (the practice position is a PIN centroid, not a geocode), and are owned by **#622**. The two design decisions that constrain this ticket are not ADRs but recorded precedent: the single-palette-source rule from the token gate's history and the lazy-per-feature adoption rule from the component-library research note.
- **There is no `role="switch"` anywhere in the repo today.** Notification toggles on the doctor profile are bare native checkboxes, and the five copy-pasted chip groups use `aria-pressed` plus a local `chipClass` factory each. Those five are the eventual consumers of the toggle group, and consolidating them is **#605**'s job, not this ticket's. Do not refactor them here.
- **Out of scope, do not drift into:** i18n strings for the primitives (shadcn adds no translations and the string layer stays app-owned; the section tickets own their own dictionary keys in both locales), any page-weight measurement, and any change to the adopted five.
