# Brief - 113 DEPLOY-2 - Alembic migrations honour DATABASE_URL

**Ticket:** #113 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

Make `alembic upgrade head` deployable against a remote Postgres: `alembic/env.py` overrides `sqlalchemy.url` from `DATABASE_URL` when the env var is set, so the same harness that migrates the localhost dev database migrates the Supabase free-tier database. `alembic.ini` keeps its localhost default untouched for local dev.

Acceptance criteria (verbatim):

- `alembic upgrade head` uses `DATABASE_URL` when set; falls back to `alembic.ini` otherwise
- Verified against a throwaway Postgres reachable only via `DATABASE_URL` (localhost default not used)
- `npm run migration-check` still green (single head + cross-schema FK scan)
- `npm run test:unit:backend` green

## Read-list (in order)

1. Plan §4.2 - the one-line change intent (~0.2K).
2. `apps/backend/alembic/env.py` - `run_async_migrations` builds the connectable from `config.get_section(config.config_ini_section, {})`; override the `sqlalchemy.url` key in that section from `os.environ.get("DATABASE_URL")` when set (~0.8K).
3. `apps/backend/alembic.ini` - the `sqlalchemy.url = postgresql+asyncpg://...localhost...` line that stays as the local-dev default (~0.3K).

## Do NOT read

- Migration revision files under `apps/backend/alembic/versions/`, the app shell, frontend sources, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run migration-check` (currently single head, no cross-schema FK)
- `npm run test:unit:backend` (currently 570 passed)

## Done-verify (acceptance criteria → commands)

- Point `DATABASE_URL` at a scratch Postgres (anything except the localhost default) and run `alembic upgrade head`; it migrates that DB. Unset the var and confirm the localhost default still applies.
- `npm run migration-check`, `npm run test:unit:backend` - green

## Handoff notes

- The override belongs in the ONLINE path (`run_async_migrations`), which is what `alembic upgrade head` uses; `run_migrations_offline` reads `config.get_main_option("sqlalchemy.url")` and is only used by `alembic heads`/SQL generation - leave it (or mirror the same override, but it is not required by the plan).
- The `section` dict passed to `async_engine_from_config` is read via the `prefix="sqlalchemy."` key, so set `section["sqlalchemy.url"]`.
- Do not edit `alembic.ini` - local dev keeps its localhost default.
