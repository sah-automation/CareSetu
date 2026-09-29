# Brief - 574 Console sidebar: collapse control to the brand header, Log out alone in a divided footer, bilingual names

**Ticket:** #574 · **Parent:** #560 (front five defects, part 13 of 16) · **Refreshed:** 2026-09-27
**Reading surface:** ~9.6K tokens (budget 10K) - within budget
**Chain position:** 13 of 16. #575 reads this brief for the width expression only and re-establishes nothing here. #576 reviews this ticket's diff against this brief.

## Scope

As a doctor (or a lab/chemist partner, or an operator - one component, one rail, driven by the role prop), the console sidebar's collapse control sits on the trailing edge of the brand header as a compact icon control, and Log out stands alone inside the existing footer divider. Both accessible names come from the shared string dictionary, in English and Hindi.

Today the footer is one undivided stack of two full-width rows - **Log out first, the collapse toggle second** - sharing `min-h-11` and `px-3`, so the navigation control reads as a nav item. The fix moves the toggle out of the footer and into the brand header. Nothing is added to the footer; a row is removed from it.

**No backend, no schema, no session transport, no new read, no new route, no new prop.** The shell keeps owning the collapse state; the sidebar keeps receiving it as a prop.

### The misattribution to stop repeating

**The Log out button is not yellow and never was.** Its classes are a neutral text token at rest, tinted to the danger text on a danger-soft background on hover (`Sidebar.tsx:95`). A repo-wide grep for `amber` / `yellow` across `apps/frontend/` and `prototype/` returns only:

- `apps/frontend/src/app/tokens.css:4` - the `warn` token's own comment
- `apps/frontend/src/lib/record/timelineView.ts:152` and `dictionaries.ts:1289` - comments about the `warn` ramp
- the pre-summary low-confidence notice (`app/(patient)/patient/intake/[intakeId]/pre-summary/page.tsx:8, 11, 555, 590, 643`) and the doctor review screen (`app/(doctor)/doctor/review/[intakeId]/page.tsx:87`) - the `warn` surface for low-confidence framing
- the operator audit tamper-attempt highlight prose
- the corresponding `prototype/` phase-7-8 and phase-4/2-6 comments

**No amber or yellow utility exists in the sidebar, in any other component, or in any prototype.** Do not go looking for it, and do not add one. The real defect is the _composition_ - a navigation control visually paired with sign-out - not the colour.

### What "descendant of the brand header" needs, and does not have

Neither the brand header (`Sidebar.tsx:69`) nor the footer (`Sidebar.tsx:87`) carries a `data-testid` or any distinguishing class today. The rail carries `data-testid="sidebar"`, the nav `sidebar-nav`, the flyout `sidebar-flyout` - the hook convention is established and the two elements you must address are the two that lack it.

The acceptance criterion "the collapse control is a descendant of the brand header" **cannot be asserted structurally until the header is addressable.** Adding `data-testid="sidebar-brand"` and `data-testid="sidebar-footer"` is the conventional route and is the one this brief recommends. Say which you chose and why in the PR - if you assert it another way, the PR needs to say what you did instead.

The toggle keeps `data-testid="sidebar-toggle"`. **Seven call sites reach it by that id** and they must all keep working: `Sidebar.test.tsx:123, 139, 212, 382` and `AppShell.test.tsx:851, 886` (`:889` reuses the same node). Rename or drop the id and all seven break at once.

### The two traps in the brand header row

1. **The touch-target floor.** Blueprint §9.4 line 597 requires touch targets >= 44px. The toggle is `min-h-11` (2.75rem = 44px) today. A "compact" control must keep 44px **in both states**. Compactness is about _width_ - dropping `w-full` and `px-3` - never about shrinking the hit area.
2. **The collapsed rail is 64px and the header carries `px-4` plus `overflow-hidden`.** `w-16` = 4rem = 64px; `px-4` = 16px each side; a 44px control placed at the trailing edge lands at x=16..60. It is inside the rail, but **off-centre by 12px**, and it will read misaligned against the collapsed nav icons and against the centred Log out icon. When collapsed, either drop the header's horizontal padding or centre the control. Judge it against `justify-center px-0` on the `w-full` Log out button (`Sidebar.tsx:96`) - that is the shape the collapsed footer row already uses, and it can be reused in the header without reintroducing the pairing the ticket is removing.

