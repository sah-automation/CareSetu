# Brief - 575 Console sidebar: narrow the expanded rail, leave the collapsed rail untouched

**Ticket:** #575 · **Parent:** #560 (front five defects, part 14 of 16) · **Refreshed:** 2026-09-27
**Reading surface:** ~1.7K tokens (budget 10K) - within budget
**Chain position:** 14 of 16, immediately after #574. **Read `docs/agents/briefs/574-sidebar-collapse-control-and-footer.md` first; it establishes the sidebar's composition, the header, the footer, the dictionary keys and the new test hooks, and none of it is re-listed here.**

## Scope

One Tailwind utility changes. The expanded console rail is narrower; the collapsed rail, the per-role persistence, the sticky / scrollable / phone-hidden behaviour and the whole sidebar composition are untouched.

**The whole ticket is guarded by existing assertions, and the guard is the acceptance criterion** - not a note attached to one. Two separate test sites pin the collapsed width, and neither may be edited:

| pin                                                                  | file:line               | what it holds                                                                |
| -------------------------------------------------------------------- | ----------------------- | ---------------------------------------------------------------------------- |
| `expect(sidebar.className).toContain("w-16")` after the toggle click | `AppShell.test.tsx:854` | the collapsed width, in the same test that pins the expanded width at `:849` |
| the same, after adopting a stored `"collapsed"` preference           | `AppShell.test.tsx:865` | the collapsed width, on the adopt-on-mount path                              |

**The mechanism.** The two widths are one ternary in one expression, `collapsed ? "w-16" : "w-60"` (`Sidebar.tsx:64`). Narrow only the expanded rail, so change only the `false` branch. The `true` branch is untouched, `w-16` is still the literal the two pinned assertions match, and **they pass without being edited**. That is how "the collapsed rail did not change" is guaranteed rather than assumed. If you find yourself editing line 854 or 865, you have changed the collapsed rail - stop.

**A third guard that is not a test.** The collapsed flyout is positioned `fixed left-16` (`Sidebar.tsx:224`), which hardcodes the collapsed rail's width so the hover label sits flush against the rail's trailing edge. Narrow the collapsed rail and the flyout detaches from the rail with **no test failing anywhere in the repository**. That is why the collapsed width is not "just a number", and why the `w-16` pin is load-bearing rather than decorative. Do not touch `left-16` in this ticket.

### UNRESOLVED - the ticket names no amount

#575's first acceptance criterion reads: "The expanded rail is narrower than today, **by the amount this ticket names**." **The ticket names no amount.** Neither does its parent: #560's Implementation Decision §5 says only "The expanded rail narrows", and user story 34 says only "I want the expanded sidebar to be narrower, so that more of the clinical workspace is visible."

So the number is an open decision, and it is yours to make and justify - not something to leave implicit in a class string, and not something to stall on waiting for. What the tree does constrain:

- Both widths are **literal Tailwind width utilities in a ternary** - not tokens, not a CSS module, not a class map. `theme.extend` in `tailwind.config.ts` declares `colors`, `borderRadius` and `boxShadow` only; there is **no `width` key**, so `w-*` is the stock spacing scale. #560 forbids adding or re-valuing a token anyway, and #564's token gate only governs colour utilities, so a `w-*` change is outside it.
- `w-16` = 4rem = **64px**. `w-60` = 15rem = **240px**. The prototype that produced them records the same pair: `--shell-sidebar-w: 240px` / `--shell-sidebar-w-collapsed: 64px` (`prototype/assets/css/tokens.css:57-58`).
- The brand header is `h-14 ... px-4` and the nav is `p-2`, with `min-h-11 px-3` rows and a `size={20}` icon; the footer is `p-2` with `min-h-11 px-3` rows. **Any width that drops the row content below icon plus padding starts truncating labels.**
- **#574 has just added a 44px control to that same brand header.** The header is `h-14` (56px) with a 44px-tall control, and the header's `px-4` was already a live trap in the collapsed 64px rail (see #574's brief, "The two traps in the brand header row"). Your width decision and #574's header centring decision are now coupled. Read that section before choosing.
- **Check against the longest `nav.*` label per role**, not the shortest: doctor's `Patients` / `Profile`, partner's `Bookings & Orders` / `Profile & Settings`, operator's `Verifications` / `Disputes` (from `NAV_CONFIG` in `nav-config.ts`, labels in `dictionaries.ts` `nav.*`).

