# Brief - 604 Label the doctor landing area Dashboard and give the account menu its own key

**Ticket:** #604 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~8.5K tokens (budget 10K) - within budget

## Scope

The doctor console's landing area is called Queue in English and by a word that is also a country name in Hindi, and the account popup reuses the logout string as its own label. Both change here, in both locales, by dictionary change only - the underlying route and the test identifiers stay stable.

Acceptance criteria (from ticket):

- [ ] The doctor sidebar and the phone tab bar both read Dashboard for the landing area, in English and in Hindi, from one dictionary key so the two surfaces cannot drift.
- [ ] The existing Hindi string for that key is replaced, because it was a word that is also a country name.
- [ ] The account popup label reads Profile and Settings in both locales from a new dictionary key, and no longer reuses the sidebar label key.
- [ ] The sidebar label for the profile entry itself is unchanged.
- [ ] The bilingual parity suite passes with every new key present in both locales.

## Read-list (in order)

1. `CONTEXT.md` - the Build-session protocol, the Cross-reference rule, the Do NOT read section, then the "Doctor console & care loops" glossary block. Tells the implementer the doc order, that `docs/archive/` is never read, and which glossary terms own the doctor console chrome. (~1.5K tokens)
2. `docs/standards/coding-standards.md` §1 Language/Runtime & Framework Lock, §6 Tests, §8 Readability & Debuggability, and §9.1 plus §9.2. The framework lock, the colocated no-globals suite rule, traceability by construction (every edit carries its ticket id in a header comment), and the Content & locale hard rule that a literal a locale change must touch is a defect. Skip §2 through §5 and §9.3. (~1.2K tokens)
3. The dictionary module's contract surface: the module header comment (why `hi` is annotated as `Dictionary` so TypeScript rejects a missing or reshaped key at compile time, and why the parity suite re-enforces it at runtime), the `export type Dictionary = typeof en` derivation, the `export const STRINGS: Record<Lang, Dictionary>` declaration, the **`nav` namespace in both locales**, and the **`accountMenu` namespace in both locales**. This is the whole edit surface. The `nav` block also carries the flat-only rule (no functions in a nav key, because every value is a `NavItemDef` label lookup) and the `sections` sub-object, which is the one member that is _not_ a label. (~1.6K tokens)
4. The nav configuration: the `NavLabelKey` mapped type over the dictionary's `nav` keys (the conditional that keeps only string-valued members and drops `sections`), the `NavItemDef` interface, the `NAV_CONFIG.doctor` array - the `{ key: "queue", labelKey: "queue", href: "/doctor", group: "work" }` entry and the `{ key: "profile", labelKey: "profile", href: "/doctor/profile", group: "account" }` entry - and the `sidebarSections` / `splitMobileTabs` selectors that fan one config into the grouped sidebar and the tab split. (~1.2K tokens)
5. The three label consumers, so the implementer can see there is exactly one lookup and three call sites: the `Sidebar` nav item's `STRINGS[lang].nav[item.labelKey]` lookup (and the separate `nav.sections[section.labelKey]` lookup for group headings, which is a different lookup and must not be touched), `BottomTabs` passing `strings[item.labelKey]` as the column label in both the tab and the More-sheet paths, and `NavItemLink` doing the same lookup. All three index the same dictionary by the same `labelKey`, which is precisely the "cannot drift" property the first acceptance criterion names. (~0.9K tokens)
6. The account menu component, only the parts that render a label: the `strings` (`STRINGS[lang].nav`) and `menuStrings` (`STRINGS[lang].accountMenu`) locals, the doctor branch's profile row that currently renders `strings.profile` into a `Link href="/doctor/profile"`, the patient branch's profile row that renders `strings.profileSettings`, and the `redLogoutItem` factory whose label is `strings.logOut`. (~1.0K tokens)
7. The bilingual parity suite: the `parityProblems` recursive walker and the two `describe` blocks, including the "ships exactly the en/hi locales" check. The walker is what makes the "every new key present in both locales" criterion mechanical - it reports a key missing from either locale and a value whose type diverges. (~0.6K tokens)
8. The two assertions that will actually move, and nothing else in either suite: the `Sidebar` suite's collapsed-rail accessible-names test, which resolves the landing link by `getByRole("link", { name: "Queue" })` and will fail the moment the value changes; and the two `AccountMenu` suite cases that assert the doctor profile row with `expect(entry).toHaveTextContent("Profile")`. (~0.5K tokens)

## Do NOT read

- `docs/archive/` - superseded by the PRD.
- `docs/roadmap/implementation-roadmap.md` and `docs/architecture/internal-modules.md` - this ticket lands no module, no phase and no traceability row.
- The doctor landing page component and its suite. The route and the review-queue content are unchanged; `nav.queue` is a chrome label, not the page's own copy. (A test that mentions "Queue" for the review-queue _content_ is a different thing entirely and stays as it is.)
- The whole profile page, the public profile renderer, the directory browser, the partner/operator/patient nav entries, and every dictionary namespace other than `nav` and `accountMenu`. The dictionary is one 3400-line file; read the two named namespaces, not the file.
- The mobile More sheet's internals beyond its label prop - the `profileSettingsLabel` it receives is the patient's row, not the doctor's.
- Any prototype or design doc. The parent already settled the copy: the label is Dashboard in English with the Hindi string replaced, and the account popup row is Profile & Settings.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - includes the bilingual parity suite, the nav-config suite and the design-token gate, so it is the real baseline for this ticket. ~1700 tests, a couple of minutes.
- `npm run typecheck` - `tsc --noEmit` over the frontend. This is the command that catches a new dictionary key added to only one locale, because `hi` is annotated as `Dictionary`.

