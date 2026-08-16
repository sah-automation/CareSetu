# Brief - 117 DEPLOY-7 - Provision free tiers + verify live demo

**Ticket:** #117 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The live, public demo: create the Supabase free project (direct connection string into the GitHub secret + Render env), the Render service from the blueprint (env vars + deploy hook into the GitHub secret), and the Vercel project (root dir `apps/frontend`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_DEMO_MODE=true`). Then verify the end-to-end demo flow on the live URLs: open the Vercel app, register `+91 9000000001`, the demo banner shows the OTP, verify, and a session lands on the protected route. Accepts the plan's free-tier caveats (Render spin-down, Supabase 7-day pause, no backups).

Acceptance criteria (verbatim):

- Supabase project created; direct connection string live as the `SUPABASE_DATABASE_URL` secret and Render env
- Render service from the blueprint; deploy hook live as the `RENDER_DEPLOY_HOOK_URL` secret
- Vercel project serving the PWA with the two env vars inlined at build
- A push to `main` runs `deploy.yml` to green: migrations applied, seed run, Render redeployed, Vercel rebuilt
- Live demo flow works: register `+91 9000000001` -> OTP banner -> verify -> session -> protected route

## Read-list (in order)

1. Plan §5.1 (Supabase), §5.2 (Render), §5.3 (Vercel) - the exact connection-string shape, env tables, and deploy-hook creation (~2K).
2. Plan §6.2, §6.3, §7, §9 - the secrets, the demo flow script, the accepted caveats, and the final checklist items (~0.8K).
3. `docs/agents/issue-tracker.md` - how to set GitHub secrets/actions if needed for the repo (`sah-automation/CareSetu`).

## Do NOT read

- Backend/frontend source internals beyond the §6.3 flow, alembic revisions, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- All of DEPLOY-1..6 merged on `main` and green (repo harness: `npm run test:unit`, `npm run typecheck`, `npm run migration-check`, `npm run lint`).

## Done-verify (acceptance criteria → commands)

- The five acceptance criteria above, checked live against the deployed URLs.

## Handoff notes

- This ticket needs HUMAN dashboard access (supabase.com, render.com, vercel.com account creation cannot be automated) - it carries `ready-for-human`, not `ready-for-agent`.
- URL-encode special characters (`@`, `#`, ...) in the Supabase password when building the `postgresql+asyncpg://` direct connection string.
- Supabase free pauses after 7 days idle - restore from the dashboard before any demo; no automated backups (manual `pg_dump` only, acceptable for demo data).
- Render's start command ALSO runs migrations on every boot (belt-and-suspenders on top of the workflow's migrate step) - a fresh DB is migrated by the first push.
- The worker/outbox dispatcher and MinIO/Gemini/backup-cron are deliberately NOT deployed (plan §2.3) - do not add them.
- Confirmation of success = the §6.3 demo flow, not just green CI.
