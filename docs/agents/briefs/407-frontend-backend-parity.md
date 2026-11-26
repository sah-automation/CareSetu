# Brief - 407 T10 Frontend/backend threshold parity test

**Ticket:** #407 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Frontend recording/upload thresholds can no longer silently diverge from the backend. A backend pytest reads the frontend constants and asserts they equal the Python domain constants: record ceiling 180 s, usability floor 3 s, 3 record attempts, 3 upload attempts, 0.5 s backoff base. Backend is the source of truth. Client-only UI constants (poll interval/polls) are not pinned. Acceptances: the parity test asserts the 5 JS constants equal the Python domain constants; poll constants are not pinned; the test passes in the backend unit suite.

## Read-list (in order)

1. `apps/frontend/src/lib/intake/voice.ts` - the exported constants `MAX_RECORD_MS` (:9), `MIN_RECORD_MS` (:13), `MAX_RECORD_ATTEMPTS` (:17), `MAX_UPLOAD_ATTEMPTS` (:21), `UPLOAD_RETRY_BASE_MS` (:25); the client-only `INTAKE_POLL_INTERVAL_MS`/`MAX_INTAKE_POLLS` (:28-32) to exclude (~0.5K)
2. Backend source-of-truth constants: `modules/intake/domain/state_machine.py` - `MAX_RECORD_ATTEMPTS` (:72), `MIN_AUDIO_DURATION_MS` (:82), `MAX_AUDIO_DURATION_MS` (:86); `modules/intake/facade.py` - `MAX_UPLOAD_ATTEMPTS` (:82) and `_upload_backoff_delay` (:85, base 0.5 s) (~0.8K)
3. `docs/standards/coding-standards.md` §9.2 - the no-value-duplication-across-languages rule this ticket enforces (~0.2K)
4. An existing backend test that reads a repo file off disk - prior art for the file-read harness pattern in `tests/unit/` (~0.5K)

## Do NOT read

- AI pipeline internals, middleware, media storage, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new parity test passes (and fails if a constant drifts)

## Handoff notes

- Assert the exact pairs: 180000 ms, 3000 ms, 3, 3, 500 ms
- Backend is the source of truth by rule; a drift is caught here instead of silently diverging
- Do not pin `INTAKE_POLL_INTERVAL_MS`/`MAX_INTAKE_POLLS` - they are client-only UI pacing
