# Brief - FIX-6 Fix latency test to assert p95 < 50ms

**Ticket:** #226 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~1K tokens (budget 10K) - within budget

## Scope

Latency NFR is actually verified: test asserts `p95 < 50` instead of `p50 < 100`.

**Acceptance criteria:**

- `test_p95_latency_under_50ms` in `tests/integration/test_consent_check_gate.py` asserts `p95 < 50` (not `p50 < 100`)
- Test still runs 100 iterations with warmup
- `npm run test:integration` passes (if DB available)

## Read-list (in order)

1. `tests/integration/test_consent_check_gate.py:284-323` - the latency test (~410 tokens total file, read lines 284-323)

**Total:** ~40 tokens of targeted reading, well within budget.

## Do NOT read

- Facade code, route code, frontend code
- Other integration tests
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verify current state (integration needs DB)

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` passes (if DB available)
- `grep -n "p50 < 100" tests/integration/test_consent_check_gate.py` returns no matches
- `grep -n "p95 < 50" tests/integration/test_consent_check_gate.py` returns a match

## Handoff notes

- Line 321: `assert p50 < 100, f"p50 latency {p50:.2f}ms too high"` - change to `assert p95 < 50, f"p95 latency {p95:.2f}ms exceeds 50ms NFR"`
- Line 316: `p95 = latencies[int(len(latencies) * 0.95)]` - already calculated, just not asserted
- The test comment on line 289 says "check median < 50ms as a proxy" - update comment to reflect the actual assertion
- Consider: should we keep the p50 assertion as a secondary check? The spec only requires p95 < 50.
