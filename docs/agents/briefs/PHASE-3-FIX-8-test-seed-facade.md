# Brief - FIX-8 Refactor test-seed endpoints to use facade layer

**Ticket:** #228 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Test-seed endpoints (`/v1/test/seed` and `/v1/test/seed-egress`) call through facades instead of importing raw schema models. Module isolation maintained even in dev-only endpoints.

**Acceptance criteria:**

- `/v1/test/seed` endpoint uses `HealthFacade` methods instead of raw schema imports
- `/v1/test/seed-egress` endpoint uses `ConsentFacade` methods instead of raw schema imports
- No direct imports of `modules.health.schema.models` or `modules.consent.schema.models` in `app/main.py` (except for the error envelope)
- `npm run test:unit:backend` passes
- `npm run typecheck` passes

## Read-list (in order)

1. `apps/backend/app/main.py:280-444` - test-seed endpoints (~449 tokens total, read 280-444)
2. `apps/backend/modules/health/facade.py` - search for existing methods that can seed data (e.g., `_ensure_record_shell`, any insert methods)
3. `apps/backend/modules/consent/facade.py` - search for existing methods that can seed egress data

**Total:** ~800 tokens of targeted reading, well within budget.

## Do NOT read

- Frontend code
- Route adapters (health/consent)
- Redis cache code
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verify current state
- `grep -n "from modules.health.schema" apps/backend/app/main.py` - confirm raw imports exist
- `grep -n "from modules.consent.schema" apps/backend/app/main.py` - confirm raw imports exist

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes
- `npm run typecheck` passes
- `grep -n "from modules.health.schema" apps/backend/app/main.py` returns no matches
- `grep -n "from modules.consent.schema" apps/backend/app/main.py` returns no matches

## Handoff notes

- The seed endpoints are gated behind `settings.mock_otp_readback_enabled` (dev/test only)
- They directly import `health_patient_records`, `health_record_entries`, `consent_consents`, `consent_egress_log` from schema modules
- They also import `write_outbox`, `dispatch`, `record_consumed_event` from bus modules
- Consider: add `seed_record_entries` and `seed_egress_log` methods to the respective facades
- The bus imports (`write_outbox`, `dispatch`) are harder to move - consider leaving them if the facade approach is too complex
