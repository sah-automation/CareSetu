# Brief - 06 Doctor patients list onto one shared doctor card grid

**Ticket:** #651 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

One shared doctor card serves both doctor lists, composed from the existing token-bridged card, badge, and avatar primitives rather than hand-rolled markup, so tokens stay the single source of elevation, radius, and surface. Card anatomy: avatar (initials branch - a photo reference never crosses the wire), patient name, age, chips, stage, a meta line, and a single whole-card link. Every card is one focus stop carrying an accessible name that includes the patient, and the grid collapses to a single column below the large breakpoint with no horizontal scroll.

The stage-chip tone and label mapping is extracted once here and shared, so a stage looks the same everywhere it appears on the two lists.

The doctor patients list moves onto it: a card grid per bucket with Current and Past preserved, the granted record scopes as chips, the latest case stage, and a patient with no open case saying so in words rather than showing an empty chip. The name search keeps working unchanged against the grid, the list keeps its current bounded fetch, and the loading skeleton and all three empty states are preserved. Every existing data-testid on the list is preserved, so the current suite and the end-to-end specs keep passing.

## Acceptance criteria

- [ ] One shared doctor card component exists, built from the existing card / badge / avatar primitives, and renders avatar, name, age, chips, stage, meta line, and a whole-card link target.
- [ ] The card is a single focus stop with an accessible name that includes the patient; the avatar is decorative and carries no meaning on its own.
- [ ] The grid renders as a multi-column card grid at the large breakpoint and a single column below it, with no horizontal scroll.
- [ ] The stage-chip tone and label mapping is one shared exported map, used by the patients list.
- [ ] The patients list renders cards per bucket with Current and Past grouping preserved, granted scopes as chips, and the latest case stage.
- [ ] A patient with no open case shows a worded state, not an empty chip.
- [ ] The name search still filters the cards; the list still issues its current bounded fetch and does not fetch unbounded.
- [ ] The loading skeleton, the page-level empty state, both per-bucket empty states, the no-search-results state, and the error banner all still render, with their existing test ids.
- [ ] Every existing data-testid on the patients list is preserved.
- [ ] Every new label, chip, and empty state ships in English and Hindi.
- [ ] No new runtime dependency; the card primitive is adopted for the doctor console, not bulk-added elsewhere.

## Read-list (in order)

1. The `#645` spec's "Shared doctor card" decision block plus user stories 14–23 and 66–71 - the anatomy, the whole-card-link requirement, the single-focus-stop rule, and the deliberate no-photos-on-cards decision. (~1K)
2. The doctor patients page in full - `PatientGroup`, `PatientRow`, `scopeBadges`, the local `stageLabel`, the local `LoadingSkeleton`, the search input, the four `LoadStatus` branches, and the Current / Past filter. Note the testids you must preserve: `patients-skeleton`, `patient-search`, `patient-group-${bucket}`, `patient-list-${bucket}`, `patient-row`, `patient-row-name`, `patient-row-scope-${scope}`, `patient-row-stage`, `patient-row-open`, plus the three empty states and the error banner. (~3K)
3. The card primitive in full, and the badge and avatar primitives' headers - the token bridge, the parts available, and the avatar's precedence chain and its "consumers size it via className and never fork the chain" rule. (~1.5K)
4. The doctor patients page test suite in full - the fixtures, the mocking shape, and every existing assertion you must not break. (~2.5K)
5. The dictionary file's doctor-patients and doctor-console namespaces in **both** locales - including the scope-badge map and the existing worded no-open-case string you are reusing rather than re-authoring. (~1K)
6. `docs/design/ui-blueprint.md` - the doctor surface's list section only, for the grid breakpoint convention. (~1K)

## Do NOT read

- `docs/archive/`.
- The cases page, the case workspace page, the patient profile page, the review page, and the doctor console landing page. #652 adopts the card you build; this ticket does not touch them.
- The **other** inline copies of the stage-chip tone (landing page, case workspace, review page, patient detail). The spec scopes the map's adoption to the two lists; unifying the rest is out of scope and a wider diff than asked for.
- The backend. The patients wire shape is unchanged and already pinned.
- `components.json` and the shadcn registry - you are adopting primitives that already exist, not adding new ones.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**. The single failure is pre-existing and unrelated: `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history` cannot find "No access yet.". That is your starting truth; do not fix it here and do not attribute it to your change.
- `npm run typecheck` - **currently green.**
- `npm run check:pages` - the page-weight budget. This is the gate the "no bundle regression" rule is measured by.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new card and grid cases green; every existing patients-page assertion still green; the one pre-existing failure is still the only failure.
- `npm run typecheck` - `tsc --noEmit`. The bilingual dictionary is typed as a record over both languages, so a key added to English and missing from Hindi is a **compile error**, which is the translation gate you get for free.
- `npm run lint` - prettier plus the em-dash hook.
- `npm run check:pages` - budget unchanged.

## Handoff notes

- **There is no lazy-loading convention to follow.** The repo has zero `next/dynamic` / `React.lazy` usage; route-segment splitting is the mechanism, and primitives are adopted per feature ticket rather than bulk-added. So "adopted lazily" here means: the shared card is imported only by the doctor list surfaces, so it costs the doctor routes and nothing else. Keep it that way - do not promote it into a shared barrel.
- **The list does not use `Card`, `Badge`, or `Input` today.** All three shapes are hand-rolled inline, including a raw `<input>` for the search. This ticket is where the card and badge get adopted for this surface. Do not also swap the search input; that is not in the acceptance criteria and it widens the diff.
- **The patients page fetches one bounded page and filters by name client-side**, with an explicit comment saying so. The backend already serves `search` / `page` / `per_page` and `total` is fetched but never read. This ticket **keeps that shape**. "The patients list's existing server-side pagination is unchanged" is in the spec's Out of Scope.
- **The stage tone currently disagrees across the app.** This page maps `closed` to the accent tone; the cases page maps it to a muted hairline tone. Extracting one map means picking one. The spec says the existing mapping is "reused unchanged" on both lists - follow the fuller three-way mapping the cases page already has, and leave the other four inline copies alone.
- **A patient with no open case already has worded copy** in the dictionary. Reuse that string; do not invent a second one.
- **The avatar is decorative and always `aria-hidden`.** The accessible name belongs on the card's link. Putting the patient's name in the avatar's attributes would double-announce and would violate the primitive's documented contract.
- **Photos stay off these cards.** `has_photo` is on the row type and unused. Streaming one photo per row is one request per row; the avatar's initials branch is the intended rendering, and that is a deliberate performance decision, not an oversight.
