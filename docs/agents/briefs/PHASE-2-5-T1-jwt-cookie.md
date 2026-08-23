# Brief - T1 Backend - Set JWT cookie on session issuance

**Ticket:** #147 · **Parent:** #146 Phase 2.5 · **Refreshed:** 2026-08-17
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The `POST /v1/auth/session` and `POST /v1/auth/refresh` backend endpoints set an httpOnly cookie containing the JWT in addition to returning it in the response body. The response body is unchanged - existing API clients (frontend auth wizard) continue working without modification. This is the foundation for Next.js middleware route protection, which reads the cookie on every request to check auth state.

Acceptance criteria (verbatim):

- `POST /v1/auth/session` response includes `Set-Cookie` header with JWT value
- Cookie attributes: `httpOnly=true`, `secure=true` (when not dev), `sameSite=strict`, `path=/`, `maxAge` matching JWT TTL
- `POST /v1/auth/refresh` response also sets the cookie (with rotated JWT)
- Response body remains unchanged (JWT + refresh_token + metadata in JSON)
- Existing `PatientAuthWizard` login flow continues to work (reads JWT from response body, stores in localStorage)
- Backend tests pass: session endpoint test verifies Set-Cookie header presence and attributes

## Read-list (in order)

1. `modules/iam/adapters/routes.py` (289 lines) - the `POST /v1/auth/session` and `POST /v1/auth/refresh` endpoints; understand current response shape and how they return JWT (~3.5K tokens)
2. `modules/iam/domain/jwt.py` (192 lines) - JWT signing logic, TTL constant, token claims structure; the cookie maxAge must match the JWT TTL defined here (~2.5K tokens)
3. `modules/iam/facade.py` (1159 lines, read only `issue_session` and `refresh_session` methods) - the return types from session issuance and refresh; the cookie must be set on the same responses (~2K tokens)
4. `app/main.py` - the FastAPI middleware stack; understand where cookie-setting fits in the response pipeline (~1K tokens)

## Do NOT read

- Frontend code (auth wizard, session.ts, api.ts), other backend modules, PRD, roadmap, database schemas, migration scripts.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (currently 642 passed)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - existing + new session cookie tests pass
- `npm run typecheck:backend` - clean
- Manual verification: session endpoint response includes `Set-Cookie` header with correct attributes

## Handoff notes

- The `refresh_session` facade method exists but has no HTTP route yet (internal rotation path only, per `PHASE-2 REM T10 #82`). You need to add a `POST /v1/auth/refresh` route or extend the existing session route to handle refresh - check routes.py for current coverage.
- Cookie name should be `caresetu.access_jwt` or similar (coordinate with frontend T5 middleware which will read this cookie).
- `secure=true` only in non-dev environments; use the existing `Settings` env detection (check `app/config.py` for dev/test/production detection).
- The response body must remain byte-for-byte identical - the `Set-Cookie` header is purely additive.
- Test approach: use `httpx` test client to hit the session endpoint and assert `set-cookie` header presence + attribute values; test both session and refresh paths.
