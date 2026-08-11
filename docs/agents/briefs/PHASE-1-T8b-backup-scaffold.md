# Brief - 32 PHASE-1 T8b: Daily backup scaffolding

**Ticket:** #32 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The `NFR-004` durability floor: a committed daily backup script (`pg_dump` of
the single instance) under `deploy/cron/`, a cron config for the staging VM, a
CI smoke test that runs the dump against a throwaway DB, and the RPO contract
documented. Structure with no business logic.

Acceptance criteria (from #32; all delivered):

- [x] Backup script + cron config committed under `deploy/cron/`
- [x] CI smoke test runs the dump against the throwaway DB
- [x] RPO <= 24h documented (daily cadence)

## Read-list (in order)

1. `CONTEXT.md` glossary - no new terms; "outbox" etc. are irrelevant here.
   (~0.5K tokens)
2. Issue #16 Implementation Decisions, "Backups" bullet - committed
   `deploy/cron/backup.sh` (pg_dump of the single instance, daily) + cron config
   on the staging VM; the monthly restore drill is Phase 14. (~1K tokens)
3. `docs/roadmap/implementation-roadmap.md` §2.1 - the `NFR-004` floor:
   "backup scaffolding job exists" in the release readiness criteria; §2.14
   adds the monthly restore drill (`GAP-012`). (~1K tokens)
4. `deploy/edge/` (Caddyfile + README + `check_edge_config.py` +
   `test_edge_config.py`) - the sibling T8a scaffold's pattern to mirror:
   committed scaffold under `deploy/<area>/`, deterministic stdlib-only lint
   gate, fixture unit tests, wired as `npm run check:*` + a pre-commit local
   always-run hook, plus the CI job for the thing the lint cannot run.
   (~1.5K tokens)
5. `.pre-commit-config.yaml`, `package.json` scripts, `.github/workflows/ci.yml`
   - the three wiring points. (~0.5K tokens)

## Do NOT read

- `docs/archive/`, `phase0/`, backend module packages, `bus/`, `app/`, frontend
  code, `docs/standards/*`.

## Baseline verify (must pass before the first edit)

- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run lint` (runs the new backup hook)
- `npm run check:backup`
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_backup_config.py -q`
- CI `backup-smoke` job: runs `deploy/cron/backup.sh` against a throwaway
  Postgres service container, seeds a row, and `pg_restore`s the dump into a
  second database to prove it restores.

## Handoff notes

- `deploy/cron/` is created by this ticket; `deploy/edge/` (T8a, #31) stays
  separate.
- `pg_dump`/a cron daemon are unavailable locally and in the lint pass, so the
  committed contract is enforced by a deterministic lint gate; the _real_ dump
  is exercised by the `backup-smoke` CI job (apt-installed `postgresql-client`
  on the runner against the `postgres:16-alpine` service container).
- Crontab does not interpolate variables into the command line - the cron file
  commits a literal `/opt/caresetu` checkout path and the README says to adjust
  it if the VM checkout differs.
- No secrets committed: `backup.sh` reads `PGHOST`/`PGPORT`/`PGDATABASE`/
  `PGUSER`/`PGPASSWORD`/`BACKUP_DIR` from the environment; the gate rejects a
  literal `PGPASSWORD=` or `--password=`.
- Backups are PHI and must be encrypted at rest (`security-phii-standards.md`
  §1): `backup.sh` pipes `pg_dump` through `openssl enc` and refuses to run
  without `BACKUP_PASSPHRASE`; the gate enforces both. The `backup-smoke` CI
  job decrypts the dump before the restore check.
- `tests/unit` resolves `from scripts.<module> import ...` because
  `apps/backend/pyproject.toml` sets `pythonpath = [".", "../.."]`.
