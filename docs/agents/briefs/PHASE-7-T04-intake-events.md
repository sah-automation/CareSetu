# Brief - T04 Intake domain events + outbox/worker wiring

**Ticket:** #349 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The intake event shapes are frozen and registered so facade and pipeline tickets can emit and consume them: Pydantic payloads plus envelope builders for the registry event set (intake.captured, intake.retry_requested, pre_summary.ready, pre_summary.low_confidence, ai_job.completed, ai_job.failed, ai_egress.recorded), the module producer constant, and the intake handler-registration seam wired into the worker boot composition. Emitting bodies still land in later tickets, but the contract is testable now.

Acceptance criteria:

- [ ] Payload models validate against the envelope event_type dot-notation and the registry names (no snake_case)
- [ ] register_handlers registers the intake self-subscription for intake.captured and any declared handlers without raising duplicate-registration
- [ ] The worker boot composition includes the intake registration seam
- [ ] Unit test asserts an emitted envelope round-trips through the registry validator

## Read-list (in order)

1. `docs/architecture/internal-modules.md` §4.2 - authoritative event list (dot-notation, producers/subscribers) (~1K)
2. `apps/backend/modules/partner/domain/events.py` - envelope builder pattern to mirror (~1K)
3. `apps/backend/modules/partner/adapters/__init__.py` - register_handlers seam pattern (~0.5K)
4. `apps/backend/bus/events.py` + `envelope.py` + `registry.py` - envelope/registry validator (+ self-subscription semantics) (~2K)
5. `apps/backend/worker/main.py` - boot composition where the intake registration seam is wired (~0.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- state-machine internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Event set is fixed: intake.captured, intake.retry_requested, pre_summary.ready, pre_summary.low_confidence, ai_job.completed, ai_job.failed, ai_egress.recorded - registered under producer MOD-005 in §4.2 (use exactly these names; T03 makes the registry the single source of truth).
- Emitters/consumers bodies land in later tickets (T07, T10, T11); this ticket only freezes shapes and the registration seam.