The brand header becomes a two-child row: the wordmark first (already `{!collapsed && ...}`, so it disappears entirely when collapsed) and the control pushed to the trailing edge (`justify-between`, or `ml-auto` on the control). The wordmark keeps `whitespace-nowrap`; `overflow-hidden` stays; `h-14`, `shrink-0`, `items-center`, `border-b border-hairline` all stay.

### The footer after the move

`shrink-0 border-t border-hairline-soft p-2` plus the `space-y-1` wrapper, now with one child. The single-child `space-y-1` div becomes pointless - drop it or keep it; the requirement is only that the footer contains Log out and not the toggle. **Do not touch** the Log out button's own classes at `:95` or its collapsed treatment at `:96`. Two existing tests pin it: `Sidebar.test.tsx:261-264` and `:273-275`.

### The two literals, and every assertion that names them

`Sidebar.tsx:107` - `aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}`. Note the polarity: when **collapsed**, the label reads "Expand sidebar", because it names the _action_, not the state.

They move to the `nav.*` namespace. Seven facts constrain the landing place:

- **The namespace is `nav`, not a new one.** The sidebar already reads `STRINGS[lang].nav` at `Sidebar.tsx:58`, and `.nav.sections[...]` at `:134` and `.nav[item.labelKey]` at `:180`.
- **`nav.*` carries plain strings only.** The dictionary's own comment above the `accountMenu` block (`dictionaries.ts:1031-1035`) states it: `nav.*` "indexes `nav.*` and carries one entry per NavItemDef.labelKey - **no functions allowed there**". So the two entries are two flat string keys, **not** one `collapseSidebar: (isCollapsed: boolean) => ...` function. The parity differ _does_ check function arity, so a function would technically pass parity - but it violates the stated namespace rule, and `nav-config.test.ts:68-75` asserts every `labelKey` resolves to a `string`. (`logOut`, `more` and `sections` are the existing non-`labelKey` precedents inside `nav.*`, so two more flat keys are consistent with how the namespace is already used.)
- **Parity is enforced twice, independently.** `Dictionary = typeof en` (`dictionaries.ts:1818`) plus `STRINGS: Record<Lang, Dictionary>` (`:1832`) means `tsc` fails if a key exists in one locale only; `parityProblems` (`dictionaries.test.ts:13-64`) fails it at runtime on a missing key, a shape mismatch, a function-arity divergence or an array-length divergence. You cannot land half a translation and get a green typecheck.
- **The English copy is your choice, and it decides whether the shell assertions need editing.** The issue says moving them "changes the literal strings the shell tests assert, so those assertions are updated in the same change". That is true **only if the English you ship differs from `Expand sidebar` / `Collapse sidebar`**. If you ship byte-identical English, `AppShell.test.tsx:887, 889` need **no** edit - and the criterion "assertions are updated in this change" must then be satisfied by saying so explicitly on the ticket, not by claiming a rename that did not happen. Pick the English deliberately, then reconcile the criterion against what you actually did.
- **`Sidebar.test.tsx` runs at `en` by default and does not reset the language.** Unlike `AppShell.test.tsx`, `Topbar.test.tsx` and `AccountMenu.test.tsx`, the sidebar suite never imports `__resetLangForTests` and never sets `caresetu.lang`, so it inherits the `LangContext` default and asserts English labels (`"Queue"`, `"Cases"`, `"Log out"`). That is why the move is nearly free there. If you add a Hindi assertion, set `localStorage.setItem("caresetu.lang", "hi")` **in that test only** and clear it after - do **not** add a suite-wide reset, because the collapsed-rail block is required to pass untouched.
- **Every site that names either literal**, all of which must be reconciled in the same change:

  | file                | line    | assertion                                                                                   |
  | ------------------- | ------- | ------------------------------------------------------------------------------------------- |
  | `Sidebar.test.tsx`  | 123-126 | `sidebar-toggle` has `aria-label` `"Expand sidebar"` (collapsed)                            |
  | `Sidebar.test.tsx`  | 211     | `queryByText("Collapse sidebar")` absent from the collapsed tree                            |
  | `Sidebar.test.tsx`  | 212-215 | `sidebar-toggle` has `aria-label` `"Expand sidebar"` (collapsed)                            |
  | `Sidebar.test.tsx`  | 382     | `getByRole("button", { name: "Expand sidebar" })` is reachable and fires `onToggleCollapse` |
  | `AppShell.test.tsx` | 887     | expanded toggle `aria-label` is `"Collapse sidebar"`                                        |
  | `AppShell.test.tsx` | 889     | collapsed toggle `aria-label` is `"Expand sidebar"`                                         |

  Plus `Sidebar.tsx:107` itself. Nothing else in the repository names either string - no e2e spec asserts the sidebar at all.

