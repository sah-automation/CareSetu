# Coding Standards

**Scope:** How every line of CareSetu code is written and organized.
**Upstream:** `docs/prd/project-prd.md` (NFRs), `docs/architecture/internal-modules.md` (module boundaries), `docs/roadmap/implementation-roadmap.md` (phase order).

---

## 1. Language, Runtime & Framework Lock

- **Backend:** Python 3.11+ (asyncio), FastAPI, Pydantic v2, SQLAlchemy 2.0 (async only).
- **Frontend:** Next.js / React, one codebase with role-scoped route groups (Patient / Partner / Operator).
- **No paid proprietary frameworks** — `NFR-001`. Everything used must be OSS/free-tier.
- If a new dependency is needed, it must be justified against the cost floor before adding.

## 2. Module Structure (per `MOD-xxx`)

Every module follows hexagonal layout — pure domain core + adapters:

```
<module>/
  domain/        # pure logic, state machines, no I/O, no FastAPI
  adapters/      # routers, event handlers, external-provider clients
  schema/        # SQLAlchemy models for THIS module's schema only
  facade.py      # typed public API (sync) — the only legal import target
  outbox.py      # transactional outbox writer
```

- No module imports another module's `domain`/`schema`/adapters directly. Cross-module access is **only** via `facade.py` (sync) or the event bus (async).
- **No cross-schema SQL. No foreign keys across schemas.** Each module owns exactly one of the 11 private schemas.
- Namespace prefixes: every model/table carries the module id (e.g. `consent_consents`, `care_prescriptions`).

## 3. Typing & Naming

- **Type everything.** No `Any`, no untyped dicts crossing module boundaries; use Pydantic v2 schemas/DTOs.
- Type hints on all function signatures; return annotations mandatory.
- Naming: `snake_case` (python), `PascalCase` (classes/models), `CONSTANT_CASE` (env/config). Event names are `domain.action` (see event registry §4.2 of the whitebox doc).
- Exceptions named with a domain `Error` suffix, one per module.

## 4. State Machines

- All business state transitions are explicit state machines (see module specs §3). No `if/else` sprawl over statuses.
- A state change writes its event to the module's outbox **in the same DB transaction** as the change.
- Validate pre-conditions (e.g. no prescription without doctor approval — `REQ-023`) in the domain core, never in the router.

## 5. Migrations & Schema

- One migration harness from `PHASE-1`; every phase adds a versioned, idempotent schema delta.
- Migrations are additive (new tables/columns), never destructive; destructive changes go through a written ADR.
- Append-only tables (`audit`) are protected at DB level (no UPDATE/DELETE grants) + hash-chained.

## 6. Tests

- Unit: domain core (pure, no I/O). Integration: facade + schema against a test Postgres. Contract: external providers mocked.
- Every state machine has a test per transition (happy + edge), using the PRD's BDD scenarios.
- Every outbox consumer has an idempotency test (replay of same `event_id`).
- PRD acceptance criteria are the source of test names; trace with the `FEAT-xxx` id in the test docstring.

**Local test harness** (see `D:\Dev\tools\README.md` for the global tooling):

| Layer          | Tool                                                                        | Command (repo root)                                               |
| :------------- | :-------------------------------------------------------------------------- | :---------------------------------------------------------------- |
| Backend unit   | `pytest` + `pytest-asyncio` + `pytest-cov` (`tests/unit`)                   | `npm run test:unit:backend`                                       |
| Frontend unit  | `vitest` + Testing Library (`apps/frontend/src`)                            | `npm run test:unit:frontend`                                      |
| Integration    | `pytest` vs a native PostgreSQL (`tests/integration`, skips if unreachable) | `npm run test:integration`                                        |
| E2E            | `Playwright` (`tests/e2e`, browsers shared from the global cache)           | `npm run test:e2e`                                                |
| Lint           | `pre-commit` (ruff lint+format, prettier, whitespace)                       | `npm run lint` / `npm run lint:backend` / `npm run lint:frontend` |
| Typecheck      | `mypy --strict` (backend), `tsc --noEmit` (frontend)                        | `npm run typecheck`                                               |
| Migration gate | `alembic` single-head check + cross-schema-FK scan                          | `npm run migration-check`                                         |
| Security scan  | `gitleaks` (secret), `bandit` (static), `pip-audit` (deps)                  | `npm run scan`                                                    |

- **pre-commit is the gate on every commit** — gitleaks, ruff, bandit, prettier, whitespace run there; CI runs the same plus typecheck/unit/integration/migration-check/e2e (`.github/workflows/ci.yml`).
- Integration tests need a local native PostgreSQL (no Docker); the suite connects to `TEST_DATABASE_URL`/`DATABASE_URL` and skips cleanly when the DB is unreachable (setup: `tests/integration/README.md`).
- `apps/backend/pyproject.toml` holds all backend tool config; the backend venv lives at `D:\Dev\venvs\backend-env` (uv sync via `UV_PROJECT_ENVIRONMENT`).

## 7. Data Durability

- Backups ≥ daily (RPO ≤ 24h) — `NFR-004`; restore drill validated at least monthly.
- All PHI writes go to the object store or the owning module's schema; media refs only in SQL.

## 8. Readability & Debuggability

Code must be easy to understand, navigate, and debug **by a human**, without an agent.

- **Traceability by construction:** a human can navigate PRD feature → module → file. Every module and router carries its `MOD-xxx` / `FEAT-xxx` ids in a header comment, matching the whitebox doc.
- **Small, single-purpose functions:** one responsibility per function, shallow nesting, no long `if/else` chains (state machines replace status branching — §4).
- **Name for the reader:** names carry intent; avoid abbreviations, magic numbers, and terse one-liners. Complex logic gets a short docstring explaining _why_, not just _what_.
- **Debuggability:** a failure must be reproducible from `trace_id` + structured logs alone (see `error-handling-observability.md`). No silent swallowing of errors; expected outcomes are typed results, not bare `pass`/`except`.
- **Local reasoning:** keep modules and files small enough that the whole flow fits one screen where possible; split large facades along their state machines.
