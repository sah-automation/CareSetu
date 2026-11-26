# Brief - T15 Frontend: intake API client + mode chooser page

**Ticket:** #359 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Patient-facing intake opens: a typed API client in lib covering submit, upload, re-record, get pre-summary, and save edits, and the intake-start page where a patient picks how to describe their symptoms - two oversized mode buttons, voice default-highlighted (recommended, not forced) and text equal-first-class, in both English and Hindi per the ratified Phase 7 prototype, wired into the patient shell.

Acceptance criteria:

- [ ] The lib client covers the intake routes with the standard authedFetch/request conventions and typed responses
- [ ] intake-start renders the two oversized mode buttons with voice default-highlighted and routes to voice/text
- [ ] Bilingual copy for every visible string passes the i18n parity test
- [ ] The page lives in the patient shell with the Start nav active (per prototype)

## Read-list (in order)

1. `prototype/phase-7-8/intake-start.html` + `prototype/phase-7-8/BUILD-PLAN.md` Part 1 - the ratified interaction and copy (~2K)
2. `apps/frontend/src/lib/api-base.ts` + `request.ts` + `record/api.ts` - client + authedFetch/request conventions (~2K)
3. `apps/frontend/src/lib/i18n/dictionaries.ts` + `dictionaries.test.ts` - bilingual strings and the parity gate (~2K)
4. An existing patient page `apps/frontend/src/app/(patient)/patient/page.tsx` - shell + router conventions, nav config (~1.5K)
5. The route shapes from T12 - the client endpoints/types mirror these verbatim (~1K)

## Do NOT read

- `docs/archive`
- backend internals beyond the route contract
- non-patient surface prototypes

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 687 pass with 1 known unrelated flake: `(operator)/operator/verification/[partner_id] > renders partner profile on load` times out intermittently (verified 2026-09-08); re-run if only that test fails
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run check:pages`

## Handoff notes

- The i18n parity test (`dictionaries.test.ts`) is the hard gate for "bilingual copy passes the i18n parity test" - every visible string needs a Hi key.
- Voice is default-highlighted but never forced; text is equal-first-class per the prototype.
- The patient dashboard page is `app/(patient)/patient/page.tsx` (`dashboard.tsx` does not exist).
