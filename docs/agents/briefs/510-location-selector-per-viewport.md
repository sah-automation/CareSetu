# Brief - 510 One location selector per viewport on patient Home and Find Care

**Ticket:** #510 · **Parent:** #510 (this ticket is the spec; authored via `/to-spec`) · **Refreshed:** 2026-09-22
**Reading surface:** ~10K tokens (budget 10K) - within budget. The spec text below is the ticket itself (already held); all reads are targeted slices, never whole files.

## Scope

Give every patient page exactly one interactive location selector per viewport, matching the PROTO-2.7 binding (chip in the desktop top bar; chip at the top of the mobile feed). Home already does this; Find Care does not.

Acceptance (from the ticket's Decision + Solution sections):

- [ ] Find Care (`/patient/find`) mounts the mobile-only feed `LocationChip` (placement `feed`, `lg:hidden`) as the first content element, above the continuation banner - the same component and placement style as the Home feed chip (`patient-home-greeting` strip).
- [ ] Desktop Find Care shows the top-bar chip only: the static location line that the shared directory browse renders under the search button is absent when embedded under the patient shell. Public `/directory` keeps its static location line and its beachhead fallback, unchanged.
- [ ] `DirectoryBrowser` drops its `locationLabel` prop and its static location line renders only when NOT embedded (i.e. `baseRoute` is absent). The authed embed relies on the shell's `LocationChip`; the chip already reads the profile draft `area`, so the draft stays the single source of truth - no new data seam.
- [ ] Invariant after the change: exactly one interactive selector per viewport on Home and Find Care (top-bar chip at the `lg` breakpoint and up; feed chip below `lg`). The existing two-placement responsive swap (`topbar` desktop-only / `feed` mobile-only) is preserved - do not promote a chip into the shell.
- [ ] No schema, API, glossary, or i18n changes. `STRINGS[lang].loc` and the profile draft `area` seam (#501) already exist.

## Read-list (in order)

1. **Ticket #510** - the full spec (Problem / Solution / User Stories / Decisions / Testing). (~1.5K, already held)
2. **`LocationChip`** (`components/patient/location/LocationChip.tsx`) - the reused component: props `{ placement: "topbar" | "feed"; className?: string }`, test ids `location-chip-<placement>` / `location-sheet`, the bottom-sheet picker, and persistence through the profile draft `area`. The find page mounts `placement="feed"`. Do not modify it. (~2K)
3. **`FindCareBrowser`** (`components/patient/find/FindCareBrowser.tsx`) - the edit target. Today it reads the persisted area via `useOptionalProfile`/`serviceAreaLabel` and passes it to `DirectoryBrowser` as `locationLabel`; that plumbing goes away and the feed chip mounts here. (~1K)
4. **`DirectoryBrowser`** (`components/directory/DirectoryBrowser.tsx`, cited slices only) - the props interface (`presetType`, `baseRoute`, `cardGridClassName`, `locationLabel`), the commit base (`baseRoute ?? DIRECTORY_ROUTE`), and the static `directory-location` span. Change: gate the span on `!baseRoute`, remove `locationLabel` from the interface and the `?? t.locationDaltonganj` fallback logic. Read only those slices, not the whole 426-line file. (~1.2K)
5. **Home page feed-chip mount** (`app/(patient)/patient/page.tsx`, lines ~74-95) - the parity baseline: `<LocationChip placement="feed" className="inline-flex lg:hidden" />` inside the greeting strip. The find-page chip mirrors this. (~0.6K)
6. **`find/page.test.tsx`** (harness + the "#501 default location" block) - the page-level seam. The harness mocks `ProfileContext.useOptionalProfile` and `next/navigation`; the two `directory-location` tests become feed-chip assertions. (~2K)
7. **`DirectoryBrowser.test.tsx`** (harness + the "location indicator (#501)" block) - the component seam. The `locationLabel="Bishrampur"` test is removed (prop dies); add: public render (no `baseRoute`) keeps the beachhead line; embedded render (`baseRoute` set) omits it. Existing card/filter/URL tests are untouched. (~1.8K)
8. **Home `page.test.tsx` #501 block** (lines ~317-407) - the prior art the new chip tests mirror: chip label from persisted area, beachhead fallback, sheet opens with single-city + coming-soon note, apply-persists into the draft, hi localization. (~1.2K)
9. **`ui-blueprint.md` §5.2/§5.3** (~lines 286-305) - the binding posture for Home vs Find Care chrome. Skim only; the brief encodes the placement contract. (~0.7K)

## Do NOT read

- The rest of `DirectoryBrowser.tsx` outside the cited slices (filter chips, search, cards, result states) unless a failing test pulls you in.
- The rest of the 1361-line home `page.test.tsx`, the full `find/page.test.tsx`, or the full `DirectoryBrowser.test.tsx` outside the cited blocks.
- `lib/i18n/dictionaries.ts` - no string changes; `STRINGS[lang].loc` already exists.
- Backend, other role shells (doctor/partner/operator), the public homepage, auth/proxy, or `docs/archive/`.
- `prototype/` full files - the binding contract for the location chip is captured in the ticket and read-list item 5.
- E2E/integration suites - this is client-chrome; unit seams cover it.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - green for the home, find and DirectoryBrowser suites on 2026-09-22. **Known infra flake unrelated to this ticket:** vitest reports `2 failed | ... passed` from worker timeouts on unrelated files; the failing files MOVED between runs (record page, verification page) and pass in isolation when re-run directly. Do not attribute them to this work.
- `npm run typecheck:frontend` - green **after clearing a stale `apps/frontend/.next`**: the dev-types cache can hold a corrupt `routes.d.ts` (`error TS1128/TS1109`); `Remove-Item -Recurse -Force apps/frontend/.next` then re-run. `.next` is gitignored.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - green on: the find-page suite (feed chip renders persisted area / beachhead fallback, opens the sheet, `directory-location` absent + the existing resume-banner and filter-commit tests), the `DirectoryBrowser` suite (public keeps the beachhead line; embed omits it), and the home suite (unchanged parity baseline).
- `npm run typecheck:frontend` - green (clear `.next` first if stale).
- `npm run lint` - pre-commit clean.
- Manual spot-check (optional): at ~390px and ~1024px+, `/patient` and `/patient/find` each show exactly one selector; choosing a city on Find Care persists to the profile area and reflects on Home.

## Handoff notes

- **Spec seams were confirmed with the user** before publication: page-level seam on `/patient/find` + component seam on `DirectoryBrowser`; home `#501` block is the parity baseline.
- **The dedupe contract:** `DirectoryBrowser` knows it is embedded because `baseRoute` is provided (only `/patient/find` passes it). Embedded => the shell owns the location control; the static `directory-location` span only exists on public browse (no selector anywhere there). Remove `locationLabel` entirely - FindCareBrowser is its only caller; leaving a dead prop is not acceptable.
- **Keep the one-per-viewport invariant:** top-bar chip is `hidden lg:inline-flex`, feed chip is `inline-flex lg:hidden`. Both are the same `LocationChip` component with a different `placement` and responsive wrapper. The find page mounts the mobile-only feed chip at the top of its content, above the continuation banner, so its position stays stable across patient pages; do NOT add a shell-level mobile chip (that would land above the Home greeting and break the PROTO-2.7 reading order).
- **No new seams, data routes, or strings:** the chip reads the profile draft `area` via `useOptionalProfile` (existing #501 seam); the picker persists through `updateDraft`. Changing location on Find Care flows through the same draft that drives the default area filter.
- No blocking or sibling-ticket dependencies are open; #510 is unblocked. Prior home rework briefs (#499-#509) in this same `briefs/` dir provide acceptance context if needed, but the slices here are self-contained.
