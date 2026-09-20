# Brief - 456 Runtime activation-to-directory seam (approved doctors appear in search)

**Ticket:** #456 · **Parent:** #455 · **Refreshed:** 2026-09-17
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Operator approval of a partner's current round makes them directory-visible at runtime. Add a single "activate" transition on the credential-validity deep module (the symmetric counterpart of its `close_out_credentials` transition) that (a) stamps the current round's `partner_credentials` rows `verified = true` and (b) upserts/refreshes the `partner_directory_index` row (practice lat/lng, partner_type, `is_active = true`) consistent with the directory search projection; `operator_decision` (approve) calls it in the same transaction as the status flip, decision record, outbox write and cache flush. Result: an operator-approve makes the doctor appear in `GET /v1/directory/search` immediately.

Acceptance criteria:

- [ ] A single "activate" transition on the credential-validity deep module: stamps the current round's credentials verified and upserts/refreshes the partner's directory-index row in one call, leaving an existing index row refreshed (not duplicated) and never raising when the partner already appears.
- [ ] The operator-approve decision path calls this transition inside the same transaction as the status flip, decision record, outbox event and cache flush.
- [ ] Tests exercise the real seam: approving a doctor through the decision path makes them appear in directory search (unit + integration), and the approval is idempotent.

## Read-list (in order)

1. `OperatorGateFacade.operator_decision` (partner module, operator-gate facade) - the approve path to extend (only the `if approve:` block) (~2K).
2. Credential-validity deep module: `close_out_credentials` (the transition to mirror), `provider_visible`/`has_any_credential`/`has_invalid_credential` predicates (the truth the index must agree with), and its module imports/table refs (~3K).
3. `CredentialValidityPort` protocol (partner shared) - the seam must be represented here for the fakes (~0.5K).
4. `DirectoryFacade.search_directory` condition assembly + `get_provider_profile` credential read - the projection the upsert must be consistent with (~2K).
5. `partner_directory_index` and `partner_credentials` table shapes (partner schema models) - columns/SQL for the stamp and upsert (~1K).
6. `tests/unit/test_operator_gate_facade.py` - the test style/engine harness for the new approve assertions; `tests/integration/test_directory_search.py` fixture style for the real-seam integration case (~2K).

## Do NOT read

- `register_handlers` / worker-bus wiring (`partner/adapters/__init__.py`, bus registry) - this slice is synchronous in-transaction, no new consumer.
- Artifact store, mobile/i18n, credential-intake facade internals, unrelated modules.
- `docs/archive/`; any phase-6+ care/eprescription slices.

## Baseline verify

- `npm run test:unit:backend` (known pre-existing 3 failures in OTP/demo tests - see Handoff) and `npm run typecheck` (currently green) pass for everything touching the partner module.

## Done-verify

- New seam unit tests + `npm run typecheck` + `npm run test:unit:backend` green (minus the 3 recorded OTP config failures).
- `tests/integration/test_directory_search.py` (or a new integration case) activates a partner via the decision path and sees it in search.

## Handoff notes

- The uncommitted `apps/backend/app/config.py` change (`DEFAULT_APP_ENVIRONMENT` production->dev) is pre-existing local dev state and causes the 3 OTP/demo unit-test failures; do not revert or "fix" it as part of this ticket - record it.
- `operator_gate_facade.operator_decision` already flushes the directory cache on approve via `directory_cache.directory_visibility_changed()` (best-effort); keep that - the seam is the missing state write, not the cache flush.
- The v6_0 migration (`9f6c2e1b7d3a4`) backfill SQL is the authoritative "certified" shape for the index row + credential-validity conditions; #458 mirrors your transition's semantics.