- **The bilingual proof for these two keys is a test, not a claim.** The dictionary already carries `nav.logOut`; the cheapest honest addition is a `#574` case in the sidebar suite that switches language and asserts the collapsed rail still exposes the toggle by both its English and its Hindi name. Prior art for the mechanism, all `localStorage.setItem("caresetu.lang", "hi")`: `Topbar.test.tsx:206`, `HealthBackgroundZone.test.tsx:971`, `PickConsentSheet.test.tsx:129`, `LangContext.test.tsx:48`.

## Spec excerpt

Three sentences carry this ticket, all from `docs/design/ui-blueprint.md`:

§2.4, line 145:

> At `lg` and above: full shell shows the sidebar expanded by default; user can collapse it to an icon rail and that choice persists per role.

§9.4, line 597:

> Labeled controls (no placeholder-only labels); touch targets >= 44px.

§9.2, line 578, the bilingual parity rule the two new keys land under:

> Bilingual parity rule: a string key missing from either locale fails review - no shipping EN-only keys in patient surfaces.

**There is no spec sentence about a brand header, a footer, or a "divided footer".** #560's Implementation Decision §5 is the authority for the arrangement, and its own words are the contract: "The brand header gains the collapse control on its trailing edge, as a compact icon control, and the footer's stack collapses to a single Log out row inside its existing divider." **The existing divider already exists** - `border-t border-hairline-soft` at `Sidebar.tsx:87`. Nothing new is added to the footer; a row is removed from it.

`prototype/phase-2-6/shell-full.html` is **not** a spec for this arrangement. It places the collapse control in `.sidebar-footer` (line 25), which is precisely the arrangement the ticket removes. Its `--shell-sidebar-w: 240px` / `--shell-sidebar-w-collapsed: 64px` (`prototype/assets/css/tokens.css:57-58`) are the origin of the live `w-60` / `w-16` and are the right prior art for #575, but `prototype/` is gitignored and out of scope for this whole set. #560 explicitly skipped a prototype pass ("the sidebar's target is the conventional professional console layout"); if the placement is contested after implementation, settle it in `prototype/`, not in app code.

Standards hook: `docs/standards/coding-standards.md` §9 / §9.1 (lines 90-99) - "Everything that varies by environment, provider, service, deployment, or scale is configuration, not code", which #560 extends to every user-facing string. Two hardcoded English UI literals are exactly what that rule forbids. Moving them to the dictionary is not cosmetic; it is the §9.1 compliance fix.

## Read-list (in order)

