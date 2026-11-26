# Brief - 369 T05 Emit intake.started event on intake submission

**Ticket:** #369 Â· **Parent:** #364 Â· **Refreshed:** 2026-09-09
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

An intake.started telemetry event is emitted when a patient submits an intake, completing the PRD-defined telemetry trail for intake funnel metrics.

Acceptance criteria (from ticket):

- [ ] EVENT_INTAKE_STARTED = intake.started constant in bus/events.py
- [ ] IntakeStartedPayload(patient_id, mode, language) plus envelope builder in domain/events.py
- [ ] Emitted from facade.submit_intake() in same outbox transaction as intake.captured
- [ ] Telemetry-only handler registered in composition root (log + count, no domain effect)
- [ ] Event registry table in internal-modules.md updated
- [ ] Unit test asserting intake.started envelope emitted with correct payload

## Read-list (in order)

1. `apps/backend/bus/events.py` - the intake event constants block (~lines 104-110) where EVENT_INTAKE_STARTED is added (~0.7K tokens)
2. `apps/backend/modules/intake/domain/events.py` - existing payload classes and envelope builders (pattern to mirror for IntakeStartedPayload/builder) (~1.5K tokens)
3. `apps/backend/modules/intake/facade.py` - `submit_intake` (lines 109-193), specifically where the intake.captured outbox write happens, to co-emit intake.started in the same transaction (~1.7K tokens)
4. `apps/backend/modules/intake/adapters/__init__.py` (post-T01 thin composition root) - `register_handlers` to add the telemetry-only handler (~0.7K tokens)
5. `docs/architecture/internal-modules.md` Â§4.2 - event registry table to add intake.started (~1K tokens)

## Do NOT read

- Pipeline adapter, routes, media store
- Frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new test asserting intake.started envelope with correct payload passes
- `npm run typecheck` clean

## Handoff notes

- Blocked by #365 (T01) - the telemetry handler registers in the thin `__init__.py` composition root.
- The handler is telemetry-only: log + count, and MUST NOT touch domain tables or emit outbox rows of its own.
- Emitted in the same outbox transaction as intake.captured - one transactional write covers both events.
- Register the new event in the Â§4.2 registry (producer MOD-005) as required by the cross-reference rule - do not invent an unregistered name.
