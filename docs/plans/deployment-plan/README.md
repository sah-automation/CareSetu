# Deployment Plan - README (easy reference)

**Purpose:** current and future deployment strategy for CareSetu. The active plan is the portfolio free-tier split (**Render + Vercel + Supabase**). The roadmap's launch target (single VM, roadmap `PHASE-14`) is documented as the future migration path.

## Files

| File                           | Read when                                                                                                                                                              |
| :----------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `portfolio-deployment-plan.md` | The full plan: target architecture, code changes, provisioning steps, env vars, CD pipeline, free-tier caveats, VM migration path. Start here for any deployment work. |

## TL;DR - the portfolio deployment

- **CI (already live):** `.github/workflows/ci.yml` - lint, typecheck, unit, page-budget, migration-check, integration, backup-smoke, e2e, security scan. Green on `main`.
- **CD (to build):** `.github/workflows/deploy.yml` - on push to `main`: CI gate → alembic migrate + seed against Supabase → trigger Render deploy hook. Vercel auto-deploys from the same push.
- **Backend:** Render free web service (`render.yaml`, root dir `apps/backend`), start = `alembic upgrade head && uvicorn app.main:app`.
- **Frontend:** Vercel free, root dir `apps/frontend`, env `NEXT_PUBLIC_API_BASE_URL` + `NEXT_PUBLIC_DEMO_MODE`.
- **Database:** Supabase free Postgres (direct connection, port 5432).
- **OTP:** demo-mode - `DEMO_MODE=true`, OTP shown in the UI banner (mock SMS). Portfolio-only exception to never-expose-OTP.
- **Async worker:** deferred (no business handlers exist yet). Render free has no background workers; run the dispatcher in-process (FastAPI lifespan) from Phase 4 onward.

## Key free-tier caveats (accepted - no keep-alive)

- Render web service spins down after 15 min idle; cold start ~1 min on first request.
- **Supabase free project pauses after 7 days idle** - restore it from the Supabase dashboard before a demo.
- Supabase free has **no automated backups** (diverges from roadmap `NFR-004`); manual `pg_dump` only.
- No free background worker on Render -> worker deferred.
- Free SMS providers do not match the EXT-001 contract (`POST {base}/v1/send`, `{request_id,status}`); demo mode chosen instead of a provider adapter.

## Code changes (all delivered - DEPLOY-1..7, #112-#125)

| Change                                        | File                                                          | Status            |
| :-------------------------------------------- | :------------------------------------------------------------ | :---------------- |
| `CORS_ALLOWED_ORIGINS` + `DEMO_MODE` settings | `apps/backend/app/config.py`                                  | done (DEPLOY-1)   |
| Honour `DATABASE_URL` in migrations           | `apps/backend/alembic/env.py`                                 | done (DEPLOY-2)   |
| CORS from settings + demo OTP gate            | `apps/backend/app/main.py`                                    | done (DEPLOY-1)   |
| Idempotent demo identity seed                 | `apps/backend/scripts/seed_demo.py`                           | done (DEPLOY-3)   |
| Demo OTP read-back client call                | `apps/frontend/src/lib/auth/api.ts`                           | done (DEPLOY-4)   |
| Demo OTP banner                               | `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx` | done (DEPLOY-4)   |
| Render blueprint                              | `render.yaml`                                                 | done (DEPLOY-5)   |
| CD workflow                                   | `.github/workflows/deploy.yml`                                | done (DEPLOY-6/7) |

> Deployed-auth behavior (cookies, guard, credentialed CORS) is governed by `docs/adr/0007-split-origin-deployment-session-invariants.md` - read it before touching session transport; localhost masks split-origin failures.

## Env var cheat sheet

**Render** - `DATABASE_URL` (Supabase direct), `APP_ENVIRONMENT=production`, `GATEWAY_JWT_VERIFY_ENABLED=true`, `GATEWAY_JWT_SIGNING_KEY`, `GATEWAY_RATE_LIMIT_ENABLED=true`, `SMS_PROVIDER=mock`, `DEMO_MODE=true`, `CORS_ALLOWED_ORIGINS=https://<vercel>.vercel.app`.

**Vercel** - `NEXT_PUBLIC_API_BASE_URL=https://<render>.onrender.com`, `NEXT_PUBLIC_DEMO_MODE=true`.

**GitHub Actions secrets** - `SUPABASE_DATABASE_URL`, `RENDER_DEPLOY_HOOK_URL`.

Full details: see `portfolio-deployment-plan.md`.
