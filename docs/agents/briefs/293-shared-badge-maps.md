# Brief - 293 Extract shared badge maps + status key normalizer

**Ticket:** #293 · **Parent:** phase5-frontend-review-fixes.md Fix 4 · **Refreshed:** 2026-09-03
**Reading surface:** ~5K tokens (budget 10K) - well within budget

## Scope

Extract the byte-identical `TYPE_BADGE`/`STATUS_BADGE` maps from the operator queue list and detail pages into a shared module. Add a `statusKey()` normalizer that maps backend status strings to stable lowercase keys, resolving the inconsistent casing.

- [ ] Shared module exports `STATUS_BADGE`, `TYPE_BADGE`, and `statusKey()`
- [ ] Both operator pages import from the shared module (no local duplicates)
- [ ] `statusKey()` normalizes all backend status values to stable lowercase keys
- [ ] Tests: `statusKey()` covers every backend status value, both screens' tests green

## Read-list (in order)

1. `apps/frontend/src/app/(operator)/operator/page.tsx` - Lines 41-51: `TYPE_BADGE` and `STATUS_BADGE` maps. Status keys: `"Under Verification"` (Title Case), `verified` (lowercase), `rejected` (lowercase). (~300 lines, ~5K tokens - read selectively, focus on badge maps and their usage)
2. `apps/frontend/src/app/(operator)/verification/[partner_id]/page.tsx` - Lines 36-52: identical `TYPE_BADGE`/`STATUS_BADGE` maps plus `CREDENTIAL_STATUS` map. (~250 lines, ~4K tokens - read selectively)
3. `apps/frontend/src/app/(operator)/operator/page.test.tsx` - existing test assertions on badge rendering.
4. `apps/frontend/src/app/(operator)/operator/verification/[partner_id]/page.test.tsx` - existing test assertions.

## Do NOT read

- partner modules, auth modules, i18n dictionaries
- Backend modules

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - both operator page tests pass
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source
- `npm run lint` - clean

## Handoff notes

- The `STATUS_BADGE` map has inconsistent casing: `"Under Verification"` is Title Case while `verified`/`rejected` are lowercase. The `statusKey()` normalizer should map all backend status strings to stable lowercase keys.
- The detail page also has a `CREDENTIAL_STATUS` map (lines 48-52) with `verified`/`pending`/`expired` - decide whether to include it in the shared module.
- The shared module could live at `apps/frontend/src/components/operator/badges.ts` or `apps/frontend/src/lib/partner/status.ts`.
