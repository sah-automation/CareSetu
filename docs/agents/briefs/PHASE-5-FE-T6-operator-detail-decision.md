# Brief -- T6 Operator verification detail + decision

**Ticket:** #285 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~3K tokens (budget 10K) -- within budget

## Scope

Operator verification detail page at `/operator/verification/[id]`: shows partner profile + credential artifacts + verification history from `GET /v1/partner/verification/{id}`. Approve button calls `POST /v1/partner/verification/{id}/decision` with `{ "approve": true }`. Reject button opens a reason-required form, then calls decision with `{ "approve": false, "reason": "..." }`. After decision: navigate back to queue, which reflects the updated state.

## Read-list (in order)

1. `apps/frontend/src/lib/operator/api.ts` -- T1 output: `fetchVerificationDetail(partnerId)` and `submitDecision(partnerId, body)` functions
2. `apps/frontend/src/app/(operator)/operator/page.tsx` -- T5 output for link target (how the queue links to detail)
3. `apps/frontend/src/app/(patient)/patient/record/page.tsx` -- loading/error pattern reference
4. `apps/frontend/src/lib/api-errors.ts` -- `ApiError`, `parseErrorEnvelope`, `extractTraceId`
5. `apps/frontend/src/app/(operator)/layout.tsx` -- AppShell wrapper (confirm route exists under operator group)

## Do NOT read

- partner status pages, registration wizard, backend decision handler code, docs/archive/, prototype/.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- **T5 dependency**: queue list must exist to link into detail view; operator session from T4.
- Backend response shape: `PartnerVerificationDetail: { partner_id, identity_id, partner_type, status, practice_name, practice_address, service_area_id, created_at, credentials: CredentialDetail[], verification_history: VerificationRound[], audit_events: AuditEventDetail[], audit_link? }`.
- `CredentialDetail: { credential_id, credential_type, verified, expires_at, artifact_refs: { [key]: string } }`
- `VerificationRound: { round, status, decision, decision_reason, decision_by, decided_at, created_at }`
- `AuditEventDetail: { id (UUID), event_type, actor_id (UUID), target_id (UUID), scope, metadata, timestamp, prev_hash, hash }`
- Decision request body: `{ approve: boolean, reason?: string }`. Reason is REQUIRED on reject (422 when missing).
- Create a new page at `apps/frontend/src/app/(operator)/verification/[partner_id]/page.tsx`. This is a new file (no existing skeleton).
- Use Next.js dynamic route: `[partner_id]` segment, read with `useParams()`.
- Show: partner profile header (type badge, name, address), credential list (type, verified status, expiry), verification history table (round, status, decision, reason, date), audit events timeline.
- Approve: simple button with confirmation. Reject: modal/sheet with reason textarea, submit button disabled until reason is non-empty.
- After decision: `router.push("/operator")` to go back to queue.
- The `audit_events` list shows the partner's full audit chain. Display it as a timeline with event type, actor, timestamp, and hash links.
