# Brief - 342 Review fix: restore atomic partner-profile check in session issuance (F4)

**Ticket:** #342 · **Parent:** #339 · **Refreshed:** 2026-09-07
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

`issue_partner_session` verifies partner-profile existence only at the route level (early-rejection optimization), then trusts the passed `partner_id` when minting the JWT. If the profile is deleted between the route pre-check and the mint, a partner-scoped token is minted for a now-patient-only phone. Restore atomicity: re-verify profile existence under the identity row lock, in the same transaction as the mint, via an injected verification callback (so iam never imports the partner module - cross-schema isolation).

Acceptance criteria (from #342):

- [ ] `issue_partner_session` re-verifies partner-profile existence under the identity row lock, before minting the JWT, in the same transaction.
- [ ] If the profile no longer exists (or `partner_id < 1`) at mint time, a `SessionIssuanceError` is raised.
- [ ] The route-level pre-check remains as the fast-path early rejection.
- [ ] Unit test exercises the concurrent profile-deletion scenario.
- [ ] Route-level test verifies the 409/error response in the race scenario.
- [ ] `npm run test:unit:backend`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `apps/backend/modules/iam/session_facade.py` - `issue_partner_session` (298-344): the `engine.begin()` transaction (324), `_lock_identity_by_phone` (325), `_mint_session_row` (333). Add the verification before line 333. (~4K)
2. `apps/backend/modules/iam/adapters/routes.py` - `issue_partner_session` route (256-310), `_issue_verified_partner_session` closure (289-296), pre-check via `resolve_partner_id_by_identity` (291). Wire the verification callback here. (~2K)
3. `apps/backend/modules/partner/registration_facade.py` - `resolve_partner_id_by_identity` (202) - the non-throwing resolve-for-session seam the callback should mirror, but executing within the iam transaction. Verify whether a helper exists to run this check against an open connection without importing partner from iam. (~1.5K)
4. `tests/unit/test_iam_session.py` - mock pattern (NullPool engine, unreachable host); add the concurrent-deletion unit test.
5. `tests/unit/test_iam_session_route.py` - stub-facade pattern swapped into `app.state` (296-427); add the race route test.

## Do NOT read

- OTP/MFA/JWT/refresh internals, event bus, outbox, partner domain/schema layer, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (new race tests green)
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Cross-schema constraint: iam must NOT import the partner module. Implement the existence re-check as an optional injected callback on `SessionFacade.issue_partner_session`, typed to accept the open `AsyncConnection` and `partner_id`, raising `SessionIssuanceError` when the profile is gone. The route supplies the callable, backed by the partner facade's resolution logic re-run against the caller's connection.
- Keep the route-level pre-check unchanged - it is the fast path for the common case; the in-transaction re-check is the atomic safety net.
- Follow the existing mocking patterns: `test_iam_session.py` uses real facades with a NullPool unreachable engine; `test_iam_session_route.py` stubs facades into `app.state`.
- Parent for all review-fix briefs is #339. Concept drawn from review finding F4.
