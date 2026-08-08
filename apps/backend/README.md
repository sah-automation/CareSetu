# CareSetu backend — FastAPI modular monolith

Skeleton package for the `PHASE-1` foundation (see `docs/roadmap/implementation-roadmap.md`). Owns the single PostgreSQL schema-migration harness (`alembic/`).

## Local commands (run from repo root)

```sh
npm run test:unit:backend    # pytest — tests/unit
npm run test:integration     # pytest — tests/integration (needs a local native Postgres; skips if unreachable)
npm run lint:backend         # ruff check
npm run typecheck:backend    # mypy strict
npm run scan:backend         # bandit
npm run migration-check      # alembic single-head gate
```
