# Brief - 274 Phase-5 review fix: consolidate duplicated gateway helpers (S2/S3)

**Ticket:** #274 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

`_run_idempotent` is copy-pasted verbatim into `modules/partner/adapters/routes.py` (66-92) and `modules/iam/adapters/routes.py` (157-183); a module-local `_error_response` is duplicated across the iam, partner, consent, and health route modules. Meanwhile `app/gateway/errors.py` already provides a shared `error_response`, and `app/gateway/idempotency.py` provides the shared `IdempotencyStore`. This is the review gap S2/S3 - the diff itself consolidated delivery boilerplate into `bus/handler_harness.py` and should extend the same discipline to these gateway concerns.

Deduplicate the two helpers behind shared gateway primitives and point the module routes at them.

Acceptance criteria (from #274):

- [ ] `_run_idempotent` extracted to a shared location (e.g. a helper next to `app/gateway/idempotency.py`), reusing the existing `IdempotencyStore`.
- [ ] `_error_response` consolidated onto the existing `app/gateway/errors.py` `error_response` (reconciling the module-local `details` variant if needed).
- [ ] `modules/partner/adapters/routes.py` imports from the shared location, no local copy.
- [ ] `modules/iam/adapters/routes.py` imports from the shared location, no local copy.
- [ ] Other modules using `_error_response` (consent, health) updated if feasible without scope creep.
- [ ] No behavioral change - all existing tests pass.
- [ ] `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck` pass.

## Read-list (in order)

1. `apps/backend/app/gateway/idempotency.py` - the shared `IdempotencyStore` (get/put, key TTL, injectable clock). The extracted `_run_idempotent` must reuse this, not build a new store. (~1.0K)
2. `apps/backend/app/gateway/errors.py` - the existing shared `error_response` (66) and `ErrorEnvelope`. Understand its signature (status_code, code, message, request, headers) vs the module-local `_error_response` (has a `details` param the gateway one lacks). (~1.2K)
3. `apps/backend/modules/partner/adapters/routes.py` - `_run_idempotent` (66-92) and `_error_response` usage; how the idempotency store is accessed via `request.app.state.idempotency_store`. (~0.8K)
4. `apps/backend/modules/iam/adapters/routes.py` - `_run_idempotent` (157-183) and `_error_response` (383-405) for comparison / dedupe. (~0.8K)
5. `apps/backend/bus/handler_harness.py` - the consolidation precedent (shared harness the diff already adopted) to mirror the "where shared helpers live" decision. (~0.6K)
6. `docs/standards/api-standards.md` §5 (idempotency) and §2 (error envelope) - the contract both helpers serve. (~0.8K)

## Do NOT read

- module domain/facade internals, `docs/archive/`, frontend.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- Idempotency + relevant route tests green (grep `idempot` tests)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- The module-local `_error_response` carries a `details` param that the gateway `error_response` does not. Decide deliberately: extend the gateway one to accept optional `details` (single source of truth) rather than keeping two shapes. Do NOT break the `_emit_access_denial` boundary in `errors.py`.
- Keep the extracted `_run_idempotent` reusing `request.app.state.idempotency_store` (the same `IdempotencyStore` instance) and the same key derivation (`f"{request.url.path}:{key}"`) so behaviour is unchanged - this is a pure dedup, not a behaviour change.
- This ticket is blocked by #272 (MFA enrollment) to avoid route-merge conflicts in `iam/adapters/routes.py`. Do not start until #272 has landed.
- Parent for all Phase-5 review-fix briefs is #243. Findings drawn from the code-review S2/S3.
