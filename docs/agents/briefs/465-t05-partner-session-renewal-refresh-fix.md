# Brief - 465 F014-T05 Backend: partner session renewal in every pre-activation state (refresh fix)

**Ticket:** #465 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~6.5K tokens (budget 10K) - within budget

## Scope

A partner waiting for verification stops being ejected every ~15 minutes. `POST /v1/auth/refresh` is fixed so that a `partner`-scoped session renews in every pre-activation lifecycle state - `[Registered]`, `[Under Verification]`, `[Rejected]` - whenever a partner profile exists and the identity is not suspended. Only a suspended identity is refused. The active partner-role-grant requirement currently on the refresh path applies only to scopes that genuinely need it; the renewal keeps using the identity's current scope (never the old token) and the composition-boundary partner check so iam does not read the partner schema.

Acceptance criteria (verbatim from ticket):

- [ ] A `partner`-scope refresh token renews for a partner whose identity is not `Suspended`, with no active `partner` role grant required (a `[Registered]`/`[Under Verification]`/`[Rejected]` partner renews normally).
- [ ] The renewal re-confirms the partner profile still exists at the composition boundary (same callback pattern as the session mint), refusing with the refresh envelope if it does not.
- [ ] A suspended identity's partner-scope refresh is refused; other scopes keep their existing behaviour unchanged.
- [ ] Rotation semantics are unchanged: old refresh token revoked in the same transaction, replay detection intact, `patient.auth_failed` audit on a refused rotation preserved for scopes that already emit it (no event-name changes).
- [ ] Route-seam tests cover: partner renewal in registered / under-verification / rejected states, suspended refusal, and unchanged patient/operator refresh behaviour.

**Blocked by:** #464 (tighten partner session mint) - same router + session facade files; sequence to avoid conflicts.

## Read-list (in order)

1. `apps/backend/modules/iam/session_facade.py` `refresh_session` (~L380-486) - the scope re-derivation via `_resolve_active_role` (from current role grants, never the old token), the `FOR UPDATE` refresh-token row (`_session_for_refresh`), old-row revocation in the same transaction, replay detection mapping to a `patient.auth_failed` "replay" envelope, and the suspended-identity refusal. This is where the partner-scope renewal rule changes. (~3K)
2. The iam auth router `refresh` route in `apps/backend/modules/iam/adapters/routes.py` (~L338+) - the envelope/`run_idempotent` wiring the fix sits under, plus `_resolve_active_role` and `partner_role_status` (session_facade ~L685) which read the partner role grant status for the suspension signal. (~1.5K)
3. The composition seam `apps/backend/modules/partner/registration_facade.py` `resolve_partner_id_by_identity` / `verify_partner_exists` - the same callback pattern the mint uses, to re-confirm the partner profile still exists on renewal. (~0.5K)
4. Refresh test prior art: `tests/unit/test_iam_refresh_route.py`, `tests/unit/test_iam_refresh.py`, and the partner-mint/refresh cases in `tests/unit/test_iam_session.py` - rows to extend for the three pre-activation states + suspended refusal. (~1.5K)

## Do NOT read

- Operator MFA internals, patient OTP internals, frontend, `docs/archive/`, partner module internals beyond the two named seams.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (2184 passed on 2026-09-17), `npm run lint`, `npm run typecheck` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - refresh tests cover partner renewal in registered/under-verification/rejected, suspended refusal, profile-deleted refusal, and unchanged patient/operator refresh.
- `npm run lint`, `npm run typecheck` green.

## Handoff notes

- Current behaviour to fix: `refresh_session` requires an active `partner` role grant to re-derive the partner scope - that is what ejects a pre-activation partner. The renewal must instead allow the partner scope whenever the identity is not `Suspended` and a partner profile exists (i.e. the `resolve_partner_id_by_identity` seam answers), WITHOUT loosening patient/operator refresh.
- Rotation correctness is non-negotiable: keep revoke-old-in-same-transaction, replay detection, and the `patient.auth_failed` audit for scopes that already emit it. The change is to which partner states are allowed to renew, not to the refresh mechanics.
- iam never reads partner schema: the partner-profile re-check rides the same `verify_partner_exists` callback the mint uses, executed on iam's lock-held connection.
- No schema change, no new events (migration-check not affected, but run it anyway as part of the gate).
- Sequence hard after #464 in the same files; coordinate branches so the router/facade slices do not overlap when both tickets' tests run.
