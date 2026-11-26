# Brief - 483 Doctor console Cases tab + /doctor/cases index

**Ticket:** #483 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

"Cases" becomes an active doctor side-window nav item (with count pill); `/doctor/cases` renders the doctor's open care cases from the existing open-cases read, each linking into `/doctor/cases/[case_id]`. `patients`/`profile` stay coming-soon. History-panel empty-consent record wording reads "no history yet" (wording-only, no consent logic change).

AC:

- [ ] "Cases" active with count pill; `patients`/`profile` stay coming-soon
- [ ] `/doctor/cases` renders the doctor's open care cases linking into each workspace
- [ ] History panel empty state reads "no history yet" (wording only)
- [ ] i18n strings in `doctorConsole` block; en/hi parity passes
- [ ] Tests: nav-config (Cases un-sooned), `/doctor/cases` page from queue fixtures, AppShell nav

## Read-list (in order)

1. `components/dashboard/nav-config.ts` doctor entries (L112-135) + `nav-config.test.ts` (L37-43 pins every non-home staff entry as Soon - this assertion changes for `cases`) (~700 tokens)
2. `app/(doctor)/doctor/page.tsx` open-cases cards (L260-296) + its test - the list/read pattern to reuse on `/doctor/cases` (~1K tokens)
3. `lib/care/api.ts` `listOpenCases` + view model (~400 tokens)
4. `components/dashboard/AppShell.tsx` + `AppShell.test.tsx` + `Sidebar.tsx`/`NavItemLink.tsx` - nav rendering, count pill pattern, tests (~800 tokens)
5. `lib/i18n/dictionaries.ts` `doctorConsole` + `caseWorkspace` blocks + parity test (~500 tokens)

## Do NOT read

- Intake module, prescription lifecycle, backend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- Known pre-existing (unrelated): frontend homepage parity fails on one Daltonganj string; backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - nav-config, cases index page, AppShell tests; parity
- `npm run typecheck`

## Handoff notes

- The history wording change is D-E (documented no-change): the empty state is correct behaviour, only the copy reads broken.
- The open-cases read already exists on the landing page - reuse it, don't add a new backend surface.
