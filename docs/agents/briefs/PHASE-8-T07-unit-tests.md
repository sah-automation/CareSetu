# Brief - T07 Unit Tests - REQ-023 Gate & Lifecycle

**Ticket:** #423 · **Parent:** #416 · **Refreshed:** 2026-09-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Comprehensive unit tests covering the hard REQ-023 gate, full care lifecycle, and all cross-cutting concerns.

Tests: REQ-023 hard-gate (zero prescriptions without approval + verification declaration), consent-gated history, outbox event payload validation, full lifecycle integration (handshake -> draft -> approve -> issued), rejection-then-retry, close-without-prescription, drafting cap exhaustion, `edited_yn` derivation. Plus repo gate verification.

### Acceptance criteria

- [ ] All REQ-023 hard-gate tests pass
- [ ] Full lifecycle integration tests cover happy, reject, close, cap, and edited_yn paths
- [ ] Outbox envelope payloads validate against Pydantic event models
- [ ] Consent gate is fail-closed
- [ ] All repo gates green: module_layout, event_names, boundaries, migration-check

## Read-list (in order)

1. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - the canonical vocabulary the tests must assert against (`case stage`, `draft snapshot`, `verification declaration`, `edited_yn`) (~0.5K)
2. `tests/unit/test_intake_facade_capture.py` - facade test pattern with faked engine: `_FakeResult`, `AsyncMock(spec=AsyncEngine)`, `connection.execute.await_args_list`, compiled-insert assertions (~2K tokens)
3. `tests/unit/test_partner_facade_register.py` - second faked-engine facade-test convention (spec names it for CareFacade) (~0.8K)
4. `tests/unit/test_intake_state_machine.py` - state machine test pattern: parametrized matrix, `IllegalTransitionError` raises (~1K tokens)
5. `tests/unit/test_intake_low_confidence.py` - REQ-023 hard gate template (~0.8K tokens)
6. `tests/unit/test_consent_check_gate.py` - consent gate template (~0.5K tokens)
7. `tests/unit/test_patient_intake_routes.py` - route-boundary convention reference (for the RBAC-skin acceptance in T06) (~0.5K)
8. `apps/backend/modules/care/facade.py` - both halves: method signatures to test (~1K tokens)
9. `apps/backend/modules/care/domain/state_machine.py` - both machines: transitions to verify (~0.8K tokens)
10. `apps/backend/modules/care/care_models.py` - DTOs for return type assertions (~0.3K tokens)
11. `apps/backend/bus/events.py` - event constants for payload validation (~0.3K tokens)

## Do NOT read

- Intake facade implementation details (only test patterns)
- Routes (route tests are separate)
- Prototype HTML
- ADR files

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend && npm run migration-check && npm run scan`

## Handoff notes

- Follow the faked-engine pattern from `test_intake_facade_capture.py`: `AsyncMock(spec=AsyncEngine)` with `_FakeResult` for `scalar_one`/`first`/`all`. Assert via `connection.execute.await_args_list` extracting `Insert` statements.
- REQ-023 hard test: attempt `approve_prescription` with `verification_declaration=False` -> must raise. Attempt with stale revision -> must raise.
- Outbox tests: extract the `Insert` for the outbox table, compile params, validate the `event_type` and `payload` JSON against the Pydantic model.
- Consent test: call `submit_doctor_input` (or whatever triggers history read), assert `ConsentFacade.check_consent` was called, test both granted and denied paths.
- Lifecycle test: wire the full happy path as a sequence of facade calls in one test function, asserting status at each step.