Both were verified green on this tree immediately before this brief was written; re-run only if the tree has moved.

Not needed here: `npm run lint` at baseline (it is in done-verify), `npm run test:integration` (no backend change), `npm run test:e2e` (Playwright browsers from the shared cache, slow), `npm run check:pages` (builds and serves the Next app).

## Done-verify (acceptance criteria to commands)

- `npm run test:unit:frontend` - the bilingual parity suite is the gate for "every new key present in both locales": add the key to one locale only and this command is what fails. It also proves the `Sidebar` suite's accessible-name lookup resolves under the new value, and that the nav-config suite's loop over every `labelKey` finds a non-empty string in both locales.
- `npm run typecheck` - the `hi` locale is annotated as `Dictionary`, so an en-only or hi-only key is a compile error, and the `NavLabelKey` mapped type rejects a `labelKey` that is not a string-valued nav key.
- `npm run lint` - whitespace, prettier and the no-em-dash gate over the edited files.
- Cheap manual greps worth doing because they answer acceptance criteria no suite states: grep the `nav` namespace of the dictionary for the new Hindi value and confirm the old country-name string is gone from both locales; grep the account menu for its profile-row label expression and confirm it no longer reads the `nav` namespace.

## Handoff notes

- **No blockers.** The ticket's Blocked by section says "None - can start immediately" and that is correct: nothing in the tree consumes the value being changed. It is independent of the shadcn-primitives ticket and of the section-shell ticket, both of which are blocked _by_ other work.
- **Resolved discrepancy, read this before editing the account menu.** The ticket's "What to build" says the account popup "reuses the logout string as its own label". That is not what the code does, and the acceptance criteria plus the parent's Navigation-and-copy section both say something else. What is actually true:
  - The account menu's **sign-out row** reads the shared `nav.logOut` string, in a `redLogoutItem` factory that both the patient and the doctor branch call. That is correct as it stands and must not change - the row _is_ the logout row.
  - The account menu's **doctor profile row** reads `strings.profile`, which is `nav.profile` - the very same dictionary key the sidebar's and the tab bar's profile entry reads (`labelKey: "profile"` in the doctor nav config). That is the "reuses the sidebar label key" the third criterion names, and it is the row that becomes Profile & Settings from a new key.
  - The account menu's **patient profile row** already reads its own `nav.profileSettings` key and already says Profile & Settings. It is not the row under change.
    So the edit is: add one new key under the `accountMenu` namespace in both locales, and point the doctor branch's profile row at it. Leave the patient row and the sign-out row alone. If the intent was ever to migrate the patient row onto the new key too, that is a defensible tidy-up and it changes no rendered string - but it is not asked for, so do not do it silently.
- **The mapped type is the mechanism, and it is worth stating why the first criterion is already structurally true.** `NavLabelKey` is a mapped type over the dictionary's `nav` keys with a conditional that keeps only members whose value type extends `string`, then indexes by `keyof`. The sidebar, the tab bar and the top-nav all resolve `STRINGS[lang].nav[item.labelKey]` from the same field on the same `NavItemDef`, and the phone tab bar and the desktop sidebar are both fed from one `NAV_CONFIG.doctor` array. So changing the one dictionary value changes both surfaces at once and they cannot drift. Do **not** add a second key, a second config entry, or a per-surface override - the criterion is satisfied by the value change, not by new structure. The parent says the same: "via a dictionary change on the existing label key".
- **The `NavItemDef.key` field is not the `labelKey`, and that is why the route and the test identifiers stay stable.** `key` is the stable identity that test ids and React keys derive from; `labelKey` is the dictionary lookup. The landing entry's `key` stays `"queue"` and its `href` stays `/doctor` - only `nav.queue`'s two values change. Renaming either field is out of scope and would break test ids.
- **One existing assertion fails and must be updated: the `Sidebar` suite's collapsed-rail accessible-names test resolves the landing link by accessible name** (`getByRole("link", { name: "Queue" })`). It is the only place in the frontend suites that names the old English value, and it fails the moment the dictionary changes. That is the expected red.
- **The two `AccountMenu` assertions on the doctor profile row will stay green and that is not a bug.** Both use `toHaveTextContent("Profile")`, which is a substring match, and the new label "Profile & Settings" contains "Profile". Two options: leave them, or tighten them to the full new label (or to `getByRole("menuitem", { name: ... })`, which is the accessible-name form the patient-branch test already uses). Tightening is better - it makes the row's label an assertion rather than a prefix - but the implementer should not expect the suite to go red and should not go hunting for a failure that will not come.
- **Every new and changed string ships in both locales, and the parent records the review rule: a key present in one locale and missing from the other fails review.** The Hindi replacement for the landing label must be a real Hindi word for the landing area, and it must not be the current value, which is the Devanagari spelling of a country name.
- **Relevant ADRs.** None directly constrain this ticket. The two ADRs this parent work writes are reserved as **0021** (a profile save moves the public directory position) and **0022** (the practice position is a PIN centroid, not a geocode), and both are owned by **#622**, a sibling that does not block this one. The design-system decision that does bear on the new key is recorded precedent rather than an ADR: the i18n layer stays app-owned, so shadcn brings no translations and the dictionary is the only string source.
- **Out of scope, do not drift into:** the `nav` entries for the other three roles, the patient More-sheet's `profileSettingsLabel`, the doctor landing page's own review-queue copy, any component change beyond re-pointing the one label expression in the account menu, and any consolidation of the five copy-pasted chip groups (that belongs to the section-shell ticket).
