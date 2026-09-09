# Brief - 292 Pending screen - show current verification round state

**Ticket:** #292 · **Parent:** phase5-frontend-review-fixes.md Fix 7 · **Refreshed:** 2026-09-03
**Reading surface:** ~5K tokens (budget 10K) - well within budget

## Scope

Fix the partner pending status page to show the current verification round's status instead of a stale `decision_reason` from a prior round in the "Verifying scope" row.

- [ ] Pending page reads the correct current-round field (not `decision_reason`)
- [ ] If no distinct current-round scope field exists on the backend, the row is dropped rather than showing a stale prior-round reason
- [ ] Tests: pending screen shows current round status, not prior `decision_reason`

## Read-list (in order)

1. `apps/frontend/src/app/(partner)/partner/status/pending/page.tsx` - Line 162: `verification?.decision_reason` rendered in the "Verifying" row. Need to find the correct field for current-round status. (~170 lines, ~3K tokens)
2. `apps/frontend/src/lib/partner/api.ts` - `PartnerVerificationStatusView` type and `isPartnerVerificationStatus` guard. What fields does the backend expose for the current verification round? (~271 lines - read selectively, focus on the verification type definition)
3. `apps/frontend/src/app/(partner)/partner/status/pending/page.test.tsx` - existing test assertions on `decision_reason`. (~200 lines, ~3K tokens)

## Do NOT read

- `apps/frontend/src/app/(partner)/partner/status/rejected/page.tsx`
- operator modules, auth modules, i18n dictionaries
- Backend modules beyond the type definition

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend` (ignore `.next/dev/types/` errors)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` - pending page tests pass with correct field
- `npm run typecheck -w @caresetu/frontend` - no new type errors in source
- `npm run lint` - clean

## Handoff notes

- `decision_reason` carries the rejection reason from a prior verification round - it is semantically wrong for a fresh "Under Verification" application.
- Check `PartnerVerificationStatusView` in `partner/api.ts` for what fields the backend exposes. The correct field might be `verification.status` (current round status) or a dedicated current-verification-scope field.
- If no appropriate field exists, drop the row entirely rather than showing stale data.
