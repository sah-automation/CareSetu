# Brief - 541 Doctor Patients page + live nav entry

**Ticket:** #541 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The doctor's Patients nav entry goes live and lands on a real page with Current and Past groups, rows showing consent-scope badges and the latest case stage, a light name search/filter, and a per-patient detail view (drawer or page) surfacing contact/photo/consultation history, a deep link into the case workspace, and - only under a live `health_background` grant - the health background. Denied sections render as a calm locked "not shared" state, not an error (US-11..US-19). The page works on desktop and mobile (doctor mobile gets the Patients destination in its bottom tabs; no regression to existing tabs). Every client read goes through the gated detail API; no client-side permission holes. All copy EN/HI.

AC:

- [ ] Patients nav entry is live (un-sooned with the config + test) and the page renders Current/Past groups from the list API
- [ ] Rows show granted scope badges + latest case stage; the search box filters by name
- [ ] Detail view shows contact/photo/history/deep link and a locked "not shared" state for ungranted sections (incl. health background without its grant)
- [ ] Desktop and mobile verified; mobile tab config gains the Patients destination without regressing existing tabs
- [ ] Empty/loading/error states present; EN/HI parity; component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The two backend API shapes from #539/#540 (the delivered Patients list + detail response contracts) - the Current/Past groups, scope badges, stage, and locked-section shape the page renders; grep the shipped routes (~0.6K).
2. An existing doctor console page + its client lib to mirror - e.g. the review screen `app/(doctor)/doctor/review/...` + `lib/intake/api.ts`, and `lib/care/api.ts` for the case-workspace deep link shape (~1.5K).
3. `components/dashboard/nav-config.ts` + `nav-config.test.ts` - the un-soo pattern (drop `soon: true` from the doctor Patients entry; `NavItemLink`/BottomTabs render it live automatically) (~1K).
4. `components/dashboard/BottomTabs.tsx` + `AppShell.test.tsx`/`channels.test.tsx` - the mobile bottom-tab config path for adding the doctor Patients destination without regressing existing tabs (~1K).
5. The locked/empty/loading primitives: `EmptyState`, `ErrorBanner`, `Skeleton`, chips (inline `rounded-full` tone classes today) (~0.4K).
6. The i18n `doctorConsole` block + `dictionaries.test.ts` parity for all new copy (~0.5K).

## Do NOT read

- Patient home internals, backend module code beyond the API contracts from #539/#540, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - page/nav/tab/detail-locked-state tests + parity green.
- `npm run typecheck` - clean.

## Handoff notes

- Requires #539 + #540 landed (the API contracts); do not invent client-side permission logic - the detail view renders exactly what the gated API returns, and ungranted sections come back as a locked shape (never an error).
- The nav un-soo touches `NAV_CONFIG.doctor` only; the landing page's hardcoded coming-soon cards are elsewhere (#544) and unrelated.
- Mobile: adding the Patients destination goes through `splitMobileTabs`/`NAV_CONFIG`, preserving the center accent and overflow behavior asserted by the shell tests.
- No em-dashes anywhere (lint-gated); use simple dashes.
