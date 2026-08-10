# Brief - PHASE-1 T7a FastAPI app shell + health route

**Ticket:** #28 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

The FastAPI app shell: app entrypoint, shared config (DB URL, env-driven), and a health route. A boot test proves the app serves `/health` with 200.

Acceptance criteria:

- [ ] FastAPI app boots from the shared config
- [ ] `/health` returns 200
- [ ] Boot test passes (httpx/TestClient against the app)
- [ ] No business routes (Phase 2+)

## Read-list (in order)

1. `docs/standards/coding-standards.md` §2 - app package layout (~0.5K).
2. The backend dependency manifest (`apps/backend`) - the declared stack: FastAPI, uvicorn, pydantic, SQLAlchemy async, asyncpg (~0.5K).
3. Issue #16 Implementation Decisions - app shell + gateway wiring (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck:backend`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (boot test passes)

## Handoff notes

- Config is env-driven (DB URL at minimum) and shared - the worker (#30) and gateway (#29) build on it.
- No business routes in this ticket.
- Baselines verified green on 2026-08-10.
