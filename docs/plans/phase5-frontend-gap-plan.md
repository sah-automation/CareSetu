# Phase 5 - Frontend Gap & Implementation Plan (FEAT-014/FEAT-015)

**Status:** ready for `/to-tickets`
**Source:** manual UI check on branch `feat/phase-4-audit` (Phase 5 backend complete + migrated to Supabase; frontend still at PHASE-2.6/3 skeletons).
**Upstream targets:** roadmap `PHASE-5-PARTNER-ONBOARDING` (§2.5), blueprint `docs/design/ui-blueprint.md` §4.2/§4.3, PRD `FEAT-014`/`FEAT-015`, `docs/architecture/internal-modules.md` MOD-002 + MOD-001 (role grants/MFA) + MOD-011 (audit).

## 1. Goal

The Phase 5 **backend** is complete (open partner registration, credential Step-1 pre-filter, operator two-step verification queue, operator MFA login, role grant/deny on activation, audit of every operator decision) and is migrated + seeded on the live Supabase database. The Phase 5 **frontend** was never built - the four surfaces users hit are PHASE-2.6/3 skeletons that intentionally no-op ("arrives in Phase 5"). This plan closes that gap so the partner onboarding loop can actually be driven from the browser.

Deliverable end-to-end loop: partner registers openly → submits credentials (browser artifact upload) → lands on status screen → operator logs in with MFA → reviews queue → approves/rejects → the partner sees `[Active]`/`[Rejected]` + reviews their own verification status. Plus the Phase 4 patient access-history surface and a non-empty doctor landing.

## 2. What is already built (backend - do NOT rebuild)

| Backend surface               | Endpoints (all exist, migrated)                                                                                                                                      |
| :---------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Open partner registration     | `POST /v1/partner/register` (open, resolves phone, creates credential account per ADR-0010), `POST /v1/partner/credentials` (Step-1 artifact submission, idempotent) |
| Partner self-service status   | `GET /v1/partner/me`, `GET /v1/partner/me/verification`, `GET /v1/partner/rejection-reason`, `POST /v1/partner/appeal`                                               |
| Operator login + MFA          | `POST /v1/auth/operator/login` (phone + TOTP), `POST /v1/auth/operator/mfa/enroll`                                                                                   |
| Operator verification console | `GET /v1/partner/verification-queue`, `GET /v1/partner/verification/{id}`, `POST /v1/partner/verification/{id}/decision`                                             |
| Partner role grant/deny       | via `partner.activated`/`partner.rejected` events consumed by MOD-001                                                                                                |
| Patient access history        | `GET /v1/audit/access-history` (patient-only, own record)                                                                                                            |
| Patient record timeline       | `GET /v1/records` (already wired in frontend)                                                                                                                        |

Seeded `scripts/seed_demo.py` (idempotent) ensures: demo patient `+919000000001`, bootstrap operator `+919000000002` (MFA-enrolled TOTP). Run it on a migrated DB before manual verification.

## 3. Current frontend state (the gap)

Frontend files below are PHASE-2.6/3 skeletons; none call the Phase 5 backend. There is **no** partner/operator/staff API client in `apps/frontend/src/lib`. Canonical session/error plumbing exists and must be reused (`lib/api-base.ts` `authedFetch`, `lib/auth/api.ts`, `lib/api-errors.ts`, `lib/auth/staff-routing.ts` post-login matrix, dual-cookie session via ADR-0005/0007).

| Page                            | File                                                                                   | Current behaviour                                                                          | Needed                                                                                                                                                       |
| :------------------------------ | :------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Staff login                     | `src/app/staff/login/page.tsx` + `components/auth/staff/StaffLoginForm.tsx`            | Submits only a local `phase5Notice` (StaffLoginForm.tsx:92-95)                             | Real split-auth: operator MFA login (`POST /v1/auth/operator/login`); keep email+password form fields for partner staff login path per blueprint §4.2        |
| Staff register (partner wizard) | `src/app/staff/register/page.tsx` + `components/auth/staff/ProviderRegisterWizard.tsx` | Final submit sets `phase5Notice` only (ProviderRegisterWizard.tsx:807); uploads stay local | Wire to `POST /v1/partner/register` + `POST /v1/partner/credentials`; submit artifacts (base64), supply mandatory practice geo + type; handle error envelope |
| Partner status screens          | `src/app/(partner)/partner/status/pending/page.tsx`, `.../rejected/page.tsx`           | Skeleton placeholders                                                                      | Read real status via `GET /v1/partner/me` + `/me/verification`; rejected shows reason + appeal path                                                          |
| Operator console                | `src/app/(operator)/operator/page.tsx`                                                 | 5-line header only                                                                         | Queue list (`GET /v1/partner/verification-queue`), detail (`.../{id}`), decision (`.../decision`); operator-only guard                                       |
| Doctor dashboard                | `src/app/(doctor)/doctor/page.tsx`                                                     | `Welcome, Doctor` header only                                                              | Phase-5 landing content for an activated doctor partner (no directory feature yet - Phase 6)                                                                 |
| Patient record - access history | `src/app/(patient)/patient/record/page.tsx`                                            | Stale Phase 3 `Soon` placeholder (`placeholder-access`, record/page.tsx:244-255)           | Render `GET /v1/audit/access-history` in place of the placeholder                                                                                            |

