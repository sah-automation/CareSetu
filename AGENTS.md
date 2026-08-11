## Agent skills

### Dependencies & local testing

Global dev tooling (gitleaks, pre-commit, ruff, mypy, bandit, pip-audit, uv, shared Playwright browsers) lives in `D:\Dev\tools\` — setup/upgrade: `D:\Dev\tools\README.md`. Project Python venvs live in `D:\Dev\venvs\` (`backend-env` for this repo). Verify work with the repo harness before declaring done:

- `npm run test:unit:backend|frontend` — pytest / vitest unit suites
- `npm run test:integration` — needs a local native PostgreSQL (skips if unreachable; see `tests/integration/README.md`)
- `npm run test:e2e` — Playwright (browsers from the shared cache)
- `npm run lint` — pre-commit (gitleaks, ruff, bandit, prettier, whitespace)
- `npm run typecheck` — mypy `--strict` (backend) + `tsc --noEmit` (frontend)
- `npm run scan` — gitleaks + bandit + pip-audit
- `npm run migration-check` — alembic single-head gate + cross-schema-FK scan

### Build sessions

Start every session by reading `CONTEXT.md` — it maps the plan/architecture/standards docs and tells you what to read (and skip) for the work at hand. Follow its build-session protocol: current phase → in-scope modules → feature PRD sections → relevant standards. Never read `docs/archive/`; the PRD supersedes it. Cross-reference matrices live in `internal-modules.md` §4/§5 and `implementation-roadmap.md` §3 — read those whole when tracing edges.

### Issue tracker

Issues and PRDs for this repo live as GitHub issues, driven via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels, each equal to its role name: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Standards

Standards set **top-level rules only** and never override the plan — see `docs/standards/README.md`. Read the relevant standard before working in its area; `docs/standards/*`:

- `coding-standards.md` — language/framework lock, module layout, isolation, tests, durability
- `api-standards.md` — REST conventions, error envelope, validation, idempotency, RBAC, rate limiting
- `third-party-integration-standards.md` — EXT-001..004 call discipline, webhook verification, degradation rules
- `error-handling-observability.md` — error taxonomy, structured logging, no-PHI, cost-aware telemetry
- `security-phii-standards.md` — encryption, consent gating, secrets, uploads, audit
- `ai-engineering-standards.md` — product AI pipeline safety/cost AND agent-assisted development conventions
