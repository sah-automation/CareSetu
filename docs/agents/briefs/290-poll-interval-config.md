# Brief - 290 Extract poll interval to shared config constant

**Ticket:** #290 · **Parent:** phase5-frontend-review-fixes.md Fix 2 · **Refreshed:** 2026-09-03
**Reading surface:** ~3K tokens (budget 10K) - well within budget

## Scope

Replace the duplicated `POLL_INTERVAL_MS = 10_000` in both partner status screens with a single `NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS` env var read from a shared config module.

- [ ] Shared config constant reads from `NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS` env var (default 10000)
- [ ] Both pending and rejected status pages use the shared constant
- [ ] Tests: both screens read from the shared constant

## Read-list (in order)

1. `apps/frontend/src/app/(partner)/partner/status/pending/page.tsx` - Line 29: `const POLL_INTERVAL_MS = 10_000`. Used for polling partner status. (~170 lines, ~3K tokens)
2. `apps/frontend/src/app/(partner)/partner/status/rejected/page.tsx` - Line 31: `const POLL_INTERVAL_MS = 10_000`. Same pattern. (~140 lines, ~2.5K tokens)
3. Check if a shared `lib/config.ts` or `lib/poll.ts` already exists in `apps/frontend/src/lib/`.
4. `.env.example` - document `NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS`.
5. Test files: `pending/page.test.tsx`, `rejected/page.test.tsx`.

## Do NOT read

- operator modules, auth modules, i18n dictionaries, wizard, audit modules

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - both status page tests pass
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source
- `npm run lint` - clean

## Handoff notes

- This is the simplest ticket - purely mechanical extraction.
- If no shared config module exists, create `apps/frontend/src/lib/config.ts` (or similar) and export the poll interval constant. If one exists, add the constant there.
- The `NEXT_PUBLIC_` prefix is required for Next.js client-side env vars.
