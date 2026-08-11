# Brief - 31 PHASE-1 T8a: Edge reverse-proxy scaffold

**Ticket:** #31 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The edge seam: a reverse-proxy config (Caddy/nginx) for TLS termination on the
staging VM, committed under `deploy/edge/`, validated to parse. The deployment
boundary exists before real traffic.

Acceptance criteria (from #31; all delivered):

- [x] Edge config committed under `deploy/edge/`
- [x] Config validates (syntax-check via the proxy tool if available, else a lint pass)
- [x] Documented as the staging TLS boundary (edge != in-app gateway)

## Read-list (in order)

1. `CONTEXT.md` glossary - `edge` vs `gateway` (distinct terms; lines ~102-108). Edge = reverse proxy at the VM perimeter terminating TLS; gateway = in-app FastAPI middleware. No other glossary terms matter here. (~1K tokens)
2. Issue #16 Implementation Decisions, "Gateway / edge" bullet - edge is the separate deployment boundary: `deploy/edge/` reverse-proxy scaffold (Caddy/nginx) doing TLS termination for the staging VM. (~1K tokens)
3. `docs/roadmap/implementation-roadmap.md` §2.1 item 4 - "staging VM with TLS termination (Caddy/nginx) behind the edge". (~0.5K tokens)
4. `apps/backend/scripts/check_module_boundaries.py` + `tests/unit/test_boundary_checker.py` - the repo's validator-with-tests pattern to mirror: stdlib-only Python gate, `(Violation,)` dataclass tuple, `main()` exiting 1 on violations, wired into `package.json` as an `npm run check:*` script and into `.pre-commit-config.yaml` as a local always-run hook. (~3K tokens)
5. `.pre-commit-config.yaml` + `package.json` scripts - the two wiring points to extend. (~0.5K tokens)

## Do NOT read

- `docs/archive/`, `phase0/`, backend module packages, `bus/`, `app/`, frontend code, `docs/standards/*` (their loose "edge" phrasing predates the glossary and is not this ticket's reconciliation job).

## Baseline verify (must pass before the first edit)

- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run lint` (runs the new edge hook)
- `npm run check:edge`
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_edge_config.py -q`

## Handoff notes

- `deploy/` does not exist yet - this ticket creates it; `deploy/cron/backup.sh` lands in a later T9/T10 ticket, keep `deploy/edge/` separate.
- No `caddy`/`nginx` binary is available locally or in CI, so "config validates" = a deterministic lint pass (`check_edge_config.py`), not a binary syntax check.
- Backend port 8000 (uvicorn default), frontend port 3000 (Next.js default); neither is pinned elsewhere in the repo, the Caddyfile is what fixes them for staging.
- Backend app shell/gateway stubs already exist (`apps/backend/app/main.py`); the edge is deliberately independent of them.
- `tests/unit` resolves `from scripts.<module> import ...` because `apps/backend/pyproject.toml` sets `pythonpath = [".", "../.."]`.
