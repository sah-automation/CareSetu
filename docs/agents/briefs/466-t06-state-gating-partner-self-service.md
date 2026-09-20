# Brief - 466 F014-T06 Backend: state-based gating on partner self-service (MOD-002)

**Ticket:** #466 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Partner self-service respects lifecycle state at the API seam. As a partner:

- **Always reachable** (except when suspended): own status, rejection reason, appeal.
- **Credential submission**: reachable for `[Registered]` / `[Under Verification]` / `[Rejected]`, refused when the identity's partner role grant is suspended.
- **Consultation fee**: usable only after approval - refused unless the partner profile is `[Active]` (and only doctors may set it, as today).
- **Suspended**: the self-service routes refuse so the partner lands on a clear contact-support surface rather than half-working pages.

Approval still gates serving patients, never the session itself; this ticket gates the routes, matching the "reachable routes" language of the spec.

Acceptance criteria (verbatim from ticket):

- [ ] `POST /v1/partner/credentials` refuses a suspended partner (identity role grant suspended) with a clear envelope, and still works for `[Registered]` / `[Under Verification]` / `[Rejected]`.
- [ ] Consultation fee set/clear is refused unless the partner profile is `[Active]`; existing doctor-only rule unchanged.
- [ ] `GET /v1/partner/me`, `GET /v1/partner/me/verification`, `GET /v1/partner/rejection-reason` and `POST /v1/partner/appeal` stay reachable in every non-suspended state (existing `PARTNER_NOT_REJECTED` / `APPEAL_ALREADY_USED` rules unchanged).
- [ ] The suspension signal is read through the existing iam seam (identity status / role-grant status via the `partner_role_status` seam), never by crossing the module-isolation boundary.
- [ ] Route-seam tests cover each refusal and each reachable path above.

**Blocked by:** #464 (tighten partner session mint) - the session/suspension boundary the gating keys off lands there.

## Read-list (in order)

1. The partner auth router `apps/backend/modules/partner/adapters/routes.py` (prefix `/v1/partner`, `require_partner` gate) - `open_credential_submission`, `update_consultation_fee`, `rejection_reason`, `partner_me`, `partner_me_verification`, `partner_appeal` handlers and their error-envelope registration. (~2.5K)
2. The credential intake facade `apps/backend/modules/partner/credential_intake_facade.py` `submit_credentials` (+ `get_my_verification`, `get_rejection_reason`, `appeal`) - the current state rules to extend with the suspended refusal. (~1.8K)
3. `apps/backend/modules/partner/facade.py` `update_consultation_fee` (~L761-816) - current rule is doctor-type-only; the ticket ADDS the `[Active]`-only requirement (do not weaken the doctor-only rule). (~0.7K)
4. The iam suspension seam: `apps/backend/modules/iam/facade.py` `partner_role_status` (delegating to `session_facade._partner_role_status`) + `suspend_partner_role` + `resolve_partner` - the suspension signal, read from iam, never by importing the partner schema from iam or vice versa. The partner domain state machine `domain/state_machine.py` (`PartnerStatus` = `Registered|Under Verification|Active|Rejected`) for the profile states that stay reachable. (~1.3K)
5. Existing route-seam tests: `tests/unit/test_partner_credentials_route.py`, `tests/unit/test_consultation_fee_route.py`, `tests/unit/test_partner_status_route.py` + intake facade tests `test_credential_intake_facade.py` - the rows to extend. (~1.7K)

## Do NOT read

- Operator console internals (queue/detail/decision are operator-scoped, not this self-service surface), directory-search internals, frontend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (2184 passed on 2026-09-17), `npm run lint`, `npm run typecheck`, `npm run migration-check` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new/updated route tests: credential submit refuses when the iam role grant is suspended + works in registered/under-verification/rejected; consultation fee refuses unless `[Active]`; me/verification/rejection-reason/appeal reachable in every non-suspended state with existing rules intact.
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- CRITICAL drift flag: `PartnerStatus` has NO `Suspended` value. Suspension exists only on the iam side: `iam_identities.status = Suspended` and/or `iam_role_grants.status` flipped via `suspend_partner_role`. The gating keys off `partner_role_status` (the existing iam seam), so "suspended" in this ticket always means the iam-side signal.
- Today `update_consultation_fee` enforces doctor-type only - there is NO active-state check yet. This ticket adds it; keep the existing 403 for non-doctors intact.
- Credential submission currently has no suspension gate; add the refusal without disturbing the Step-1 prefilter, the re-submission round logic, or the `MAX_RE_SUBMISSIONS` throttle.
- Read the module-isolation rule: the partner route reaches iam only through the `partner_role_status`/`resolve_partner` facade seams; the lint gate enforces no cross-schema SQL/imports.
- The reachable paths must NOT regress the existing `PARTNER_NOT_REJECTED` (rejection-reason/appeal) or `APPEAL_ALREADY_USED` safeguards - the AC keeps those unchanged.
