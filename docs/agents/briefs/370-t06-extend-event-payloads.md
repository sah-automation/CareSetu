# Brief - 370 T06 Extend event payloads with missing PRD fields

**Ticket:** #370 Â· **Parent:** #364 Â· **Refreshed:** 2026-09-09
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

intake.captured carries patient_id, mode, duration_s; intake.retry_requested carries reason field. Event payloads match PRD definitions and telemetry consumers have the fields they need.

Acceptance criteria (from ticket):

- [ ] IntakeCapturedPayload extended with patient_id (int), mode (str), duration_s (float | None)
- [ ] IntakeRetryRequestedPayload extended with reason (str)
- [ ] Envelope builders updated to populate new fields
- [ ] Callers (facade.submit_intake, pipeline adapter) pass new fields
- [ ] Event registry table in internal-modules.md updated
- [ ] Unit tests asserting new fields present in envelope output

## Read-list (in order)

1. `apps/backend/modules/intake/domain/events.py` - `IntakeCapturedPayload` (line 38), `IntakeRetryRequestedPayload` (line 49), and their envelope builders `intake_captured_envelope` (line 125), `intake_retry_requested_envelope` (line 135) (~1.5K tokens)
2. `apps/backend/modules/intake/facade.py` - `submit_intake` (lines 109-193) passes patient_id/mode/duration to the builders (~1.7K tokens)
3. `apps/backend/modules/intake/adapters/pipeline.py` (post-T01) - where `intake_retry_requested_envelope` is emitted, to supply the `reason` field (~1.5K tokens)
4. `docs/architecture/internal-modules.md` Â§4.2 - event registry table to reflect the extended payloads (~0.7K tokens)
5. Prior art: `tests/unit/test_intake_events.py` - the payload/envelope unit-test seam asserting new fields (~1.5K tokens)

## Do NOT read

- intake_models.py, routes, media store
- Frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - test_intake_events payload tests pass with new fields; facade + pipeline consumer tests pass with updated callers
- `npm run typecheck` clean

## Handoff notes

- Blocked by #365 (T01) - the intake.retry_requested emitter and builder callers live post-split.
- Adding required fields changes the builder signatures; every caller must be updated in this ticket (mypy strict will catch stragglers).
- The `reason` on intake.retry_requested is descriptive (e.g. "unusable_audio") alongside the existing record_attempt - keep record_attempt.
- duration_s is optional (`float | None`) - voice reports it, text mode is None.
- Register the extended payload shapes in the Â§4.2 registry per the cross-reference rule.
