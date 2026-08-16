# Brief - 115 DEPLOY-5 - Render blueprint (render.yaml)

**Ticket:** #115 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

A committed Render Blueprint for the backend web service: root directory `apps/backend`, Python 3.13, build `uv sync --frozen --no-dev`, start `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and the plan §5.2 env vars (`DATABASE_URL`, `APP_ENVIRONMENT=production`, JWT verify/rate-limit on with a signing key, `SMS_PROVIDER=mock`, `DEMO_MODE=true`, `CORS_ALLOWED_ORIGINS`). This makes the Render service reproducible from the repo rather than a hand-built dashboard service.

Acceptance criteria (verbatim):

- `render.yaml` is valid Blueprint YAML for a single web service rooted at `apps/backend`
- Env vars match plan §5.2 exactly (including `DEMO_MODE=true`, mock SMS)
- Build/start commands match the plan (frozen uv sync; alembic upgrade head then uvicorn on `$PORT`)
- Lint clean (prettier/whitespace pre-commit)

## Read-list (in order)

1. Plan §5.2 - the full Render service section: root dir, Python version, build/start commands, and the env-var table (~0.9K).
2. `apps/backend/pyproject.toml` + the presence of `apps/backend/uv.lock` - confirms `uv sync --frozen --no-dev` is a valid build (frozen needs a lockfile) (~0.7K).
3. `deploy/edge/Caddyfile` - existing repo deploy config for style conventions only (do not copy its behaviour) (~0.4K).

## Do NOT read

- Alembic revisions, frontend sources, app internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run lint` (currently all pre-commit hooks pass)

## Done-verify (acceptance criteria → commands)

- `npm run lint` (prettier on the new YAML) clean; the YAML parses (`python -c "import yaml,sys; yaml.safe_load(open('render.yaml'))"`).
- Actual service creation/rendering is deferred to DEPLOY-7.

## Handoff notes

- Blueprint command paths are relative to the service `rootDir` (`apps/backend`), so the start command is `alembic upgrade head && uvicorn app.main:app ...` - NOT repo-root-prefixed.
- `$PORT` must survive shell interpolation in the YAML so Render's injected port is used - do not quote it in a way that the shell sees a literal.
- `GATEWAY_JWT_SIGNING_KEY` is a placeholder value in the blueprint for reproducibility (Render secrets or the deploy-time env override it); do NOT commit a real key.
- Keep env names exactly as `Settings` reads them (`DATABASE_URL`, `APP_ENVIRONMENT`, `GATEWAY_JWT_VERIFY_ENABLED`, `GATEWAY_JWT_SIGNING_KEY`, `GATEWAY_RATE_LIMIT_ENABLED`, `SMS_PROVIDER`, `DEMO_MODE`, `CORS_ALLOWED_ORIGINS`) - DEPLOY-1/#112 made them real.
