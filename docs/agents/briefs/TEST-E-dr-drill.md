# Brief - 133 TEST-E - Monthly DR drill (backup-restore round-trip)

**Ticket:** #133 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Operationalize the boundary durability floor (NFR-PERF-004) as a monthly DR drill in a new scheduled workflow `backup-drill.yml`:

1. Real `pg_dump` of the live Supabase database over the session-pooler connection (`secrets.SUPABASE_DATABASE_URL`).
2. AES-256-encrypt the dump (passphrase from a new secret) and store it as a workflow artifact.
3. Restore the dump into a throwaway Postgres service container in the job.
4. Assert the round-trip: the demo identity is present and a row-count checksum matches.

If Supabase has paused (7-day idle), the job must fail loudly with a clear message instead of passing silently. The existing `deploy/cron/backup.sh` + the `backup-smoke` CI job are the precedent for the dump/encrypt/restore mechanics.

Acceptance criteria (verbatim):

- `backup-drill.yml` runs monthly (cron) and can be dispatched manually for verification
- The drill does a live `pg_dump` -> AES-256-encrypt -> artifact -> restore into a throwaway Postgres -> round-trip asserts (demo identity present + checksum)
- A paused/unreachable Supabase fails the job loudly with a clear message, never a silent pass
- The backup passphrase is a secret, never committed

## Read-list (in order)

1. `deploy/cron/backup.sh` - the exact dump/encrypt mechanics to reuse (`pg_dump --format=custom` piped to `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE`, empty-file guard) (~0.5K).
2. `.github/workflows/ci.yml` - the `backup-smoke` job: Postgres 16-alpine service container, `apt-get install postgresql-client`, `BACKUP_PASSPHRASE` env, decrypt + `createdb` + `pg_restore` + row-count assert (~0.9K).
3. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.E + §5 - the four drill steps and hard-fail posture (~0.3K).
4. `render.yaml`/`apps/backend/app/config.py` - where the Supabase URL shape lives (session-pooler connection) (~0.3K).

## Do NOT read

- `docs/archive/`, unrelated module specs, the frontend.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Manual dispatch of `backup-drill.yml` completes green with a round-trip assert; `npm run check:backup` still passes.

## Handoff notes

- `SUPABASE_DATABASE_URL` exists as a secret and is used by `deploy.yml`'s `migrate-and-seed` job - reuse that wiring. A NEW secret for the backup passphrase must be added (never hardcode it; `deploy/cron/backup.sh` already refuses to run without `BACKUP_PASSPHRASE`).
- Round-trip assert targets live demo data: the seeded demo identity `+91 9000000001` (row present in the restored DB) plus a row-count checksum compared source-vs-restored.
- Supabase free pauses after 7 days idle - connection/restore failure must produce a loud, explicit message (e.g. "Supabase database unreachable - paused?"), never a pass with zero rows checked.
- `openssl` params must match `deploy/cron/backup.sh` exactly (`-aes-256-cbc -pbkdf2 -iter 200000`) or the decrypt in the drill will fail.
- Restore target is a throwaway Postgres service container in the job (same pattern as `backup-smoke`), never the live DB.
