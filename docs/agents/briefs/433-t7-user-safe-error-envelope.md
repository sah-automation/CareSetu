# Brief - T7 PHASE-8 review-close: user-safe error-envelope copy for care validation failures

**Ticket:** #433 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~4.3K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T7. Care validation failures return the platform's standardized error-envelope copy (user-safe fixed message with the `CARE_VALIDATION_ERROR` code) instead of forwarding internal exception phrasing to the client. Full detail stays in server-side structured logs correlated by trace id.

Acceptance criteria (verbatim from ticket):

- [ ] The care validation-failure error handler returns a fixed user-safe envelope message, never `str(exc)` or internal phrasing
- [ ] Internal exception detail appears only in server-side structured logs with the trace id
- [ ] Route tests assert the envelope copy; no internal text reaches the response body
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

**Blocked by:** #431 (T5) - route-error-mapping churn is serialized after the idempotency wrapper lands; this ticket is parallel-able with the facade-split work.

## Read-list (in order)

1. `app/gateway/errors.py` (full) - the `error_response(status, code, message, *, request, ...)` funnel that builds the `{code, message, trace_id, details}` envelope and writes the correlation-log line, plus `register_gateway_error_handlers`. This is the pattern the care handler must follow so internal text never reaches `message`. (~1.5K)
2. `care/adapters/routes.py` `register_error_handlers` (~L413-491) - the current care mappings; find where `CareValidationError` (and the illegal-transition errors) map to 422 `CARE_VALIDATION_ERROR` and whether today's message leaks `str(exc)`. This is the handler to make user-safe. (~0.8K)
3. One comparative module handler, e.g. `modules/intake/adapters/routes.py` error block (~L409-498) - the per-module `log_tag` + fixed-envelope-copy convention with `details` carrying structured payload. (~0.5K)
4. Care route tests' error-envelope assertions (`tests/unit/test_care_routes.py`) - the existing assertions that pin envelope shape and copy; extend them to assert no internal text reaches the response body. (~1.2K)
5. `docs/standards/api-standards.md` §2 Error Envelope - code/message/trace_id contract and "no internal phrasing" rule. (~0.3K)

## Do NOT read

- Idempotency store internals, intake/partner internals, the state machines, the facade bodies, the frontend, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - envelope-copy assertions: fixed user-safe message, no `str(exc)`/internal text in the response body
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- The shared funnel already exists: `error_response` in `app/gateway/errors.py` resolves `trace_id` and writes a `gateway_rejection ... trace_id=...` structured log line. Fix the care validation mapping to pass a fixed message and let full detail live in that server-side log (and any `details` dictionary without internal phrasing).
- The envelope contract (api-standards §2) requires a stable machine-readable code - keep `CARE_VALIDATION_ERROR` (and the derived 404/422/500 care codes already registered); only the message copy is the subject of this ticket.
- Route tests must assert the response body contains the fixed copy and NOT e.g. an exception class name or message; reuse the existing care route test harness (stubbed facade raising the typed care exceptions).
- This ticket is parallel-able with T6a/T6b (facade split) - the handler lives in `adapters/routes.py`, which T6b touches only for the facade-cast changes, not the error block; coordinate to avoid same-file merge friction.