**Record the chosen value, its reason, and the labels you checked on the ticket.** An unreviewable "narrower" is exactly the kind of silent scope decision the next ticket inherits. If the repo owner must confirm a specific number, flag that and say which number you shipped behind the flag.

## Spec excerpt

One sentence carries the persistence half. `docs/design/ui-blueprint.md` §2.4, line 145:

> At `lg` and above: full shell shows the sidebar expanded by default; user can collapse it to an icon rail and that choice persists per role.

**There is no spec sentence naming any width**, for either state. The rail's widths are the application's own choice, sitting inside "collapsible left sidebar" (§2.3, line 138) and #560's "the expanded rail narrows". Do not go looking in the blueprint or the prototype for a target number - the prototype records the _current_ pair, not a goal. The one spec-level constraint that does bear on a narrower rail is §9.4 line 597, "touch targets >= 44px", which a width change cannot violate because the row heights are `min-h-11`, not widths.

### The parent spec backs the guard, verbatim

This is the sentence that makes the guard above a spec requirement rather than a reviewer preference. #560 `### 5. Doctor console sidebar` (line 158):

> The expanded rail narrows; the collapsed rail keeps its current width **so the pinned width assertions for the rail do not move** and the rail a doctor is used to does not change.

**"so the pinned width assertions for the rail do not move" is a direct instruction about the test file.** It anticipates exactly the edit that would be tempting - moving the assertion along with the class - and forbids it. Cite this line in the PR description; it is the shortest possible answer to "why didn't you update the test?"

## Read-list (in order)

1. **#574's brief, read-list item 1 only** - `Sidebar.tsx`, and inside it only the rail element `:61-68` and the flyout's positioning class `:219-225`. Everything else #574 established (the brand header row, the footer, the toggle's classes, the two `nav.*` keys, the `sidebar-brand` / `sidebar-footer` test hooks, the seven toggle call sites, the collapsed-rail accessibility block) is inherited - **do not re-read the component for it.** (~0.2K)
   - **A deliberate seven-line deviation from the ticket's own do-not-read.** #575's context pack says not to read "the sidebar's item renderers and flyout, which this change does not touch", and that is right about the _change_. Read `:219-225` anyway, because the flyout's `fixed left-16` is the collapsed width hardcoded a second time, and **no test in the repository covers it.** Seven lines is the cost of knowing that a future collapsed-rail edit would detach the hover label from the rail with a green suite. Read those seven lines and nothing else of the flyout.
2. **`AppShell.test.tsx` lines 834-892, whole** - the `full-shell collapse preference persistence` describe, and this is the whole read that matters. `renderOperator` 835-842. Test 1 "defaults expanded, collapses on toggle, and persists per role" 844-857: `data-collapsed` pins at 848 and 853, the **`w-60` pin at 849**, the **`w-16` pin at 854**, the per-role key and value pin at 855. Test 2 "adopts the stored preference on the next visit" 859-866: the stored `"collapsed"` at 860, the **`w-16` pin at 865**. Test 3 "keeps preferences independent between roles" 868-881: `caresetu.sidebar.partner` = `"expanded"` at 879, `w-60` at 880. Test 4 "labels toggle accessibly in both states" 883-891. **The only assertions you will edit are the two `w-60` pins, at 849 and 880. The two `w-16` pins, at 854 and 865, you will not edit - and their passing untouched is the criterion.** (~0.6K)
3. **`AppShell.test.tsx` lines 632-654** - the `describe.each(["doctor", "partner", "operator"])` and its first case, "shows a collapsible sidebar plus topbar, with bottom tabs for phones", which pins `hidden` and `lg:flex`. This is the "hidden on phones, unchanged" criterion and it already exists. (~0.15K)
4. **`AppShell.tsx` lines 91-100** - the two persistence effects, so you can confirm at a glance that nothing here needs to change: read `sidebarStorageKey(role)` after mount, write back `"collapsed"` / `"expanded"`. (~0.2K)
5. **`nav-config.ts` lines 301-305** - `sidebarStorageKey`, and only as far as the tests assert it (`caresetu.sidebar.operator`, `caresetu.sidebar.partner`). (~0.15K)
6. **`tailwind.config.ts`, the `theme.extend` key names only** - confirm there is no `width` key, so `w-*` is the stock scale and both widths are literals. Do not read the colour tree. (~0.15K)
7. **`prototype/assets/css/tokens.css` lines 57-58** - the two prototype width custom properties, as the origin of `w-60` / `w-16`. Read-only reference; `prototype/` is gitignored and out of scope for the whole set. (~0.1K)
8. **Grep confirmations** - `w-16`, `w-60`, `left-16`, `sidebarStorageKey`, `caresetu.sidebar.` across `apps/frontend/src` and `tests/`. **Re-run these after the edit** and confirm `w-16` still has exactly one production site, `left-16` is unchanged, and its two test assertions have no diff. (~0.15K)

