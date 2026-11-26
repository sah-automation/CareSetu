# Brief - 271 Phase-5 review fix: partner self-service status + credential view (P2/P3, US-6/US-7)

**Ticket:** #271 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A logged-in partner has no HTTP route to read their own onboarding status or see that their credentials are under review - the facade supports it (`resolve_partner`, `get_verification_detail`) but both are only reachable via operator-scoped routes. This is the review gap P2 (US-6 "partner sees onboarding status") and P3 (US-7 "partner sees credentials being reviewed").

Add partner-scoped read routes so a partner can check where they stand, per the spec's pre-activation restricted scope (view status, submit/re-submit, view rejection reason - no patient-facing access).

Acceptance criteria (from #271):

- [ ] `GET /v1/partner/me` route exists, returns `{ status, partner_type, round, created_at }` for the authenticated partner.
- [ ] `GET /v1/partner/me/verification` route exists, returns credential review status for the partner's current verification round.
- [ ] Both routes are gated by `require_partner` (not operator).
- [ ] Partners in [Registered], [Under Verification], [Active], [Rejected] all get meaningful responses.
- [ ] Unit tests for both routes covering all four statuses.
- [ ] Existing tests pass (`node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck`).

## Read-list (in order)

1. `apps/backend/modules/partner/adapters/routes.py` - existing route definitions and the request/auth dependency pattern each uses: `require_partner` vs `require_operator`, and the existing partner GET/`me`-style handlers (e.g. `rejection_reason` 218-223) to mirror for shape. (~1.5K)
2. `apps/backend/modules/partner/facade.py` - `resolve_partner` (773) which returns the partner's status/lifecycle, and `get_verification_detail` (1296) which reads profile + credentials + history. Decide which to expose partner-scoped and which view model fits US-6/US-7. (~1.5K)
3. `apps/backend/modules/partner/domain/events.py` / `bus/events.py` - the `PartnerStatus` / lifecycle values ([Registered]/[Under Verification]/[Active]/[Rejected]) and the round model, so the response uses the canonical types. (~0.8K)
4. `apps/backend/app/gateway/rbac.py` - the `require_partner` RBAC seam (do NOT change it; just reuse) and how the authenticated caller's identity/partner is resolved. (~0.6K)
5. `docs/spec/phase-5-partner-onboarding.md` - US-6, US-7 and the pre-activation restricted scope paragraph ("[Registered]/[Under Verification] -> view status, submit/re-submit credentials, view rejection reason"). (~1.0K)

## Do NOT read

- IAM/notify/audit internals, `docs/archive/`, frontend.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- New partner status/verification route tests green (all four statuses)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- The facade already has the reads; this ticket is a thin adapter + route layer plus partner-scoped authorization. Do NOT rebuild reading logic. Use the existing `resolve_partner` / `get_verification_detail` (or a partner-scoped wrapper) rather than duplicating queries.
- Both routes must be gated by `require_partner` (partner scope), NOT `require_operator`. Only a partner may see their own record - re-check scope in the facade following the repo's "edge is convenience, facade is the boundary" rule (api-standards §6).
- The spec's restricted scope means a partner must NOT see other partners' data or patient-facing data from these routes - keep the circle tight.
- Follow the repo's `_FakeResult` / `_FakeScalar` mock idiom in unit tests. Response schemas should be Pydantic v2 models per api-standards §3.
- Parent for all Phase-5 review-fix briefs is #243. Findings drawn from the code-review P2/P3.
