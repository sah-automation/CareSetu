# Deployment Plan: Portfolio Free-Tier (Render + Vercel + Supabase) and Future VM Path

**Status:** planned (approved scope; code changes not yet implemented)
**Date:** 2026-08-15
**Decisions recorded:** user chose demo-mode OTP (shown in UI), explicit GitHub Actions CD, no keep-alive.
**Upstream targets:** roadmap `PHASE-14` release environment (single VM) documented here as the future migration path; this plan diverges from it for a ₹0 free-tier portfolio deployment.
**Scope:** deploy the Phase-2-complete app (FastAPI backend + Next.js frontend + Postgres, IAM/OTP auth) for a public portfolio demo with demo data, using only free tiers.

---

## 1. Goal

Stand up a public, live CareSetu demo at zero monthly cost so a recruiter or evaluator can open the app, register with a demo phone, and complete the OTP flow end to end:

- **Frontend:** Next.js PWA on Vercel free.
- **Backend:** FastAPI on Render free (web service).
- **Database:** PostgreSQL on Supabase free.
- **CI/CD:** existing GitHub Actions CI stays the gate; a new `deploy.yml` runs migrations + seed and triggers deploys.
- **OTP:** demo mode - OTP read back into the UI (mock SMS), no real SMS spend.

The plan is written to double as a migration reference: section 8 covers moving to the roadmap's single-VM launch environment.

---

## 2. Current state assessment (post-Phase-2)

### 2.1 Already in place (no work needed)

| Asset                                       | Where                                                                                                                  |
| :------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------- |
| GitHub repo + `main` branch + origin        | `sah-automation/CareSetu`                                                                                              |
| Full CI pipeline                            | `.github/workflows/ci.yml` (lint, typecheck, unit, page-budget, migration-check, integration, backup-smoke, e2e, scan) |
| Env-driven backend `Settings`               | `apps/backend/app/config.py`                                                                                           |
| Alembic async migrations                    | `apps/backend/alembic/` (`env.py`)                                                                                     |
| FastAPI shell with gateway stack            | `apps/backend/app/main.py` (`app.main:app`)                                                                            |
| Frontend API base via env                   | `apps/frontend/src/lib/auth/api.ts` (`NEXT_PUBLIC_API_BASE_URL`)                                                       |
| Mock SMS adapter + mock OTP read-back route | `apps/backend/modules/iam/adapters/sms.py`, `/v1/auth/dev/otp` in `main.py`                                            |
| JWT verify + auth-surface rate limit        | gateway middleware (Phase 2)                                                                                           |

### 2.2 Gaps to close (the change list)

| #   | Gap                                                                                  | Change                                      |
| :-- | :----------------------------------------------------------------------------------- | :------------------------------------------ |
| 1   | CORS hardcodes `localhost:3000`; production was designed for same-origin Caddy proxy | Make allowed origins env-driven             |
| 2   | Demo OTP read-back is gated to dev/test environments                                 | Gate on `DEMO_MODE` as well                 |
| 3   | `alembic.ini` hardcodes the localhost URL; `env.py` ignores `DATABASE_URL`           | Read `DATABASE_URL` in `env.py`             |
| 4   | No demo data                                                                         | Idempotent seed script                      |
| 5   | No Render/Vercel provisioning                                                        | `render.yaml` + Vercel project config       |
| 6   | No CD                                                                                | `.github/workflows/deploy.yml`              |
| 7   | No runbook                                                                           | this folder (`docs/plans/deployment-plan/`) |

### 2.3 Deliberately deferred (do NOT build now)

- **Async worker** (`worker/main.py`): Render free has no free background workers. No business event handlers are registered yet (Phase 1/2 registers are empty), so the outbox/dispatcher does nothing useful in production today. Outbox rows accumulate harmlessly and the dispatcher's reclaim design handles them later. From Phase 4 (audit) run the dispatcher in-process via a FastAPI lifespan task instead of a separate process.
- **MinIO / object storage**: not wired into `Settings`; first needed at Phase 7 (intake media). Later free options: Supabase Storage or Cloudflare R2 (free 10 GB).
- **Gemini / EXT-002 AI**: Phase 7 concern only.
- **Backup cron** (`deploy/cron/backup.sh`): VM/`pg_dump` based; Supabase free has no automated backups. Accept for demo (see caveats).
- **Caddy edge** (`deploy/edge/Caddyfile`): unused in the split (Vercel + Render each terminate TLS). Keep the file - it is the VM-path edge.

