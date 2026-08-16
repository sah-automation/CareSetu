# Brief - 114 DEPLOY-3 - Idempotent demo seed

**Ticket:** #114 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

A runnable, idempotent demo-data seed: `python -m scripts.seed_demo` from `apps/backend` ensures the demo identity for phone `+919000000001` exists (registering it via the iam facade's register path if missing; no-op if present, so repeated/concurrent runs converge with no duplicates) and prints the demo phone plus which OTP surface is enabled. This is what `deploy.yml` runs after migrations so a fresh Supabase database is demo-ready.

Acceptance criteria (verbatim):

- Script runs as `python -m scripts.seed_demo` against a migrated DB
- Running it twice produces exactly one identity row for the demo phone (duplicate-resolution convergence)
- Prints the demo phone and the OTP surface (mock read-back enabled vs not)
- `npm run test:unit:backend` green (unit coverage of the seed's no-op/converge path as feasible)

## Read-list (in order)

1. Plan §4.4, §5.1 step 5, §6.1 - the seed's contract and where it runs in the deploy path (~0.9K).
2. `IamFacade` (`apps/backend/modules/iam/facade.py`) - ONLY the constructor signature (engine, sms_adapter, clock, token keys) and `register_patient` + its `RegisterPatientResult` shape; the phone normalizes server-side to +91 E.164 (~2K).
3. `Settings` (`apps/backend/app/config.py`) + `build_sms_adapter` (`apps/backend/modules/iam/adapters/sms.py`) - how to construct a mock-provider facade from the environment (both already digested in this repo's conventions; skim the signatures) (~1K).
4. An existing script in `apps/backend/scripts/` (e.g. `check_backup_config.py`) - the invocation/entrypoint style for `python -m scripts.<name>` (~0.5K).

## Do NOT read

- Alembic migration revisions, the dispatcher/outbox internals, domain internals beyond `register_patient`, frontend sources, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (currently 570 passed)

## Done-verify (acceptance criteria → commands)

- `npm run migration-check` green; migrate a scratch Postgres, then run `python -m scripts.seed_demo` twice from `apps/backend` and assert exactly one identity row for `+919000000001` (the iam identities table).
- `npm run test:unit:backend`, `npm run typecheck:backend` - green

## Handoff notes

- `register_patient` already guarantees convergence: the unique `phone_e164` index makes the INSERT a no-op for an existing phone, so a second run re-resolves the same identity rather than duplicating.
- Construct the facade with the mock SMS adapter (the settings default) so the OTP issuance's background delivery is harmless in-process; wrap the whole thing in an async entrypoint (`asyncio.run`) and dispose the engine when done.
- The script reads `DATABASE_URL` from the environment via `get_settings()` - on the deploy path that is the Supabase direct connection string; locally it defaults to the localhost dev database.
- The script's `__main__` should be defensive: it is a demo convenience, not a load-bearing path - print the demo phone and which OTP surface is enabled, and fail loudly on connection errors.
- Test surface: the no-op/converge behaviour is best proven by the two-run done-verify against a scratch DB; keep any unit test to the script's pure logic (e.g. output formatting) rather than faking the engine.
