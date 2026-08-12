# Brief - PHASE-2 T7 Refresh session rotation

**Ticket:** #58 · **Parent:** #51 · **Refreshed:** 2026-08-12
**Reading surface:** ~3K tokens (execution budget 120K incl. initial read + tests) - within budget

## Scope

`refresh_session` exchanges an opaque refresh token (stored server-side in the module's `sessions` table) for a fresh access JWT, sliding the refresh lifetime (~30 days) and rotating the refresh token on every use. The refresh path is independent of SMS so an OTP outage never bricks an existing session (`NFR-004`).

Acceptance criteria:

- [ ] Refresh tokens opaque, server-side in `sessions`, ~30-day sliding lifetime
- [ ] `refresh_session` returns a fresh access JWT and rotates the refresh token on every use (old one unusable after rotation)
- [ ] Expired, revoked, unknown refresh tokens rejected
- [ ] Refresh requires no SMS interaction
- [ ] Unit tests cover refresh success, rotation, reuse of an already-rotated token, expiry

## Read-list (in order)

1. #51 Implementation Decisions §2.5 + roadmap §2.2 dependency note - refresh independent of SMS (`NFR-004`) (~1K).
2. The `sessions` table from T1 + access JWT mechanics from T6 (~0.5K).
3. `docs/standards/security-phii-standards.md` - token storage/rotation (~0.5K).
4. `docs/architecture/internal-modules.md` §3.1 MOD-001 NFR line (~0.5K).

## Do NOT read

- Frontend, dispatcher internals, `docs/archive/`, `phase0/`, OTP challenge logic, gateway middleware (T8).

## Baseline verify

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck:backend`

## Done-verify

- `npm run test:unit:backend` (refresh/rotation tests)
- `npm run test:integration` (session table assertions)
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Rotation means the exchanged refresh token is immediately invalid - a reuse attempt is a signal worth an audit event (`patient.auth_failed` per the event list).
- Sliding lifetime: each refresh pushes the expiry forward up to the ~30-day cap.
