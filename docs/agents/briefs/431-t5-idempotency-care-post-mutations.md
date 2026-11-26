# Brief - T5 PHASE-8 review-close: Idempotency-Key on the seven care POST mutations

**Ticket:** #431 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~6.4K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T5. All seven care POST mutations (consult-complete, doctor input, rx draft, rx revision, approve, reject, close) honour the shared Idempotency-Key contract served by the gateway idempotency store, following the IAM/partner route pattern. Same key and path replays the stored first response without re-executing; a different key or missing key executes normally. The state machines keep no-op and illegal transitions safe regardless of replay, so an idempotent gate is belt-and-braces.

Acceptance criteria (verbatim from ticket):

- [ ] Each of the seven care POST routes is wrapped in the shared gateway idempotency helper (same pattern as IAM/partner routes)
- [ ] Replay of the same key + path returns the stored first response without re-executing - tested on at least approve, consult-complete, and close
- [ ] A differing key re-executes; a missing key passes through with no store interaction
- [ ] Route-level tests mirror the IAM/partner idempotency-replay prior art
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

**Blocked by:** #430 (T4) - facade call signatures are the idempotency wrapper's contract; kept serial for minimal route churn.

## Read-list (in order)

1. `app/gateway/idempotency.py` (full) - `IdempotencyStore` + `run_idempotent(request, call)`; the header contract (blank/missing = pass-through), path-namespaced key, store lookup on `request.app.state.idempotency_store`, only-completed-calls-cached. (~1.4K)
2. One IAM usage pattern, e.g. `modules/iam/adapters/routes.py` `register_patient`/`invite_operator` (~L177 / ~L388) - the `return await run_idempotent(request, lambda: facade.method(...))` shape to copy. (~0.6K)
3. `care/adapters/routes.py` - all seven care POST handlers: consult-complete (~L178), doctor-input (~L244), rx/draft (~L272), rx/{id}/revision (~L300), rx/{id}/approve (~L328), rx/{id}/reject (~L357), close (T3's new route). Wrap each mutating call; GETs (`get_case`, `list_open_cases`, approved-read) stay unwrapped. (~2.3K)
4. Prior art tests: `tests/unit/test_idempotency_store.py` (store semantics) and an IAM replay test such as `tests/unit/test_iam_register_route.py` - the `_client_with_store` fixture wiring (`app.state.idempotency_store`), blank-key pass-through, TTL-expired re-executes, failed-mutation-not-cached assertions. (~1.8K)
5. `docs/standards/api-standards.md` §5 Idempotency & Retries - the normative contract. (~0.3K)

## Do NOT read

- Facade internals beyond method signatures (the wrapper never changes facade logic), intake/partner internals, the state machines, the frontend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - route-level idempotency-replay tests on approve, consult-complete, and close (replay returns first response without re-executing; differing key re-executes; missing key passes through)
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- The store is in-process on app state (`app/main.py` L312, `IdempotencyStore()`), TTL derived from `OTP_TTL_SECONDS`; restart loses entries - that at-most-once degrade is accepted by design, not something this ticket fixes.
- `run_idempotent` namespaces keys by request path, so the same key on a different path executes normally - the "same key + path" wording in the acceptance criteria is exactly that behaviour.
- The seven routes are the seven **POST mutating** handlers; the approved-prescription read and case GETs are NOT idempotency-wrapped (GET semantics, read-only).
- Do not let the wrapper change facade behaviour: a replay returns the _stored first response_, so the facade must have already run. The state machines' no-op/illegal-transition safety is what makes a re-executed bad retry harmless - belt-and-braces per the spec.
- The store app-state wiring pattern for tests is `app.state.idempotency_store = IdempotencyStore()` in the fixture (see IAM route tests); reuse the same fixture style rather than inventing a new one.
- #430 (T4) must land first so the wrapped facade call signatures are final; check #430's closing comments for the final `close_case_without_rx` signature before wrapping it.
