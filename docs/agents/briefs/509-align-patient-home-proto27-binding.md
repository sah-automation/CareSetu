# Brief - 509 Align patient home Search+Recommended, Recent activity, Health snapshot (and element-level design) to the PROTO-2.7 binding

**Ticket:** #509 · **Parent:** #498 · **Refreshed:** 2026-09-22
**Reading surface:** ~29K tokens (budget 10K) - **over budget; briefed as-is by explicit user decision. A re-cut into four per-surface tickets (#502-#507-shaped) is the recommended follow-up** (see Handoff notes).

## Scope

Rebuild the reworked patient home (#498 / #499-#508) so the live home matches the PROTO-2.7 binding (`prototype/phase-2-6/shell-light.html`) element-for-element, while keeping the decisions ratified in #498-#508 (values are only ever derived from real record data - never the binding's demo KPI 128/84 and no "Log today's BP" CTA until P12 metrics logging exists - and the app's house radius tokens are kept).

Acceptance (from User Story list, faithful):

- [ ] The Recommended rail mounts **inside** the search card (`within(home-search-card)`); the search card renders scope pills + search bar + rail as one card. The rail's header row renders the "Recommended near you" title and the See-all link **together** (row-between); See-all keeps `search-see-all` test id and `findCareHref(scope)` href (no query).
- [ ] Scope pills, Search button and See-all continue to swap destinations on the same scope state (existing test-id assertions keep passing).
- [ ] The search field is a prefixed input group: left search icon (aria-hidden, non-interactive) + input; `flex:1; min-width:0` (long-query 320px regression stays green). 48px touch targets kept.
- [ ] `search.placeholder` becomes "Doctor, lab, test or medicine" distinct from `search.aria` (aria stays "Search care near you"), translated in hi, parity compile-checked via `Dictionary` type + parity test.
- [ ] Scope selector loses its outer border; inactive pill color and active-pill shadow match the binding's `.search-scope`; >=44px pill touch floor kept (documented deviation from the binding's 40px per the ui-blueprint touch-target rule; existing touch-target test stays green).
- [ ] Recent activity rows are flat divider list-tiles: emoji+label badge left, description middle, real date right ("when" column, `formatOccurredAt`). `describeEntry` gains an optional flag to omit the occurred-at from the subtitle. Rows stay non-navigating; "View all" keeps pointing at My Record. Empty/loading/failed states unchanged.
- [ ] Action-required items render as the same flat divider list-tiles (badge-left + requester/scope text) with Allow / Not now, keeping per-item actions and test ids. Card keeps warm 4px left border, title and count badge. Absent when nothing is pending (unchanged).
- [ ] Health snapshot metric slot restyles to the binding's label/row/date posture with the "Health tracking" soon badge; the report tile uses the list-tile anatomy (badge + title + when). No demo 128/84 KPI value and no "Log today's BP" CTA (existing test asserts the fabricated value never ships).
- [ ] Services tiles gain the binding's hover lift + active press motion on navigable tiles; the Soon badge sits inline on the "Order medicine" title row. Order, routes and the non-navigating Soon tile unchanged.
- [ ] Greeting heading scales to the binding's `1.75rem/700`; sub-line to `.875rem` sub-color; `patient-home-greeting` test id preserved.
- [ ] House radius tokens kept everywhere (cards `rounded-lg`, inputs `rounded-md`, tiles `rounded-lg`); only clearly-broken spots get an override, judged in the pixel-diff loop.
- [ ] No new data seams: all changed components keep using the existing providers/clients (profile, directory search, consent log, own-record timeline). No i18n surface changes beyond the one re-keyed placeholder.
- [ ] Pixel-diff comparison of the binding vs the live `/patient` at ~1440px and ~390px (returning + fresh states), before and after.
- [ ] `npm run test:unit:frontend`, `npm run typecheck` (frontend) and `npm run lint` green; the patient-home e2e assertions green where the harness allows.

## Read-list (in order)

1. **Binding visual spec** (`prototype/phase-2-6/shell-light.html` + `prototype/assets/css/base.css` + `tokens.css`): the search card + rail (shell 222-378: `.search-scope`, `.search-bar`/`.input-group`, `.rec`/`.rec-head`/`.rec-scroll`/`.rec-card` including the See-all in the rec-head at 241-244), services grid (380-401: `.svc-tile`, inline Soon badge at 392-395, accent tile), action required (403-417: list-tile + Allow/Not now), recent activity list-tiles (419-440: badge-left / desc-middle / when-right), health snapshot rail (456-497: `.filter-sheet-label` label + `.kpi` + `.badge-soon` row posture, report list-tile), greeting (198-201: `h1` 1.75rem/700 + `.sub`). CSS: `.sub`/`.small` (base.css 43-44), `.input-group`/.input-prefix (180-182), `.list-tile` + `.kpi` (456-458), `.svc-tile` + hover/press + soon (497-515), `.search-scope` + `.search-card .search-bar` + `.rec*` (531-585), `.filter-sheet-label` (594), `:focus-visible` (26). Note the prototype's 40px pills vs the house 44px floor. (~5K tokens)
2. **The composed seam** (the patient home page + its `page.test.tsx`, subset lines ~199-680): the single regression seam. The tests assert `within(home-search-card)` rail-mounting, `search-see-all` href swap per scope, the new placeholder in en and hi, action/recent/health structure, touch targets, and the 320px long-query overflow guard. Read the page and the assertion sections; do not read the whole 1281-line file up front. (~7K tokens)
3. **`SearchCard` + `findCareHref`** (`components/patient/home/SearchCard.tsx`): current pills (border + inactive tone + 44px `min-h-11`), sr-only label fed by `search.aria`, uncontrolled input fed by `search.placeholder`, See-all link at the card bottom, `SearchCardProps { scope, onScopeChange }` (takes no children today - the composition change adds a children slot). Keep `FIND_CARE_ROUTE`/`findCareHref`, `search-see-all`, `search-scope-pill`, `search-go`. (~1.5K)
4. **`RecommendedRail`** (`components/patient/home/RecommendedRail.tsx`): `RecommendedRailProps { scope }`, title-only header today, refetch-on-scope via `fetchRecommended`, scroll/3-up grid, empty/failed/loading states. Becomes a child of the search card and gains the title + See-all header row. (~2.1K)
5. **`RecentActivityCard` + `timelineView`** (`components/patient/home/RecentActivityCard.tsx`, `lib/record/timelineView.ts`): `describeEntry(entry, t, lang) -> EntryCard { icon, title, subtitle, badge }` - the occurred-at is folded into `subtitle` today (no flag); `formatOccurredAt` formats the right-hand date; `BADGE_TONE` map; `sortTimelineDesc`; `RECENT_ACTIVITY_MAX = 3`. The new omit-flag on `describeEntry` must default to today's behavior (existing record-screen call sites unchanged). (~2.8K)
6. **`ActionRequiredCard`** (`components/patient/home/ActionRequiredCard.tsx`): pending-consent rows with Allow/Not now, test ids, absent-when-empty, warm left border. Rows become list-tile anatomy. (~1.6K)
7. **`HealthSnapshotCard`** (`components/patient/home/HealthSnapshotCard.tsx`): `health-metric`/`health-metric-teaser`/`health-report`/`health-report-teaser` structure, `ReportTile`, derive-never-invent picks from `sortTimelineDesc`. (~1.6K)
8. **`ServicesGrid`** (`components/patient/home/ServicesGrid.tsx`): `ServiceTileSpec`, soon tile (dimmed span, never a link), accent tile, current stacked Soon badge - becomes inline on the title row; motion added to navigable tiles only. (~1.2K)
9. **The page's greeting section** (`app/(patient)/patient/page.tsx` lines ~64-93): `patient-home-greeting`, current `text-xl font-semibold` (1.25rem/600) + `text-sm text-txt-muted` sub-line, `t.welcome(firstName)`/`t.welcomeGuest`. (~1.6K)
10. **i18n slice** (`lib/i18n/dictionaries.ts` en 506-513 + hi 1993-2001, `Dictionary` type at 1417, `SearchStrings` at 1423) + the parity test (`dictionaries.test.ts`): re-key the placeholder in both locales; parity is enforced automatically - do not break the hi block's shape. (~2K)
11. **Token/radius/focus vocabulary** (`apps/frontend/tailwind.config.ts` radius overrides ~80-88, `apps/frontend/src/app/tokens.css` radius vars 43-45, focus `ring` value) + the ui-blueprint touch-target floor (`docs/design/ui-blueprint.md` §9.4, >=44px): the house scale this ticket must stay on. (~1.3K)
12. **Prior art** (`channels.test.tsx` pins `patient-home-greeting`; e2e `tests/e2e/auth-loop.spec.ts` greeting + axe scans, `tests/e2e/patient-journey.spec.ts` greeting after registration): prove these stay green. (~2.7K)

## Do NOT read

- Backend, other role shells, the public homepage, the access-audit surface.
- The rest of the 1281-line `page.test.tsx` outside the cited assertion subset, unless a failing assert pulls you in.
- Unrelated i18n sections of the 2668-line dictionary (only the two `search.*` slices and the type exports).
- `docs/archive/`, prototype demo-state annotation mechanics, the full `shell-light.html` outside the cited ranges.
- P12 metrics/P9 report ingestion - they do not exist; the snapshot displays real values only when present.
- The full e2e specs, if a targeted run of the two home assertions is green.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - green on 2026-09-22 (87 files / 1189 tests). **Known flake unrelated to the home:** `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx > CaseWorkspacePage stage + forced review` intermittently fails; a re-run of the file is green. Do not attribute it to this ticket.
- `npm run typecheck:frontend` - green.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - all existing home assertions + new within-search-card/prepend-placeholder/structure assertions green; `npm run typecheck:frontend`; `npm run lint`.
- Pixel-diff harness (throwaway, outside the repo in the shared temp area): screenshots the binding `shell-light.html` and the live `/patient` at ~1440px and ~390px, returning + fresh states, before and after the change - logged in via the dev mock-OTP flow with record/directory data seeded so recent, health and rail slots are non-empty. The diff, not class-name inspection, is the acceptance for design parity.
- `npm run test:e2e` on the patient-home assertions (`auth-loop.spec.ts`, `patient-journey.spec.ts`) where the harness allows.

## Handoff notes

- **Deviation recorded:** measured reading surface ~29K tokens vs the 10K SIZING-GATE. Briefed as-is by explicit user choice. Recommended re-cut if it ever needs re-working: (1) search card + recommended rail composition + scope pills, (2) search field + placeholder copy, (3) recent activity + action required list-tile anatomy, (4) health snapshot + services grid + greeting. Each stays within budget on the shared `page.test.tsx` seam.
- **Composition seam:** `SearchCard` takes a children slot; the page passes `<RecommendedRail scope={searchScope}/>` inside it. The rail's header becomes `border-t divider` + `row-between` with the title and the `search-see-all` link; the link keeps `findCareHref(scope)` with no query, so the page.test href assertions stay green.
- **`describeEntry` flag:** add an optional omit-occurred-at flag defaulting to false (existing record-screen call sites unaffected). The home then renders the date once, in the right-hand "when" column, via `formatOccurredAt` on the raw `occurred_at`.
- **Placeholder copy:** en "Doctor, lab, test or medicine" / hi translated; `search.aria` and the sr-only label stay "Search care near you". Parity is enforced by `Dictionary = typeof en` + the dictionaries parity test - the hi block must keep shape parity.
- **Radius/house consistency:** the binding is one notch larger globally (radius-lg vs the house); do not bump the app's scale. Parity is judged on proportions in the pixel-diff loop; only clearly-broken spots get an override.
- **Never ship the binding's demo KPI (128/84) or the "Log today's BP" CTA** - an existing home test asserts the fabricated value never renders.
- The parent #498 must remain OPEN (do not close or modify it beyond this chain driving it).
- Prior briefs for the nine rework tickets live in this same `briefs/` dir (#499-#508) if the implementer wants acceptance context; the #508 review brief summarizes the combined baseline.
