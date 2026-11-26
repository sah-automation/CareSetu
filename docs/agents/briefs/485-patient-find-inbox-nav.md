# Brief - 485 Patient Find page + Inbox coming-soon nav

**Ticket:** #485 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The patient shell stops lying about navigation: `/patient/find` becomes a real authed directory-browse page reusing the verified-directory client and provider cards (blueprint §5.3), with "Book consultation" deep-linking into the intake pick step when an intake is in progress. "Inbox" is dimmed as coming-soon until Phase 13 (`FEAT-019`/`MOD-010`); "Bookings and Orders" stays coming-soon by design. After this, no patient nav item 404s and no dead nav item navigates.

AC:

- [ ] `/patient/find` renders the verified-directory browse page under the patient shell (provider cards, booking deep-link into the pick step when an intake is in progress)
- [ ] "Inbox" flagged soon (coming-soon badge, `aria-disabled`, no navigation); "Bookings and Orders" stays soon
- [ ] No patient nav item 404s after auth
- [ ] i18n: new strings in the relevant blocks, en/hi parity passes
- [ ] Tests: nav-config (Find live, Inbox soon, Bookings soon), `/patient/find` page test via `vi.mock` of directory client + `next/navigation` deep link, AppShell nav assertions

## Read-list (in order)

1. `components/dashboard/nav-config.ts` patient entries (L72-111) + `nav-config.test.ts` - `find` (live, L74), `inbox` (live today, L89, must become `soon`), `bookings` (already `soon`) (~700 tokens)
2. `components/directory/DirectoryBrowser.tsx` (L401) + `DirectoryCard.tsx` (L83) - the verified-directory UI; note `DirectoryBrowser` takes only `{presetType?}` today - no `onSelect`, cards `Link` to `/providers/:id` (~1K tokens)
3. `lib/directory/` `search.ts` + `links.ts` (`providerProfileHref`, `directoryHref`) + `emit.ts` - the directory client the page reuses (~500 tokens)
4. `app/(patient)/patient/intake/[intakeId]/pick/page.tsx` - the pick step the "Book consultation" deep-link targets (~600 tokens)
5. `components/dashboard/BottomTabs.tsx` + `NavItemLink.tsx` - soon rendering (`aria-disabled` `data-soon`, `SoonBadge`) (~400 tokens)
6. `app/(directory)/directory/page.tsx` (public browse) - what the authed page reuses vs wraps (~700 tokens)
7. `lib/i18n/dictionaries.ts` `nav` block + parity walk; `AppShell.test.tsx`/`BottomTabs.test.tsx` patterns (~500 tokens)

## Do NOT read

- Doctor console, backend modules, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- Known pre-existing (unrelated): frontend homepage parity fails on one Daltonganj string; backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - nav-config (Find live, Inbox soon, Bookings soon), find page from directory fixtures, AppShell nav
- `npm run typecheck`

## Handoff notes

- Inbox pending Phase 13 (`FEAT-019`/`MOD-010`); bookings pending Phase 9 - dim them, do not build pages.
- Blueprint §5.3 is the binding spec for the authed Find Care page; "Book consultation" resumes an in-progress intake's pick step, not a fresh physician-pick flow.
- `DirectoryBrowser` may need a booking/`onSelect` seam or a wrapper in the patient page - check `lib/directory/links.ts` and the pick-page continuation target before extending the shared component.