1. **`apps/frontend/src/components/dashboard/Sidebar.tsx`, whole (284 lines)** - the component being changed. Header comment 3-17 (note `:15-16` says "the collapse toggle is icon-only; Logout lives in the lower group" - **this becomes wrong in this change and must be updated**; `coding-standards.md` §8 line 84 expects the header to state what the file is). `SidebarProps` 39-46. `Sidebar` 48-123: the rail element 61-68 (sticky/`h-dvh`/`overflow-y-auto`/`transition-[width]`/`hidden lg:flex` all live here, and the width expression at **:64**), `data-collapsed` :66, the **brand header 69-75**, the nav 77-85, the **footer stack 87-120** with Log out at 89-103 and the toggle at 104-118. `SidebarSectionGroup` 125-153. The `CollapsedNavItem` provenance comment 155-171 (**read it; it is the blueprint §9.4 "a hover-only tooltip is not a name" argument and it is load-bearing**), then `CollapsedNavItem` 172-284 for the flyout's `fixed left-16` at :224 and the `sr-only` Soon variant at :263. (~2.4K)
2. **`Sidebar.test.tsx`, four slices, not the whole file** - the mocks and `beforeEach`/`afterEach` 1-66 (three module mocks: `next/navigation`, `next/link`, `@/lib/auth/AuthContext` returning `logout`); the two toggle cases in the flat describe 113-141; the collapsed-rail case 201-216 (asserts the toggle's `aria-label` **and** that `"Collapse sidebar"` is absent from the collapsed tree); the Log out cases 255-277; and **the whole `Sidebar #538 collapsed rail accessible names` describe 279-404**, which is the block that must pass **untouched** - every link named 283-306, no label leak 308-316, the flyout-as-description 318-337, the count in the description 339-369 (`"Cases 3"`), the toggle and Log out reachable by name 371-389, and the Soon `sr-only` case 391-403. (~2.3K)
3. **`AppShell.test.tsx`, three slices** - the mock block 43-120 (only `next/navigation`, `next/link` and the `AuthContext` mock's `logout` matter here; skip the `care/api` and profile-api hoists); the `beforeEach`/`afterEach` 178-207 (note `localStorage.clear()` at :180 and `__resetLangForTests()` at :181, neither of which the sidebar suite has); the phone-absence case 644-654 inside the `describe.each` over doctor/partner/operator at :632; and **the whole `full-shell collapse preference persistence` describe 834-892** - `renderOperator` 835-842, the width and key pins at 848/849/853/854/855, the adopt-on-mount pins at 860-865, the per-role independence pins at 869/879/880, and **the two aria-label assertions at 887 and 889**. Also 894-928, the `matchMedia` source scan and the per-role layout gate. (~1.6K)
4. **`AppShell.tsx` lines 64-117** - `FullShellBody`: the collapse state at :71, the open-cases count feeding `navItems` 77-87, and **the two persistence effects 91-100** (adopt `sidebarStorageKey(role)` after mount, mirror `"collapsed"` / `"expanded"` back). You need this to confirm that nothing here changes. (~0.5K)
5. **`nav-config.ts`** - the `NavItemDef` / `NavSectionKey` type declarations, and `sidebarStorageKey` + `sidebarSections` at 301-329. The key pattern is a template literal: `` `caresetu.sidebar.${role}` ``. (~0.35K)
6. **`NavItemLink.tsx` lines 22-26 and 50-61** - `VARIANT_BASE.sidebar` (what a nav item _is_, so you can judge that the footer toggle currently reads as one) and `ActiveIndicator` (the shared left-edge bar, one of the things you must not disturb). (~0.25K)
7. **`dictionaries.ts` lines 996-1040 and 2383-2412** - the `nav.*` block in **both** locales, plus the `accountMenu` comment at 1031-1035 carrying the "no functions allowed there" rule. **This is the only part of a 206KB / 3399-line file you read.** (~0.75K)
8. **`dictionaries.ts` lines 1818-1836** - `Dictionary = typeof en`, the per-namespace type aliases, and `STRINGS: Record<Lang, Dictionary>`. This is the compile-time half of parity. (~0.25K)
9. **`dictionaries.test.ts` lines 1-20 and 66-74** - the `parityProblems` signature and the two parity assertions. Skip the five negative self-tests at 76-127; you are adding two string keys, not a new value shape. (~0.35K)
10. **`docs/design/ui-blueprint.md` lines 145, 578 and 597 only** - the three sentences quoted in the spec excerpt. Do not read §2.3's ASCII shell diagram or the rest of §9. (~0.3K)
11. **`docs/standards/coding-standards.md` lines 90-99** - §9 and §9.1's first bullets, the hardcode ban. (~0.3K)
12. **Grep confirmations** - `Expand sidebar`, `Collapse sidebar`, `sidebar-toggle`, `sidebar-logout`, `w-16`, `w-60`, `left-16`, `amber|yellow` across `apps/frontend/src` and `tests/`. Re-run the first three after the edit to prove the seven toggle call sites still resolve. (~0.2K)

**Total: ~9.6K tokens. PASS** (budget 10K).

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`.** This ticket touches no module, no event, no API, no schema, no ADR and no session transport; `CONTEXT.md`'s hard gate does not fire (no cookies, no CORS, no middleware, no `credentials`, no deploy env).
- **The rest of `docs/design/ui-blueprint.md`.** Three lines are the whole slice. §1.2 tokens are #564's territory.
- **`AccountMenu.tsx` and its suite, `BottomTabs.tsx`, `Topbar.tsx`, `BottomTabs`' More sheet.** Out of scope for the whole set; you only need to know their suites stay green.
- **`nav-config.ts`'s `NAV_CONFIG` body and `BottomTabs`.** You are not changing any nav destination.
- **`CollapsedNavItem`'s collaborators** beyond the flyout positioning line. The collapsed rail is preserved, not edited.
- **The whole `dictionaries.ts`.** 206KB / 3399 lines. Read only the `nav` namespace in both locales. This is the single most expensive mistake available in this repo.
- **`StaffLoginForm.tsx`, `ProviderRegisterWizard.tsx`, `PatientAuthWizard.tsx`.** #562 and #563 own them; they are the blockers, not this ticket's work.
- **Backend code, migrations, e2e specs.** `tests/e2e/` contains no sidebar spec (grep for `sidebar` returns nothing).
- **`prototype/`.** Gitignored, out of scope for the set. The one prior-art pointer is quoted in the spec excerpt.

## Key facts and prior art

- **One component, four shells.** `Sidebar` takes `role: Role` and reads `NAV_CONFIG[role]` (`:54`). There is no per-role sidebar. Lab and chemist partners get the change for free because the partner console is the same component. `AppShell.test.tsx:632` is a `describe.each(["doctor", "partner", "operator"])`, and its first case (`:644-651`) asserts each full-density role gets a sidebar carrying `hidden` and `lg:flex`; `:917-927` asserts each `app/(role)/layout.tsx` pins `role="<role>"` into `<AppShell`. **Those two existing tests are the "reaches the lab and chemist console" and "absent on phones" criteria** - do not write new ones for either.
- **Per-role persistence is owned by the shell, not the sidebar.** `AppShell.tsx:71` holds `collapsed`; `:91-94` adopts the stored value after mount (the same hydration guard as `LangContext`); `:95-100` mirrors every change back. The key pattern is `` `caresetu.sidebar.${role}` `` (`nav-config.ts:303-305`), giving `caresetu.sidebar.doctor`, `.partner`, `.operator` - and `.patient`, which is written but never read, because the light shell has no sidebar. `nav-config.test.ts:250-254` pins the operator and doctor spellings. **Nothing about this changes in #574.** Do not touch `AppShell`'s effects.
- **The collapsed rail is load-bearing and must not move.** `CollapsedNavItem` (`:172-284`) is a separate renderer: a `h-11 w-11` `aria-hidden` anchor, a `role="tooltip"` flyout at `fixed left-16` (`:224`, which is the collapsed width hardcoded), `aria-label` + `aria-describedby` wiring, and an `sr-only` label for Soon entries because `aria-label` is prohibited on a role-less span. `Sidebar.test.tsx:279-404` pins all of it, including the count reaching the accessible description at `:368`. **Leave `CollapsedNavItem` byte-identical.**
- **The `left-16` coupling is the real reason #575 is guarded.** The flyout's `left-16` is the collapsed rail's width as a literal. Narrow the collapsed rail and the hover label detaches from the rail with **no test failing**. Say this on #575.
- **The rail's section groups are `nav.sections.*` driven by `NavItemDef.group`**, composed by `sidebarSections` (`nav-config.ts:317-329`). The doctor rail has `Work` and `Account`; the patient rail is flat and label-free (`Sidebar.test.tsx:192-199` pins that). Preserved, not touched.
- **The `matchMedia` source scan at `AppShell.test.tsx:894-912` reads every non-test file in `components/dashboard/`.** Your edit is in `Sidebar.tsx`, so that scan covers it: do not introduce `matchMedia`, and do not add a `matchMedia` comment either - it matches the regex regardless of context.
- **`Sidebar.test.tsx` has no `beforeEach` language reset and no `localStorage.clear()`.** If your new test sets `caresetu.lang`, it must clean up after itself or the whole file's English assertions downstream break.

## Baseline verify (must pass before the first edit)

- `npx vitest run src/components/dashboard/Sidebar.test.tsx src/components/dashboard/AppShell.test.tsx src/lib/i18n/dictionaries.test.ts src/components/dashboard/nav-config.test.ts --root apps/frontend` - the fast loop for this ticket. **Confirmed green 2026-09-27: 4 files, 91 tests passed, 11.2s.** Expect jsdom `Error: Not implemented: navigation` stderr noise - not a failure.
- `npm run test:unit:frontend` - **RED on the untouched tree at brief time.** Per `docs/agents/briefs/561-working-tree-preflight.md`, measured over six runs on `main` at `b6864ea`: 11-13 failures, of which 10 are in `StaffLoginForm.test.tsx` (**#562**), 1-2 in `PatientAuthWizard.test.tsx` (**#563**), plus a 13th intermittent in `CaseWorkspacePage` that is out of scope for every ticket in the set. **#562 and #563 must be closed before the first edit** - "the full frontend unit suite green" is a done-verify here, and you cannot attribute a red suite to your own change on a red baseline.
- `npm run lint` - confirmed green 2026-09-27 per the #564 brief (all 17 pre-commit hooks, including the no-em-dash gate).
- `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief (mypy strict: 251 files; `tsc --noEmit`: clean).

## Done-verify (acceptance criteria -> commands)

- `npx vitest run src/components/dashboard/Sidebar.test.tsx --root apps/frontend` - green, including the **new** descendant and footer-absence assertions **and** the **untouched** collapsed-rail block at `:279-404`.
- `npx vitest run src/components/dashboard/AppShell.test.tsx --root apps/frontend` - green, including `:644-654` (phone absence), `:834-892` (persistence, both widths, both aria-labels) and `:917-927` (the per-role layout gate).
- `npx vitest run src/lib/i18n/dictionaries.test.ts src/components/dashboard/nav-config.test.ts --root apps/frontend` - green.
- `npm run test:unit:frontend` - green, with #562 and #563 closed.
- `npm run lint`, `npm run typecheck`.
- `git diff -- apps/frontend/src/components/dashboard/AppShell.test.tsx` - read it and confirm the only edited assertions are aria-label literals, and only if your English copy actually changed them.

### Acceptance criteria as a checklist

- [ ] The collapse control is a **descendant of the brand header**, on its trailing edge, and is a compact icon control - not a `w-full` row. Asserted **structurally** (the header is addressable and the toggle is inside it), not by class substring.
- [ ] The footer contains Log out and **no longer** contains the toggle. Asserted **by absence** - the footer's subtree must not contain `data-testid="sidebar-toggle"`.
- [ ] The toggle keeps its accessible name in **both** states, and the chevron still flips with the state (`ChevronRight` when collapsed, `ChevronLeft` when expanded, `Sidebar.tsx:113-117`).
- [ ] The control's hit area stays **>= 44px in both states** (`min-h-11` or equivalent). Compactness is width, not height.
- [ ] When collapsed, the control is visually centred in the 64px rail rather than 12px off (the `px-4` trap above).
- [ ] Both accessible names come from `nav.*` in the dictionary as **two flat string keys** - not a function - with English and Hindi entries. Both `tsc` and `parityProblems` stay green, and the five parity self-tests are untouched and still green.
- [ ] Every site naming either literal is reconciled **in this change**, and the ticket says which: the six assertions in the table above plus `Sidebar.tsx:107`. If the English is byte-identical, the criterion is met by an explicit statement, not by a fictional rename.
- [ ] The collapsed rail's hover labels, accessible wiring, active indicator, open-case count on the collapsed label, and per-role persistence are **unchanged**, and their existing assertions at `Sidebar.test.tsx:279-404` and `AppShell.test.tsx:844-881` pass **untouched**. `CollapsedNavItem` is byte-identical.
- [ ] The section groups and the refined active state are unchanged - `Sidebar.test.tsx:170-199` green with no edit.
- [ ] The sidebar remains absent on phones with the bottom tab bar taking over: `AppShell.test.tsx:644-654` green with no edit, and the rail's `hidden lg:flex` / `h-dvh` / `sticky top-0` / `overflow-y-auto` unchanged.
- [ ] The patient shell's top navigation, bottom tabs and More sheet are untouched and their suites stay green: `AppShell.test.tsx:209-406` and `:407-616`, plus `Topbar.test.tsx` and `nav-config.test.ts`.
- [ ] The same improvement reaches the lab and chemist partner console - `AppShell.test.tsx:632-651` (a `describe.each` over doctor/partner/operator) green with no change.
- [ ] `Sidebar.tsx`'s header comment (`:3-17`) is updated: the toggle is no longer in the lower group.
- [ ] `data-testid="sidebar-toggle"` is preserved, and all seven call sites still resolve.
- [ ] No token added, renamed or re-valued. No new colour utility, and in particular **no amber or yellow utility**.
- [ ] No backend, schema, migration, API or session-transport change. No new prop, no new read, no new route.

## Handoff notes

- **The defect is composition, not colour.** "Log out is yellow" is a misattribution carried down from #560. If you start hunting for a yellow button you will burn the session and change nothing.
- **Prove the new structural assertions red before green.** Write the descendant and absence assertions against the _current_ tree, run them, capture the failure on the ticket, _then_ move the markup. Writing them after produces a test that has never demonstrated it can fail.
- **The seven `sidebar-toggle` call sites are a tripwire.** Renaming or dropping the id breaks the sidebar suite and the shell suite simultaneously, and both failures will look like your bug.
- **`nav.*` is strings only.** Do not reach for `collapseSidebar: (c: boolean) => ...`. The namespace comment forbids it, `nav-config.test.ts:68-75` would fail, and the parity differ's arity check would make the shape look blessed when it is not.
- **Add a test hook to the header and the footer.** Neither is addressable today. Prefer `data-testid`, matching `sidebar` / `sidebar-nav` / `sidebar-toggle` / `sidebar-logout` / `sidebar-flyout`.
- **Do not "improve" `CollapsedNavItem`, the section groups, the active indicator or the flyout.** The ticket preserves them, and the collapsed-rail accessibility block must pass without edits - editing it converts a preservation check into a rewrite and loses the evidence that nothing regressed.
- **Do not touch `AppShell.tsx`'s persistence effects.** The shell owns the state; the sidebar only receives `collapsed` and `onToggleCollapse` as props.
- **`left-16` on the flyout is the collapsed width in disguise.** Mention it on #575; it is the second guard on the collapsed rail after the pinned-width assertions.
- **The footer divider already exists** (`border-t border-hairline-soft`, `:87`). "Log out alone in a clearly divided footer" is satisfied by removing a row, not by adding a border.
- **Two blockers, still open at brief time** (#562, #563). The sidebar, shell, dictionary and nav-config suites are green independently, so the component and dictionary work can start while you wait - the full-suite done-verify cannot.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - simple dashes only, in code, comments and copy.
- **This brief is the contract.** Grep for line numbers; do not read the components beyond the slices above.
