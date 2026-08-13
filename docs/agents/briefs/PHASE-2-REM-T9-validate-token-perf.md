# Brief - PHASE-2-REM T9 validate_token p95 < 100 ms is measured

**Ticket:** #79 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~7K tokens (budget ~10K) - within budget

## Scope

The release-readiness latency criterion for `validate_token` is asserted by a benchmark test, not a comment. The test exercises the stateless validation path over a fixed batch and asserts the p95 stays under the 100 ms budget (MOD-001 NFR), with a generous, non-flaky bound for CI.

Acceptance criteria:

- [ ] A benchmark unit test asserts `validate_token` p95 < 100 ms over a fixed batch (no DB round-trip)
- [ ] The test is non-flaky (generous bound, no timing on a cold path)
- [ ] Suite passes in CI

## Read-list (in order, token estimates)

1. `IamFacade.validate_token` + the `ValidatedAccessToken` result shape - the stateless hot path (signature + expiry only, key + clock, no DB round-trip) and the shape the benchmark measures (~0.5K).
2. `jwt.verify_token` in the iam domain - the pure HS256 signature + expiry logic the facade delegates to; claim typing, `exp` window, fail-closed empty key (~2.5K).
3. `JWTVerifyMiddleware` gateway consumer - where `validate_token` runs per request at the edge; the p95 budget applies on this call path, and the token rejection taxonomy feeds it (~1.3K).
4. Existing token unit tests (`test_iam_session`) - conventions: `MutableClock`, `issue_token` helper, facade built with an engine at an unreachable host so any DB touch fails the test (the no-DB-round-trip pattern the benchmark must reuse) (~1.5K).
5. MOD-001 §3.1 latency SLA line - `validate_token` p95 < 100 ms at the edge (the budget the test asserts) (~0.7K).
6. Roadmap §2.2 release-readiness criteria - the criterion this benchmark pins, referenced in the test docstring (~0.4K).

## Do NOT read

- Anything outside the validation path: outbox/event publish, SMS adapter, OTP/lockout/cooldown logic, `issue_session` / `refresh_session` DB paths, identity or session tables, migration files, frontend, `phase0/`, `docs/archive/`.
- Optimization work: the measurement harness comes first; do not redesign or micro-tune the path.

## Baseline verify

- `npm run test:unit:backend` (from ticket; already verified green centrally: 494 passed on 2026-08-13)

## Done-verify

- `npm run test:unit:backend` (benchmark test passes in suite)

## Handoff notes

- Parent #75 finding: `validate_token` p95 is unmeasured - the criterion exists only as comments/docstrings. This ticket is measurement-first: build the harness, assert the budget, no premature optimization.
- Confirmed by grep: no existing benchmark harness in the test tree (no pytest-benchmark, no `time.perf_counter` usage). The benchmark is a plain unit test that times a fixed batch of `validate_token` calls and asserts p95 < 100 ms.
- Non-flakiness: generous bound, and no timing on a cold path - warm up (a few unmeasured calls) before the timed batch so first-call compilation/cache warm-up is excluded; the bound is far below the 100 ms budget for CI variance.
- The unreachable-host engine convention from the existing unit tests doubles as the no-DB-round-trip proof: `validate_token` uses only the signing key and the clock, so the benchmark must drive it through the same seam without touching PostgreSQL.
- Signing and timing a batch needs a fixed signing key and a fixed clock (reuse the `MutableClock` convention), plus tokens minted by `issue_token` for the same key.
