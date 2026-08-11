# Integration tests - facade + schema vs a real Postgres

Test module facades (`facade.py`) and schema against a live PostgreSQL. Contract tests mock external providers.

- No Docker required: the suite connects to the native Postgres at `TEST_DATABASE_URL` (falls back to `DATABASE_URL`, then `postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu`) and **skips cleanly if it is unreachable**.
- Run with `npm run test:integration` from the repo root. In CI the `integration` job provides Postgres as a GitHub-hosted service and sets `DATABASE_URL`.
- Every outbox consumer has an idempotency test (replay of the same `event_id`).

## Local database setup (once)

Install the native PostgreSQL service (no containers) and bootstrap the CareSetu role/database:

```sh
winget install PostgreSQL.PostgreSQL.16
```

Then, as the `postgres` superuser:

```sql
CREATE ROLE caresetu WITH LOGIN PASSWORD 'caresetu';
CREATE DATABASE caresetu OWNER caresetu;
```

`TEST_DATABASE_URL` can override the default connection string per run, e.g.:

```sh
$env:TEST_DATABASE_URL = "postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu"
```

Populated from `PHASE-1` onward.
