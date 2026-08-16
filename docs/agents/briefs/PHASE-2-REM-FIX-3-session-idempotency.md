# Brief - FIX 3 Idempotency-Key on POST /v1/auth/session

**Ticket:** #103 · **Parent:** #51 · **Refreshed:** 2026-08-14
**Reading surface:** ~5K tokens (budget ~10K) - within budget

## Scope

`POST /v1/auth/session` joins the other auth mutations in honouring the `Idempotency-Key` header. A replayed key returns the stored `SessionResult` without minting a second session.

Acceptance criteria:

- [ ] `issue_session` runs through the existing `_run_idempotent` wrapper (same pattern as register/verify/resend).
- [ ] Same-key replay calls the facade once and returns the stored result (no second session minted).
- [ ] Idempotency-store TTL expiry re-executes; a no-key request passes through untouched.
- [ ] Module docstring lists session among the idempotent mutations.
- [ ] `npm run test:unit:backend` passes (mirrors the register-route idempotency tests).

## Read-list (in order, token estimates)

1. `modules.iam.adapters.routes` `_run_idempotent` + `issue_session` - the wrapper the session route must adopt (header read, namespaced store key, store-check-then-call-then-put) and the route it currently bypasses (~1.2K).
2. `tests/unit/test_iam_register_route.py` idempotency block - the replay/TTL-expiry/no-key pattern to mirror: `IdempotencyStore` wired on `app.state`, same-key replay asserts facade called once, TTL expiry re-executes, blank key passes through (~1.5K).
3. `tests/unit/test_iam_session_route.py` - the session StubFacade harness to extend with the store wiring and the three new cases (~1.6K).
4. `docs/standards/api-standards.md` §5 Idempotency & Retries - the header contract semantics the wrapper encodes (completed-call-only caching, errors never cached) (~0.4K).

## Do NOT read

- The facade/store implementation (`IdempotencyStore` internals - the in-process TTL-300 s, non-locking store already exists; no change), gateway internals, frontend, `docs/archive/`.

## Baseline verify (from ticket)

- `npm run test:unit:backend` (green this session: 545 passed)
- `npm run typecheck:backend` (green)
- `npm run lint` (green)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck:backend`

## Handoff notes

- Parent #75 finding: `issue_session` is the one auth mutation not wrapped - a lost response retry can mint a second session.
- The change is one line in the route plus tests; no facade/store/config change (the plan is explicit).
- The wrapper already namespaces keys by request path, so a client key used on `/session` cannot collide with `/register`.
