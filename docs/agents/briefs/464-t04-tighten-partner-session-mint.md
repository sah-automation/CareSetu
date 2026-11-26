# Brief - 464 F014-T04 Backend: tighten partner session mint to require phone-verified identity

**Ticket:** #464 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The loophole is closed: no partner session can be minted without a successful phone-code verification, so knowing a partner's number is no longer enough to become them. `POST /v1/auth/partner/session` keeps its partner-profile-existence gate (including the atomic under-lock re-check) and **additionally refuses** a phone whose identity is not phone-verified. The partner who verified in ticket 03 gets their partner-scoped session; a brand-new registrant who skipped the OTP step is refused until they verify.

Acceptance criteria (verbatim from ticket):

- [ ] `POST /v1/auth/partner/session` refuses a phone whose identity is not phone-verified (the marker from ticket 03) with the same 409 `SESSION_REFUSED` envelope as the other refusals.
- [ ] Unknown phone / no partner profile / profile deleted before mint still refuse exactly as today (existing tests keep passing or are updated only where the acceptance criteria changed the gate).
- [ ] A phone-verified partner (existing identity already phone-verified, e.g. verified as a patient, or partner-verified) mints the `partner`-scoped session with cookie transport unchanged (ADR-0007 invariants hold).
- [ ] Route-seam tests cover: verified mints, unverified phone refused, patient-only phone refused, unknown phone refused.
- [ ] No new event name is introduced.

**Blocked by:** #463 (partner OTP verify + phone-verified schema) - the gate reads the marker 03 creates.

## Read-list (in order)

1. The iam auth router partner-session route in `apps/backend/modules/iam/adapters/routes.py` (`issue_partner_session` handler, ~L263+) - the existing gate (phone -> identity -> partner profile via the composition seam) that gains the phone-verified check; `run_idempotent` + `SESSION_REFUSED` 409 envelope pattern. (~1.5K)
2. `apps/backend/modules/iam/session_facade.py` `issue_partner_session` (~L301-363) + `_lock_identity_by_id` + `_mint_session_row` - the mint path: why the partner-existence gate runs as a callback (`verify_partner_exists`) under iam's row lock, and where the phone-verified check slots in without breaking the atomic re-check. (~2K)
3. The iam facade delegator `apps/backend/modules/iam/facade.py` `issue_partner_session` and the seams it calls: `resolve_identity_id_by_phone`, and `apps/backend/modules/partner/registration_facade.py` `resolve_partner_id_by_identity` (non-throwing) / `verify_partner_exists(connection, partner_id)` (runs on the caller's open connection) - the composition boundary the route already uses. (~1K)
4. The iam schema model (`iam_identities` phone-verified column from #463) and its test coverage. (~0.3K)
5. Existing test rows to extend (not rewrite): `tests/unit/test_iam_session_route.py` partner-session cases + `tests/unit/test_iam_session.py` partner-mint tests + previous partner-session 409-refusal coverage. (~2K)

## Do NOT read

- Patient OTP internals, operator MFA, frontend, `docs/archive/`, partner module internals beyond the two named seams.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (2184 passed on 2026-09-17), `npm run lint`, `npm run typecheck`, `npm run migration-check` - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - updated partner-session route tests: verified mints, unverified-refused (409 `SESSION_REFUSED`), patient-only-refused, unknown-refused.
- `npm run lint`, `npm run typecheck`, `npm run migration-check` green.

## Handoff notes

- The unverified refusal reuses the SAME 409 `SESSION_REFUSED` envelope the current refusals use - do not add a new error code.
- Keep the atomic under-lock pattern: the gate re-checks partner existence and phone-verified status on the lock-held path (`verify_partner_exists` callback), so a profile deleted between resolve and mint still refuses.
- "Phone-verified via the patient path counts" is intentional: an identity verified as a patient is phone-verified for partner mint too (the marker is on `iam_identities`, shared). A partner who never verified any role is refused.
- No event-name change; no transport change (ADR-0007 invariants are untouched - the JWT/cookie shape and frontend save path stay identical).
- #465 (renewal) and #466 (state gating) both sequence after this ticket in the same router/facade files - land clean, merge, then sequence.