## 4. Scope boundary (what this plan covers)

Frontend only (no backend schema/API changes expected; backend is complete). Build, in some order:

1. **Frontend staff/partner API client(s)** reusing `authedFetch`/error-envelope - a foundation ticket that every surface depends on.
2. **Partner registration wizard submission** - wire the existing 4-step wizard to register + credentials; handle success → post-login routing to status screen; keep local validation as-is.
3. **Operator MFA login** - wire the existing login form to `POST /v1/auth/operator/login`; surface `SESSION_MFA_REQUIRED` (401) as the MFA step; land via the staff post-login matrix.
4. **Partner status self-service** - pending/rejected screens read real state; rejected shows specific reason + appeal; pending shows verification round state.
5. **Operator verification console** - queue list, item detail (profile + credentials + verification history), approve/reject with reason-required-on-reject; refresh to reflect the decision.
6. **Doctor landing** - Phase-5 appropriate landing markup for an activated doctor partner (placeholder content is acceptable; directory search is Phase 6).
7. **Patient access-history view** - replace the placeholder on `/patient/record` with the real `GET /v1/audit/access-history` render.

### Out of scope (deferred)

- Directory search / provider profiles (Phase 6).
- Credential expiry/revocation UI (Phase 6).
- Any backend changes - this is a wiring/build frontend effort. If a required backend endpoint is found missing, stop and raise it as a backend ticket instead of inventing one.

## 5. Conventions / constraints to respect

- **Session transport:** dual-cookie model (`caresetu_authed` presence hint + httpOnly `caresetu_session`) - see ADR-0007 before any auth/cookie/route-guard work. Localhost is same-origin and masks split-origin rules.
- **Route guards:** `/partner/*` and `/operator/*` live behind role-scoped proxy matchers (`src/proxy.ts`); operator console must be operator-only, partner status patient-or-partner self-only.
- **Post-login routing:** reuse `postLoginTarget` in `lib/auth/staff-routing.ts`; partner verification state (`pending`/`rejected`) already overrides staff landing §4.4.
- **Error handling:** render the shared error envelope + short trace id (ui-blueprint §9.5); reuse `lib/api-errors.ts`; never show raw phone/PII (IAM masks phones server-side - keep client display masked too).
- **Scope rule:** confine changes to frontend + this plan. Do not touch prototype/ (disposable) or backend.

## 6. Acceptance criteria (overall loop)

- [ ] A doctor/lab/chemist can complete the 4-step wizard; on submit the application is created in the `partner` schema (register → credentials) and the user lands on the pending status screen.
- [ ] A Step-1 auto-reject (bad/missing artifact format) routes to the rejected screen with the specific reason; a valid submission queues for Step 2.
- [ ] The bootstrap operator logs in via phone + TOTP MFA (`POST /v1/auth/operator/login`), reaches `/operator`, and the review queue lists `[Under Verification]` submissions (sortable by registration age).
- [ ] Operator opens an item (sees profile + credentials + verification history), approves → partner becomes `[Active]` (role granted) or rejects → `[Rejected]` with required reason.
- [ ] The partner's status screen reflects the operator decision reliably (poll/refresh after decision).
- [ ] A patient visiting `/patient/record` sees their real record timeline and the access-history view from `GET /v1/audit/access-history` (no longer the Phase 4 placeholder).
- [ ] An activated doctor partner lands on a non-empty `/doctor` page.
- [ ] Existing frontend tests green (`npm run test -w @caresetu/frontend`, `npm run typecheck -w @caresetu/frontend`, `npm run lint`), migration-check and CI-relevant frontend gates green.

## 7. Suggested vertical-slice sequence (for `/to-tickets`)

Foundation first, then consumable surfaces. Each slice is a traceable, demoable behavior:

1. **Frontend staff/partner API client + error plumbing** (blocker for most) - typed clients for partner + operator + access-history endpoints reusing `authedFetch`.
2. **Partner registration submission** (blocked by 1) - wire wizard submit → register + credentials → pending routing.
3. **Partner self-service status** (blocked by 1) - pending/rejected screens from real `/me` + `/me/verification` + `/rejection-reason` + appeal.
4. **Operator MFA login** (blocked by 1) - wire login form → `operator/login` + MFA step + staff routing.
5. **Operator verification console** (blocked by 4) - queue list → detail → decision → reflected state.
6. **Doctor landing** (blocked by 4, or standalone) - non-empty activated-doctor page.
7. **Patient access-history view** (blocked by 1) - replace placeholder with real render.

Consider whether slices 6/7 can start after the client slice even if the full auth loop is unfinished. The operator console (5) is the largest; split queue-list from decision if it exceeds the SIZING-GATE.

## 8. Manual verification (post-implementation)

Backend must be running on :8000 and frontend on :3000 with `.env` loaded (including `IAM_MFA_SECRET_KEY`). Seed via `scripts/seed_demo.py`. Walk: partner register → status → operator login (MFA via recorded TOTP secret) → queue → decision → partner status update; patient record + access history; doctor landing. See `docs/plans/` sibling plan `phase2-iam-auth-plan.md` for the prior phase's doc style; this file follows the same `phase<N>-<area>-plan.md` convention.