**Total: ~1.7K tokens. PASS** (budget 10K).

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`.** This ticket touches no module, no event, no API, no schema, no ADR and no session transport; `CONTEXT.md`'s hard gate does not fire.
- **Everything #574's brief already established** - the brand header, the footer, the collapse toggle's classes, the two `nav.*` dictionary keys, the new `sidebar-brand` / `sidebar-footer` test hooks, the whole `CollapsedNavItem` accessibility block. Read that brief; do not re-read the component to re-derive it.
- **`Sidebar.test.tsx`.** The collapsed-rail block is in the fast loop and must pass untouched; you do not need its text to change one string. It is named in Done-verify, not in Read-list.
- **`NavItemLink.tsx`, `BottomTabs.tsx`, `Topbar.tsx`, `AccountMenu.tsx`, and `nav-config.ts`'s `NAV_CONFIG` body.** The rows that might truncate do not need reading - the labels are in `dictionaries.ts` `nav.*` and you can read the three or four longest from a grep.
- **`dictionaries.ts`.** 206KB / 3399 lines, and this ticket adds no string. If you need a label, grep `nav-config.ts` for the `labelKey` and read that one line of the dictionary.
- **`docs/design/ui-blueprint.md`** beyond line 145. §1.2 tokens are #564's territory.
- **Backend code, migrations, e2e specs, `docs/standards/*`.** `tests/e2e/` contains no sidebar spec (grep for `sidebar` returns nothing).
- **The rest of `AppShell.test.tsx`.** Lines 1-120 are mock plumbing, 121-177 are fixtures, 209-631 are the light shell, the patient mobile account surface and `maskedPhone`, 632-833 is the `describe.each` and the doctor Cases count pill - none of it moves.
- **`prototype/`** beyond the two width lines. Gitignored, out of scope for the whole set.

## Key facts and prior art

- **The width is one expression, not two rules.** `cn("sticky top-0 hidden h-dvh shrink-0 flex-col overflow-y-auto border-r border-hairline bg-surface transition-[width] duration-200 lg:flex", collapsed ? "w-16" : "w-60")`. The `w-*` is the second argument; everything in the first is the rail's behaviour and must survive byte-identical.
- **The width animates.** `transition-[width] duration-200` is in the first argument, so a narrower expanded width animates smoothly on both the toggle and the mount-adoption. Nothing to add; just do not remove the transition while you are in the class string.
- **`data-collapsed` is the state; `w-*` is the presentation.** `data-collapsed={collapsed || undefined}` is pinned at `Sidebar.test.tsx:118-121` and `AppShell.test.tsx:848, 853, 864`. Do not fold the two into one, and do not drive the width off the data attribute.
- **The rail is `sticky top-0 h-dvh overflow-y-auto`, not `fixed`.** The collapsed flyout's `fixed left-16` and its `getBoundingClientRect` math both depend on that, and **no test covers the rect math**. Touching the rail's position classes breaks the flyout silently.
- **The wordmark hides entirely when collapsed** (`{!collapsed && ...}`, `Sidebar.tsx:70-74`) and every section header does too (`:139`), so a narrower expanded rail only has to accommodate the wordmark plus the brand header's contents, which #574 has just populated.
- **`nav.sections.*` labels are short** (`Work`, `Account` in English; `कार्य`, `खाता` in Hindi) at `text-[11px] uppercase` with `px-3`, so the section headers are not what constrains the width - the nav rows are.

## Baseline verify (must pass before the first edit)

- `npx vitest run src/components/dashboard/AppShell.test.tsx src/components/dashboard/Sidebar.test.tsx --root apps/frontend` - the fast loop for this ticket. Both suites are green on the tree once #574 has landed. Expect jsdom `Error: Not implemented: navigation` stderr noise - not a failure.
- `npm run test:unit:frontend` - **must be green before the first edit.** #574's own baseline gate already requires #562 and #563 closed; this ticket is one step further down the chain and inherits that gate. See `docs/agents/briefs/561-working-tree-preflight.md` for the measured pre-set baseline (11 deterministic failures in two files, plus two order-dependent extras) and `docs/agents/briefs/564-design-token-gate-class-attributes.md` for the same numbers as of 2026-09-27.
- `npm run lint`, `npm run typecheck`.

## Done-verify (acceptance criteria -> commands)

- `npx vitest run src/components/dashboard/AppShell.test.tsx --root apps/frontend` - green, **and `git diff -- apps/frontend/src/components/dashboard/AppShell.test.tsx` shows no change to lines 854 or 865.** Run the diff and read it: the only edited assertion may be the expanded-width one at `:849` (and `:880` if you touch that test). **If the diff touches either `w-16` line, this ticket has failed its own acceptance criterion** - the suite is green because you moved the pin, which is the failure the ticket exists to prevent.
- `npx vitest run src/components/dashboard/Sidebar.test.tsx --root apps/frontend` - green, **with no diff at all** in that file.
- `npm run test:unit:frontend` - green.
- `npm run lint`, `npm run typecheck`.
- `git diff --stat` for this ticket touches **one production file and one test file**: `Sidebar.tsx` and `AppShell.test.tsx`. A wider diff means a later ticket's work leaked in.

### Acceptance criteria as a checklist

- [ ] **The expanded rail is narrower than `w-60`, by a value the ticket records with its reason and the labels it was checked against.** The amount is unnamed in the issue and in #560 - if it is still unnamed at implementation time, the number is a decision you must make explicitly and justify, not something to leave implicit in a class string.
- [ ] **The collapsed rail's width is `w-16` and the pinned `w-16` assertions at `AppShell.test.tsx:854` and `:865` are not edited.** This is the criterion, not a footnote: it is the mechanism by which "the collapsed rail did not change" is guaranteed rather than assumed. Prove it with `git diff` on the test file, not by reasoning about it.
- [ ] `w-16` still has exactly one production site (`Sidebar.tsx:64`), and the flyout's `fixed left-16` at `:224` is byte-identical.
- [ ] Only the `false` (expanded) branch of the width ternary changed. The rail's `sticky top-0`, `h-dvh`, `shrink-0`, `overflow-y-auto`, `border-r border-hairline`, `bg-surface`, `transition-[width] duration-200` and `hidden lg:flex` are all unchanged.
- [ ] The per-role collapse preference still persists and still restores: `` `caresetu.sidebar.${role}` `` with `"collapsed"` / `"expanded"`, adopted after mount. `AppShell.tsx` is unchanged and `AppShell.test.tsx:844-881` is green.
- [ ] The rail is still sticky, scrollable and absent on phones: `AppShell.test.tsx:632-654` green with no edit.
- [ ] The patient shell is untouched and its suite stays green: `AppShell.test.tsx:209-406` and `Topbar.test.tsx` unchanged, no diff.
- [ ] No nav label truncates at the new width, checked against the longest `nav.*` label per role (`Patients`, `Bookings & Orders`, `Profile & Settings`, `Verifications`, `Disputes`). Say which labels you checked.
- [ ] The brand header added by #574 still reads correctly at the new expanded width and still centres in the collapsed rail.
- [ ] No token added, renamed or re-valued. No new class beyond the changed width utility, and no arbitrary-value width form.

## Handoff notes

- **Do the diff check, do not reason about it.** `git diff` on the test file is a one-second check that _is_ the entire acceptance criterion. A green suite is not evidence here.
- **The named amount does not exist.** Do not stall waiting for it and do not silently pick one - pick it, justify it, record it, and flag it if the repo owner must confirm a number.
- **`left-16` is the collapsed width wearing a disguise.** Anyone who later narrows the collapsed rail detaches the hover flyout from the rail, and **no test fails**. That belongs on the parent spec as a follow-up guard, not as a fix here.
- **#574 and this ticket are coupled at the brand header.** #574 put a 44px control into a `h-14 px-4` header on a 64px collapsed rail. Read #574's brief section on the two header traps before choosing the width, and re-check the header once the width changes.
- **One line, one ticket.** If the edit needs a second class, a second file, or a new assertion, it is not this ticket - it is a finding for the parent spec.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - simple dashes only.
- **This brief is the contract.** Grep for line numbers; do not read the components.
