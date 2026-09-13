# Brief - 336 iam/partner composition seam (WI-3)

**Ticket:** #336 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Remove the iam-to-partner circular back-reference so the iam and partner modules can be constructed independently, and make the partner facade's iam dependency optional so the daily credential-expiry sweep no longer composes an iam facade it never uses.

Today the composition root glues the two modules together after construction: partner session issuance in the iam session sub-facade reaches back into the partner module through a pluggable resolver (`set_partner_resolver` + a closure in the composition root). This ticket has partner session issuance accept an already-verified partner status as an input from the calling route instead, so iam no longer reaches into partner and the post-construction setter is deleted. Access authority stays in the existing RBAC dependency on the same routes - the auth boundary is not weakened.

The partner facade's iam dependency becomes optional (it is only genuinely needed by the register path that creates the sync credential account). The daily credential-expiry sweep composes a partner facade without any iam facade, so it stops building an SMS adapter and reading an MFA secret it never uses. Any partner operation that genuinely requires iam fails loudly (a typed error) when it is absent.

Acceptance criteria (from ticket):

- Partner session issuance receives an already-verified partner status from the calling route instead of reaching back into the partner module; the iam-to-partner resolver and its post-construction setter are deleted.
- iam and partner modules can be constructed independently with no post-construction glue.
- The auth boundary still enforces partner status through the existing RBAC dependency on the same routes.
- The partner facade's iam dependency is optional; a partner operation that genuinely requires iam fails loudly (typed error) when iam is absent.
- The daily credential-expiry sweep composes without an iam facade (no SMS adapter, no MFA secret built); the sweep succeeds.
- Worker sweep composition succeeds with no iam facade, and a partner operation requiring iam fails loudly when absent (integration tests).
- Existing partner/iam integration and route suites pass unchanged.
- Full harness green: backend unit tests, integration tests, mypy strict typecheck, lint, migration single-head gate.

## Read-list (in order)

1. `apps/backend/modules/iam/session_facade.py` 109, 281 - `set_partner_resolver` + `issue_partner_session` (the back-reference seam to delete) (~1.0K tokens)
2. `apps/backend/app/main.py` 188, 206-210 - composition root: `PartnerFacade` construction, `_resolve_partner_by_identity` closure, `facade.set_partner_resolver(...)` (~1.0K tokens)
3. `apps/backend/worker/main.py` 116-132 - `_build_sweep_facade` composing full IamFacade (sms adapter + MFA secret) for the sweep (~0.8K tokens)
4. `apps/backend/modules/partner/facade.py` 911-985 - `register`: the iam-requiring path (create credential account) that must fail loudly without iam (~1.5K tokens)
5. The partner coordinator's constructor after #333/#332/#337 - iam becomes optional; the register sub-facade (#332) is its only iam consumer (~0.5K tokens)
6. The calling routes for partner session issuance - how an already-verified partner status flows in; the RBAC dependency that enforces it (~0.7K tokens)
7. Prior art: worker sweep integration test, session-issuance route tests, `tests/unit/test_worker.py` - pins for injection changes (~0.8K tokens)

## Do NOT read

- The close-out/eligibility internals (owned by the credential-validity module).
- OTP internals; credential-intake/operator-gate/directory read methods (separate sub-facade tickets).
- Frontend, archives.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (1258 passed)
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all prior + new composition tests pass)
- `npm run test:integration` (worker sweep no-iam + loud-failure tests)
- `npm run typecheck` (clean)
- `npm run lint`
- `npm run migration-check`

## Handoff notes

- Blocked by #332 (registration sub-facade) and #337 (directory sub-facade) - its registration path and sweep close-out live in those sub-facades. Both are blocked by #333, which is blocked by #331.
- The auth boundary must not weaken: RBAC on the partner session routes keeps enforcing partner status.
- "Fail loudly" = a typed error (e.g. `PartnerIamUnavailableError`), never a silent no-op or permissive fallback.
- After this ticket, `app/main.py` constructs iam and partner independently with zero post-construction glue; `worker/main.py` composes the sweep facade with no iam facade at all.
- Re-check `grep -R "set_partner_resolver"` for all call sites before deleting the setter.
