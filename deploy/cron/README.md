# CareSetu daily backup job (PHASE-1 T8b, #32)

`deploy/cron/` is the **backup scaffolding** that establishes the `NFR-004`
durability floor: a daily, at-rest-encrypted `pg_dump` of the single CareSetu
PostgreSQL instance, scheduled by cron on the staging VM. It is structure with
no business logic - the monthly restore-validation drill is PHASE-14 (roadmap
§2.14, `GAP-012`).

| File                    | Purpose                                                                                |
| :---------------------- | :------------------------------------------------------------------------------------- |
| `backup.sh`             | The backup script: encrypted `pg_dump -Fc` to `BACKUP_DIR`, fail-loud, retention prune |
| `caresetu-backup.cron`  | Crontab fragment scheduling `backup.sh` every day at 01:30                             |
| `README.md` (this file) | What, how to install, and the RPO contract                                             |

## Recovery point objective

The job runs **daily**, so the maximum data-loss window is one day:

- **RPO <= 24 h** - the `NFR-004` durability floor (roadmap §2.1 release
  readiness, §2.14 §6 `NFR-004` row). "Daily backups + validated monthly
  restore drill before launch".

A dump older than 24 h at recovery time means the cadence broke - the CI smoke
test keeps the _script_ honest; the cron entry keeps the _schedule_ honest, and
the monthly restore drill (PHASE-14) proves the dumps are restorable.

## How the script works

`backup.sh` reads every parameter from the environment (nothing is committed):

| Variable                | Default                 | Purpose                                      |
| :---------------------- | :---------------------- | :------------------------------------------- |
| `PGHOST`                | `localhost`             | Postgres host                                |
| `PGPORT`                | `5432`                  | Postgres port                                |
| `PGDATABASE`            | `caresetu`              | Database to dump                             |
| `PGUSER`                | `caresetu`              | Connection role                              |
| `PGPASSWORD`            | _(empty)_               | Password - via env or `.pgpass`, never here  |
| `BACKUP_PASSPHRASE`     | _(required)_            | Encryption passphrase - refuses to run unset |
| `BACKUP_DIR`            | `/var/backups/caresetu` | Where dumps land                             |
| `BACKUP_RETENTION_DAYS` | `14`                    | Dumps older than this are pruned             |

It `set -euo pipefail`, dumps in PostgreSQL **custom format** (`pg_dump -Fc`),
pipes the dump through **`openssl enc` (AES-256-CBC, PBKDF2, salted)** so the
backup is encrypted at rest, refuses to exit 0 on an empty dump, and prunes
`BACKUP_RETENTION_DAYS`-old dumps so the job cannot fill the disk.

At-rest encryption of backups is a top-level rule
(`docs/standards/security-phii-standards.md` §1) - these dumps carry PHI.
`BACKUP_PASSPHRASE` therefore has no default: the script exits non-zero rather
than write a plaintext dump. The passphrase lives in the VM environment /
secret manager, never in this repo.

To **restore** a dump (until the Phase-14 drill automates it) - note that
`-iter 200000` must match the encrypt side, because some `openssl` builds do
not read the iteration count from the file header:

```sh
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE \
  -in caresetu-caresetu-20260901T013000Z.enc -out restore.dump
pg_restore -d caresetu restore.dump
```

## Installing on the staging VM

The VM checkout lives at `/opt/caresetu` (the edge Caddyfile is run from the
same checkout); adjust the literal path in the cron file if it differs.

```sh
# once: install the daily schedule and create a writable log dir
crontab deploy/cron/caresetu-backup.cron
sudo mkdir -p /var/log/caresetu
sudo chown "$USER":"$USER" /var/log/caresetu
```

`crontab deploy/cron/caresetu-backup.cron` replaces the current user's crontab;
pipe instead (`crontab -l | cat - deploy/cron/caresetu-backup.cron | crontab -`)
to append when other jobs exist.

The crontab user must own the log dir (the `chown` above), because the cron
line appends to `/var/log/caresetu/backup.log` - a root-owned dir would make
the job fail silently every night. Then add a connection env block above the
schedule line so `backup.sh` does not prompt and does not refuse:

```cron
PGHOST=localhost
PGPORT=5432
PGDATABASE=caresetu
PGUSER=caresetu
PGPASSWORD=<from the secret manager>
BACKUP_PASSPHRASE=<from the secret manager>

30 1 * * * /opt/caresetu/deploy/cron/backup.sh >> /var/log/caresetu/backup.log 2>&1
```

## Validation

A deterministic lint gate asserts the committed scaffold's contract - files
exist, `backup.sh` is fail-loud, secret-free and encrypts at rest, the cron
entry is daily and calls `backup.sh`, and this README documents the RPO floor:

```sh
npm run check:backup
```

It runs in `npm run lint` (pre-commit) and in CI. The **CI smoke test**
(`.github/workflows/ci.yml` → `backup-smoke` job) actually executes
`deploy/cron/backup.sh` against a throwaway Postgres service container, seeds
a row, and decrypts + `pg_restore`s the dump into a second database to prove
the dump is restorable - the smoke that keeps the committed script working.
