# Brief - PHASE-1 T7b Gateway middleware stubs

**Ticket:** #29 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The gateway seam: `jwt_verify` and `rate_limit` ASGI middleware stubs (disabled by default) exposing a real `Principal` shape; middleware order is the contract Phase 2 fills in. Unit tests prove a stub principal is attached from a test header and that disabled stubs pass through.

Acceptance criteria:

- [ ] `jwt_verify` stub attaches a typed `Principal` from a test header (accept-all logic)
- [ ] `rate_limit` stub exists, disabled by default
- [ ] Middleware is wired in front of routes; disabled -> pass-through
- [ ] Unit tests cover both stubs

## Read-list (in order)

1. `CONTEXT.md` glossary - `gateway` vs `edge` are distinct terms; gateway is the in-app FastAPI middleware stack, edge is the TLS reverse proxy (~1K).
2. Issue #16 Implementation Decisions - "Gateway / edge" decision: `app/gateway/` ASGI middleware stack, both stubs disabled by default, middleware order + `Principal` shape are the Phase 2 contract (~2K).
3. `apps/backend/app/main.py` + `apps/backend/app/config.py` - the T7a shell: `create_app` factory, `Settings` frozen dataclass, `app.state.settings` pattern the gateway reads config from (~1K).
4. `tests/unit/test_app_shell.py` - the T7a test conventions (TestClient, monkeypatch env) to mirror (~0.5K).
5. `docs/standards/coding-standards.md` §3 - type everything, Pydantic v2 DTOs, no `Any` (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`, the bus/dispatcher module, migration harness.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck:backend`

Verified green 2026-08-11 (240 passed; mypy clean).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (new gateway stub tests pass)
- `npm run typecheck:backend`
- `npm run lint` (pre-commit gate on commit)

## Handoff notes

- From #28: `create_app(settings)` resolves `Settings` and stores it on `app.state.settings`; the gateway reads the same resolved config from the app instance rather than re-reading the environment.
- Env parsing is plain `os.environ.get` over a frozen dataclass - no new dependencies (cost floor `NFR-001`).
- Both stubs disabled by default; enable flags live in `Settings`. Wiring must be present so Phase 2 only flips the flags.
- The `Principal` shape is the durable contract: typed Pydantic model carrying caller identity (subject + roles) for the Phase 2 RBAC edge checks.
