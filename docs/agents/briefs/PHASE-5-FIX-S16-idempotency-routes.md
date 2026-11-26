# Brief - 269 Phase-5 fix: idempotency for new partner mutations (S16)

**Ticket:** #269 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The review finding S16: the new Phase-5 partner mutations (registration, credential submission, appeal, verification decision) are not idempotent per the api-standards, while an idempotency store already exists at the gateway. Route the partner mutations through the existing idempotency mechanism so a retried request with the same key doesn't double-apply.

Acceptance criteria (from #269):

- [ ] The partner mutations (`open_partner_registration`, credential submission, appeal, operator decision) are idempotent per the repo's api-standards (idempotency key honored; duplicate key returns the stored result).
- [ ] Reuses the existing gateway idempotency store (`app/gateway/idempotency.py`), NOT a new per-module store.
- [ ] Existing idempotency tests + partner mutation tests pass; a retry with the same key is observed to not re-run the mutation.

## Read-list (in order)

1. `apps/backend/app/gateway/idempotency.py` - the existing mechanism: how the key is derived (path + key), the store table/schema, and how a duplicate key is resolved (returns prior result). This is the wiring point the S16 finding says is underused (~1.2K).
2. `apps/backend/app/main.py` - how the idempotency middleware/error-handling attaches at the gateway so the partner routes inherit it (or the route-level seam where it's applied today; check whether `register` already uses it) (~0.8K).
3. `apps/backend/modules/partner/adapters/routes.py` - the four mutation routes: `open_partner_registration` (109-135), `open_credential_submission` (138-173), `partner_appeal` (199-218), `operator_decision` (276-302). Read the request-model + dependency pattern each uses (~1.2K).
4. `docs/standards/api-standards.md` - the idempotency section (which requests must carry an idempotency key, error envelope for a conflicting key) (~0.6K).
5. `tests/unit/` + `tests/integration/` - existing idempotency + partner mutation tests (grep `idempot` and `open_partner_registration`) to extend (~1.2K).

## Do NOT read

- notify/audit internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Idempotency + partner mutation tests green (grep `idempot` tests and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The idempotency store is dashboard-only today (gateway, keyed by path+key). The finding is that the new partner mutations DID NOT route through it. This ticket wires them to the existing store - do NOT build a second idempotency mechanism.
- Follow the api-standards: which of the four routes are naturally idempotent (registration/appeal/decision) vs. naturally one-shot (refresh/submission). The standard dictates the "same key -> stored result; different key on same path -> 409 conflict" behavior - mirror the repo's existing idempotency error envelope.
- `register` currently does `on_conflict_do_nothing` for duplicate phones (facade 521) - that is NOT idempotency; keep it but add the key-based path.
- The integration suite may have idempotency round-trip tests (grep `tests/integration` for `idempot`). If so, run those too after this lands.
- Keep the public route signatures compatible - idempotency-key is typically an HTTP header, not a path param; confirm the gateway's existing key source.
