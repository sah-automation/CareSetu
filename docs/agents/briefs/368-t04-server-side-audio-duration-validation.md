# Brief - 368 T04 Server-side audio duration validation

**Ticket:** #368 Â· **Parent:** #364 Â· **Refreshed:** 2026-09-09
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Backend enforces 3-second floor and 180-second ceiling on audio duration for voice intakes. A bypass client cannot submit unusable audio that wastes AI budget.

Acceptance criteria (from ticket):

- [ ] Constants MIN_AUDIO_DURATION_MS = 3000 and MAX_AUDIO_DURATION_MS = 180000 defined alongside MAX_RECORD_ATTEMPTS
- [ ] submit_intake() rejects voice intake with duration below 3s or above 180s (IntakeValidationError)
- [ ] re_record_intake() validates new media_ref duration
- [ ] Route query parameter constraint updated from ge=0 to ge=3000
- [ ] Boundary tests: 2999ms rejected, 3000ms accepted, 180000ms accepted, 180001ms rejected

## Read-list (in order)

1. `apps/backend/modules/intake/facade.py` - `submit_intake` (voice-mode branch, lines 109-193) and `re_record_intake` (lines 248-358) where `audio_duration_ms` flows into the media ref (~2.5K tokens)
2. `apps/backend/modules/intake/domain/state_machine.py` - where `MAX_RECORD_ATTEMPTS` is defined; add the two duration constants beside it (coding-standards S9.2 domain-constant placement) (~0.5K tokens)
3. `apps/backend/modules/intake/domain/exceptions.py` - `IntakeValidationError` to raise with descriptive messages (~0.4K tokens)
4. `apps/backend/modules/intake/adapters/routes.py` - the `audio_duration_ms` query parameter (line ~167, currently `Query(ge=0)`) to tighten to `ge=3000` (~0.5K tokens)
5. Prior art: `tests/unit/test_intake_facade_capture.py` and `tests/unit/test_intake_media_rerecord.py` - facade-with-fakes seam for boundary tests (~1.5K tokens)

## Do NOT read

- Pipeline adapter (`pipeline.py`), events, media store
- Frontend `voice.ts` (its MIN/MAX constants are the source, but validate server-side independently)
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - boundary tests for 2999/3000/180000/180001 pass
- `npm run typecheck` clean

## Handoff notes

- Blocked by #367 (T03) - the RECORD_UNUSABLE path must exist before audio validation can push an intake there end-to-end.
- Only validates voice mode (media_ref present); text mode is untouched.
- Frontend already has MIN_RECORD_MS/MAX_RECORD_MS constants in `voice.ts`; keep backend constants in sync but enforce independently - do not import frontend values.
- Raise `IntakeValidationError` with a message naming the actual and allowed duration so clients get a clear 422.