---

## 3. Target architecture

```
+----------------------+       /v1/auth/* (CORS)      +----------------------+
|  Vercel (free)       | --------------------------> |  Render (free web)   |
|  Next.js 16 PWA      |   NEXT_PUBLIC_API_BASE_URL  |  FastAPI app.main:app|
|  apps/frontend       |                             |  apps/backend        |
+----------------------+                             +----------+-----------+
                                                             |
                                                       DATABASE_URL
                                                             v
                                                  +----------------------+
                                                  |  Supabase (free)     |
                                                  |  PostgreSQL 15/17    |
                                                  |  direct conn :5432   |
                                                  +----------------------+

GitHub Actions:
  ci.yml        -> gate on every push/PR (existing)
  deploy.yml    -> push to main: alembic upgrade head + seed -> Render deploy hook
                   (Vercel auto-deploys from the same push)
```

Routing notes:

- The frontend calls the backend cross-origin via `NEXT_PUBLIC_API_BASE_URL`, so the backend must allow the Vercel origin (change #1). No next.config rewrites needed.
- The same-origin Caddy design (deploy/edge) is the VM path, not this one.

---

## 4. Code changes

### 4.1 `apps/backend/app/config.py`

Add to the `Settings` dataclass:

- `cors_allowed_origins: tuple[str, ...] = ()` - parsed from env `CORS_ALLOWED_ORIGINS` (comma-separated), via a `_env_csv` helper. Empty = no extra origins (matches current prod posture).
- `demo_mode: bool = False` - parsed from env `DEMO_MODE` via `_env_bool`.

`__post_init__` validation:

- `demo_mode=True` requires `sms_provider == "mock"` (fail-closed: the demo-flag must never ride a real provider).

Wire into `get_settings()`.

### 4.2 `apps/backend/alembic/env.py`

In `run_async_migrations()`, override `sqlalchemy.url` from `os.environ.get("DATABASE_URL")` when set, so `alembic upgrade head` works against Supabase/Render without touching `alembic.ini` (which keeps its localhost default for local dev).

### 4.3 `apps/backend/app/main.py`

- CORS: `allow_origins = tuple(dict.fromkeys(_DEV_CORS_ORIGINS + resolved_settings.cors_allowed_origins))` (preserves the localhost dev origin, adds the env-configured Vercel origin, dedupes).
- Demo OTP gate: the `/v1/auth/dev/otp` route currently answers only when `sms_provider == "mock"` **and** `app_environment in {dev, test}`. Change the condition to also allow `settings.demo_mode is True`. Document the portfolio-only exception (the design rule "never expose the OTP" is relaxed only under the explicit `DEMO_MODE` flag with mock SMS).

### 4.4 `apps/backend/scripts/seed_demo.py`

Idempotent demo seed, runnable as `python -m scripts.seed_demo` from `apps/backend`:

- Ensures the demo identity exists for phone `+919000000001` (register if missing, no-op if present).
- Prints the demo phone + which OTP surface is enabled. Safe to run repeatedly (no duplicate rows - duplicate resolution / unique phone index handles convergence).

### 4.5 `apps/frontend/src/lib/auth/api.ts`

Add `fetchDemoOtp(phone: string): Promise<string | null>` calling `GET /v1/auth/dev/otp?phone=...` and returning the code (null on 404/error). Only ever invoked from the demo banner.

### 4.6 `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx`

When `NEXT_PUBLIC_DEMO_MODE === "true"` (inlined at build time on Vercel):

- After a successful register/resend, call `fetchDemoOtp` and render a visible banner: "Demo OTP: XXXXXX".
- When the flag is absent, the component behaves exactly as today (banner code is inert).

---

## 5. Provisioning steps

### 5.1 Supabase (database)

1. Create a free project at supabase.com (region close to the target audience, e.g. Singapore/Mumbai).
2. Dashboard → Project Settings → Database → Connection string → **Direct connection** (port `5432`), the `postgres` database:
   `postgresql+asyncpg://postgres:<password>@db.<ref>.supabase.co:5432/postgres`
3. URL-encode special characters in the password (`@`, `#`, etc.).
4. The app and migrations operate inside the `postgres` database; the baseline migration creates the 11 private schemas (no `CREATE DATABASE` needed, no restricted extensions used).
5. No migrations are applied manually yet - `deploy.yml` applies them on the first push to `main` (or run `alembic upgrade head` locally against this URL once).

Free-tier constraints (accepted):

- **Project pauses after 7 days of inactivity.** Restore from the dashboard before a demo.
- No automated backups. Manual `pg_dump` only if desired.
- ~60 direct connections on free - fine for a demo with `NullPool` (app already uses `NullPool`).

### 5.2 Render (backend)

1. Create the service via the **Blueprint** (`render.yaml`) or manually: root directory `apps/backend`, Python, env `PYTHON_VERSION=3.13`.
2. Build command: `uv sync --frozen --no-dev` (uses `uv.lock`; add `UV=1` or a `pip install uv` bootstrap if the buildpack needs it).
3. Start command: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` (migration is idempotent; runs every boot as belt-and-suspenders even though `deploy.yml` also migrates).
4. Env vars:

| Var                          | Value                                       |
| :--------------------------- | :------------------------------------------ |
| `DATABASE_URL`               | Supabase direct connection string           |
| `APP_ENVIRONMENT`            | `production`                                |
| `GATEWAY_JWT_VERIFY_ENABLED` | `true`                                      |
| `GATEWAY_JWT_SIGNING_KEY`    | strong random secret (openssl rand -hex 32) |
| `GATEWAY_RATE_LIMIT_ENABLED` | `true`                                      |
| `SMS_PROVIDER`               | `mock`                                      |
| `DEMO_MODE`                  | `true`                                      |
| `CORS_ALLOWED_ORIGINS`       | `https://<frontend>.vercel.app`             |

5. Create a **deploy hook** (Render dashboard → service → Deploy Hooks) and copy its URL into the GitHub secret `RENDER_DEPLOY_HOOK_URL`.

### 5.3 Vercel (frontend)

1. Import the GitHub repo; set Root Directory to `apps/frontend`; framework auto-detects Next.js.
2. Env vars (build-time inlined):

| Var                        | Value                                   |
| :------------------------- | :-------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | `https://<render-service>.onrender.com` |
| `NEXT_PUBLIC_DEMO_MODE`    | `true`                                  |

3. Vercel auto-deploys on push to `main`; no extra config needed.

---

## 6. CD pipeline

### 6.1 New workflow `.github/workflows/deploy.yml`

Trigger: `push` to `main` + `workflow_dispatch`.

`concurrency: deploy` (single in-flight deploy; cancel older runs on the same branch).

Jobs:

1. **gate** - `uses: ./.github/workflows/ci.yml` (or `needs` an equivalent required check) so CD only runs on green CI.
2. **migrate-and-seed** - `ubuntu-latest`, `setup-uv`, `uv sync --project apps/backend`:
   - `DATABASE_URL: ${{ secrets.SUPABASE_DATABASE_URL }}`
   - `uv run --project apps/backend alembic -c apps/backend/alembic.ini upgrade head`
   - `uv run --project apps/backend python -m scripts.seed_demo`
3. **deploy-render** - needs migrate-and-seed:
   - `curl -X POST "${{ secrets.RENDER_DEPLOY_HOOK_URL }}"`

Vercel is not part of the workflow - it deploys itself from the same push. Ordering note: Vercel's build may briefly race the migration; the app tolerates this (registration against a not-yet-migrated DB returns a 500 envelope the UI shows as an error, then retries after the workflow finishes).

### 6.2 GitHub Actions secrets

| Secret                    | Source                                                                                            |
| :------------------------ | :------------------------------------------------------------------------------------------------ |
| `SUPABASE_DATABASE_URL`   | Supabase direct connection string (see 5.1)                                                       |
| `RENDER_DEPLOY_HOOK_URL`  | Render service deploy hook (see 5.2)                                                              |
| `BACKUP_DRILL_PASSPHRASE` | random passphrase for the DR drill's at-rest AES-256 encryption (TEST-E #133; `backup-drill.yml`) |

### 6.3 Demo flow after deploy

1. Open the Vercel URL.
2. Enter demo phone `+91 9000000001`.
3. The demo banner shows the OTP (read back from `/v1/auth/dev/otp`).
4. Enter the OTP → verified → session issued → protected route reachable.

---

## 7. Free-tier caveats (accepted)

| Caveat                                          | Impact                                                              | Workaround chosen                                   |
| :---------------------------------------------- | :------------------------------------------------------------------ | :-------------------------------------------------- |
| Render spins down after 15 min idle             | first request per idle period ~1 min cold start                     | none (accepted)                                     |
| Supabase pauses after 7 days idle               | DB unavailable; paused projects must be restored from the dashboard | none (accepted); restore before a demo              |
| Supabase free: no automated backups             | data loss on delete/incident; diverges from roadmap `NFR-004`       | manual `pg_dump`; acceptable for demo data          |
| Render free: no background workers              | the outbox dispatcher cannot run as a process                       | defer worker; in-process lifespan loop from Phase 4 |
| Free SMS providers don't match EXT-001 contract | real OTP delivery impossible                                        | demo-mode OTP in UI (`DEMO_MODE=true`, mock SMS)    |
| Cold-start load                                 | concurrent demo traffic may see slow first responses                | none (single evaluator use case)                    |

### 7.1 Post-deploy optimizations (applied 2026-08-16, POST-DEPLOY-OPTS)

Audit of the live free-tier stack. Three code changes + two dashboard settings, recorded here so a future session knows why things are configured as they are:

| #   | Change                                                                 | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Where                                                          |
| :-- | :--------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------- |
| 1   | CI no longer runs standalone on push to `main`                         | deploy.yml calls `ci.yml` as its gate, so a push to main ran the whole 12-job suite twice (once standalone, once as the deploy gate). Removing the `push` trigger leaves PR CI and the main-push gate intact - main still gets full CI, exactly once per push.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | `.github/workflows/ci.yml` (`on:`)                             |
| 2   | Render **auto-deploy turned OFF** (dashboard)                          | The deploy hook fired by deploy.yml is now the sole automated deploy trigger, so the DB is always migrated (migrate-and-seed job) before a Render boot. Manual dashboard deploys still work.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Render dashboard → service settings                            |
| 3   | Boot-time `alembic upgrade head` removed from the Render start command | Redundant now that deploy.yml migrates before every hook-triggered deploy; removing it trims seconds off every cold start (the slowest part of the free plan). Tradeoff: a fresh-from-scratch blueprint provision relies on the next push to main to migrate before first boot.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | `render.yaml` (`startCommand`)                                 |
| 4   | Vercel **Ignored Build Step** set to a `HEAD^`-based bash diff         | Skips the frontend build when nothing changed since the previous commit, saving Hobby build quota (100 builds/day) on pushes that don't touch the frontend. Command: `git diff HEAD^ HEAD --quiet` - compares the deployed commit against its parent, so it never depends on Vercel's `$VERCEL_GIT_PREVIOUS_SHA`. **Failure modes found 2026-08-16:** (1) a `-- apps/frontend ...` pathspec version returned 0 (skip) for every commit because Vercel runs the step with its working directory at the **project root (`apps/frontend`)**, so the pathspec matched nothing and the diff was empty - every production build from `d78a922` to `9112f50` was silently cancelled and the live site kept serving the pre-header `d24bd67` build (TEST-B2 failed on the missing `X-Content-Type-Options`). (2) The original `$VERCEL_GIT_PREVIOUS_SHA`-based command cancelled the same commits - treat that variable as unreliable. Dropping the pathspec (whole-tree `git diff HEAD^ HEAD --quiet`) fixed it; tradeoff: backend-only and docs-only pushes also rebuild the frontend. **Gotchas:** enter the bare command, never a `bash ` prefix - Vercel executes the box as `bash <script>`, so a leading `bash ` makes bash treat `git` as a script file and fail with `/usr/bin/git: cannot execute binary file` (seen on PR #140, 2026-08-16). After changing the rule, click **Redeploy** on the latest production deployment to force the pending commit through. | Vercel dashboard → project settings → Git → Ignored Build Step |
| 5   | Vercel build now fails loudly if `NEXT_PUBLIC_API_BASE_URL` is missing | Before, the frontend fell back to `http://localhost:8000` when the var was absent - the site built and looked fine but quietly talked to localhost (broken demo). A new `next.config.ts` throws during Vercel builds only (`VERCEL` is set by Vercel, never locally/CI).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | `apps/frontend/next.config.ts`                                 |

---

## 8. Future migration path: single VM (roadmap PHASE-14)

The roadmap's launch target is one VM (`FastAPI + worker + Next.js + Postgres + MinIO + Caddy edge + backup cron`, roadmap §2.14). When moving off the free tiers, do the reverse of this plan:

| Free-tier artifact                        | VM replacement                                                                  |
| :---------------------------------------- | :------------------------------------------------------------------------------ |
| `NEXT_PUBLIC_API_BASE_URL` (cross-origin) | same-origin `/api/*` via `deploy/edge/Caddyfile`; unset the env var             |
| Render web service                        | systemd service running `uvicorn app.main:app` (workers via gunicorn if needed) |
| Worker deferred                           | run `python -m worker.main` as its own systemd unit (outbox/dispatcher drains)  |
| Supabase `DATABASE_URL`                   | local PostgreSQL URL; `alembic upgrade head` at deploy                          |
| MinIO (Phase 7+)                          | local MinIO, or keep Supabase Storage/R2 if still convenient                    |
| Vercel                                    | `next build && next start` behind Caddy, or static export                       |
| `CORS_ALLOWED_ORIGINS`                    | leave empty (same-origin)                                                       |
| `DEMO_MODE=true`                          | `false`; use `SMS_PROVIDER=provider` with a real SMS_API_KEY/BASE_URL           |
| No automated backups                      | `deploy/cron/backup.sh` + `deploy/cron/caresetu-backup.cron` (already in repo)  |
| No keep-alive                             | always-on VM; no pause issue                                                    |

The code changes in section 4 are all env-driven (off by default), so the same codebase runs both topologies - only env vars and deployment config differ.

---

## 9. Implementation checklist

- [ ] `apps/backend/app/config.py`: add `cors_allowed_origins` + `demo_mode` (+ validation)
- [ ] `apps/backend/alembic/env.py`: honour `DATABASE_URL`
- [ ] `apps/backend/app/main.py`: CORS from settings; demo OTP gate
- [ ] `apps/backend/scripts/seed_demo.py`: idempotent demo identity
- [ ] `apps/frontend/src/lib/auth/api.ts`: `fetchDemoOtp`
- [ ] `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx`: demo banner
- [ ] `render.yaml`: web service blueprint
- [ ] `.github/workflows/deploy.yml`: CD (migrate + seed + Render hook)
- [ ] Supabase project + direct connection string (GitHub secret + Render env)
- [ ] Render service (env vars + deploy hook)
- [ ] Vercel project (root dir + env vars)
- [ ] Verify locally: `npm run test:unit:backend`, `npm run typecheck:backend`, `npm run migration-check`
- [ ] Push to `main`; confirm `deploy.yml` runs, Render redeploys, Vercel builds
- [ ] Demo flow: register `+91 9000000001` → OTP banner → verify → session

## 10. Verification commands (repo harness)

```text
npm run test:unit:backend   # pytest unit
npm run test:unit:frontend  # vitest
npm run typecheck:backend   # mypy --strict
npm run typecheck:frontend  # tsc --noEmit
npm run migration-check     # alembic single head + cross-schema FK scan
```

CI (`ci.yml`) already runs all of these plus integration, e2e, and security scans on `main`.
