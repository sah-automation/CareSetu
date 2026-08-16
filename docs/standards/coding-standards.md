# Coding Standards

**Scope:** How every line of CareSetu code is written and organized.
**Upstream:** `docs/prd/project-prd.md` (NFRs), `docs/architecture/internal-modules.md` (module boundaries), `docs/roadmap/implementation-roadmap.md` (phase order).

---

## 1. Language, Runtime & Framework Lock

- **Backend:** Python 3.11+ (asyncio), FastAPI, Pydantic v2, SQLAlchemy 2.0 (async only).
- **Frontend:** Next.js / React, one codebase with role-scoped route groups (Patient / Partner / Operator).
- **No paid proprietary frameworks** - `NFR-001`. Everything used must be OSS/free-tier.
- If a new dependency is needed, it must be justified against the cost floor before adding.

## 2. Module Structure (per `MOD-xxx`)

Every module follows hexagonal layout - pure domain core + adapters:

```
<module>/
  domain/        # pure logic, state machines, no I/O, no FastAPI
  adapters/      # routers, event handlers, external-provider clients
  schema/        # SQLAlchemy models for THIS module's schema only
  facade.py      # typed public API (sync) - the only legal import target
  outbox.py      # transactional outbox writer
```

- No module imports another module's `domain`/`schema`/adapters directly. Cross-module access is **only** via `facade.py` (sync) or the event bus (async).
- **No cross-schema SQL. No foreign keys across schemas.** Each module owns exactly one of the 11 private schemas.
- Namespace prefixes: every model/table carries the module id (e.g. `consent_consents`, `care_prescriptions`).

## 3. Typing & Naming

- **Type everything.** No `Any`, no untyped dicts crossing module boundaries; use Pydantic v2 schemas/DTOs.
- Type hints on all function signatures; return annotations mandatory.
- Naming: `snake_case` (python), `PascalCase` (classes/models), `CONSTANT_CASE` (env/config). Event names are `domain.action` (see event registry §4.2 of the whitebox doc). Configuration & environment rules follow §9.
- Exceptions named with a domain `Error` suffix, one per module.

## 4. State Machines

- All business state transitions are explicit state machines (see module specs §3). No `if/else` sprawl over statuses.
- A state change writes its event to the module's outbox **in the same DB transaction** as the change.
- Validate pre-conditions (e.g. no prescription without doctor approval - `REQ-023`) in the domain core, never in the router.

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

- **pre-commit is the gate on every commit** - gitleaks, ruff, bandit, prettier, whitespace run there; CI runs the same plus typecheck/unit/integration/migration-check/e2e (`.github/workflows/ci.yml`).
- Integration tests need a local native PostgreSQL (no Docker); the suite connects to `TEST_DATABASE_URL`/`DATABASE_URL` and skips cleanly when the DB is unreachable (setup: `tests/integration/README.md`).
- `apps/backend/pyproject.toml` holds all backend tool config; the backend venv lives at `D:\Dev\venvs\backend-env` (uv sync via `UV_PROJECT_ENVIRONMENT`).

## 7. Data Durability

- Backups ≥ daily (RPO ≤ 24h) - `NFR-004`; restore drill validated at least monthly.
- All PHI writes go to the object store or the owning module's schema; media refs only in SQL.

## 8. Readability & Debuggability

Code must be easy to understand, navigate, and debug **by a human**, without an agent.

- **Traceability by construction:** a human can navigate PRD feature → module → file. Every module and router carries its `MOD-xxx` / `FEAT-xxx` ids in a header comment, matching the whitebox doc.
- **Small, single-purpose functions:** one responsibility per function, shallow nesting, no long `if/else` chains (state machines replace status branching - §4).
- **Name for the reader:** names carry intent; avoid abbreviations, magic numbers, and terse one-liners. Complex logic gets a short docstring explaining _why_, not just _what_.
- **Debuggability:** a failure must be reproducible from `trace_id` + structured logs alone (see `error-handling-observability.md`). No silent swallowing of errors; expected outcomes are typed results, not bare `pass`/`except`.
- **Local reasoning:** keep modules and files small enough that the whole flow fits one screen where possible; split large facades along their state machines.

## 9. Configuration & Environment

Everything that varies by environment, provider, service, deployment, or scale is **configuration, not code**. Swapping a provider, model, endpoint, or tuning a limit is an environment edit, never a code change. Apply the same rule in every project this codebase touches or informs.

### 9.1 Always configuration - never hardcode

- **Secrets & credentials:** API keys, tokens, passwords, database connection strings, JWT/HMAC signing keys, private URLs. Never in code, committed config, or logs (`security-phii-standards.md`); injected via environment or a secret manager.
- **External service identity:** provider names, model/engine IDs, API base URLs and endpoints, regions, tenants, queue/storage/bucket names.
- **Behavior & limits:** timeouts, retries, backoff and jitter, rate limits, quotas, TTLs, max batch/concurrency sizes, circuit-breaker thresholds, poll intervals.
- **Business & price policy:** pricing tables, FX rates, currency, monthly budgets, per-unit ceilings, feature flags, license tier, demo/test identifiers.
- **Deployment surface:** ports, hosts, domains, CORS origins, cookie/header settings, storage paths, machine/venv paths, environment names, log levels, tool versions.
- **Content & locale:** language codes, region codes, timezones, locale strings, template ids, sandbox/base URLs used by tests.

### 9.2 Hard rules

- A literal value in code that a deployment, provider, scale, or locale change must touch is a defect - move it to configuration.
- **No secrets in git:** never in source, committed `.env`, Dockerfiles, or CI logs. `.env` and `.env.*` are git-ignored; only `.env.example` with non-secret defaults is committed.
- **No silent fallbacks in shipped code:** a missing required env var fails loudly at startup/boot - no hidden localhost or production default behind an unset variable.
- **Single source of truth:** one env-driven settings object per service; never duplicate the same value across files, configs, or languages (frontend and backend must not each re-declare the same TTL).
- **Validate at boot, fail closed:** settings are parsed and validated once at startup; invalid or unsafe combinations are refused (e.g. a demo flag never rides a real provider).
- **Pinned constants are the exception:** a domain threshold stays a constant only when a decision record (ADR) pins it (e.g. `ADR-0001` AMB-006 threshold / WER floor). Everything else is configurable.
- **Tests too:** tests must not silently bind to real network providers or production values; fixed literals are allowed only for deterministic assertions of that literal.

### 9.3 How to apply it

- **Central settings object:** the backend reads the environment through one typed settings dataclass with defaults + validation (pattern: `apps/backend/app/config.py`). Frontend uses `NEXT_PUBLIC_*` build-time variables.
- **Document every variable:** each env var gets a non-secret default and a comment in `.env.example`; real values live in the local `.env` (git-ignored) or the secret manager.
- **Ship config with the feature:** introducing a new endpoint/model/provider/limit adds its env var(s), default, and `.env.example` entry in the same change - not later.
- **Naming:** `CONSTANT_CASE`, prefixed by component/scope (`SMS_`, `GEMINI_`, `NEXT_PUBLIC_`); sensitive names end in `_KEY`/`_SECRET` and carry no committed value.
- **Defaults are dev/CI-friendly, never production:** safe local defaults are fine; production values come from the deployment environment.
- **Precedence:** environment over code default; an explicit CLI flag may override for a one-off local run, but must never be the only way to reach a production path.
