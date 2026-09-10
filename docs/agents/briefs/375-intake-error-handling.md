# Brief - 375 Harden submit endpoint error handling and pre-summary race condition

**Ticket:** #375 · **Parent:** #373 · **Refreshed:** 2026-09-10
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Fix three production errors in the intake feature:

1. **500 at `/v1/intake/submit`** (voice + text+voice): Untyped exceptions (SQLAlchemy `ProgrammingError`, `ValueError` from `int(subject_id)`) escape to the generic catch-all at `main.py:302`, returning opaque `INTERNAL_SERVER_ERROR`.
2. **404 at `/intake/[id]/pre-summary`**: Race condition - pre-summary row not yet created when patient arrives after submit.
3. **Voice note <3s on text page**: Frontend accepts but backend rejects with 422.

Acceptance criteria:

- DB failures in submit path return `INTAKE_INTERNAL` envelope with structured logging
- Bad `subject_id` tokens return 401 instead of 500
- Pre-summary page polls gracefully on 404 with processing spinner
- Text page validates voice duration client-side before upload
- All existing tests pass (3 pre-existing failures in `test_app_shell.py` and `test_seed_demo.py` are unrelated)

## Read-list (in order)

1. **`modules/intake/adapters/routes.py`** lines 136-160, 387-460 - submit endpoint and error handlers; the `int(subject_id)` cast and the typed exception handler registrations (~1.5K tokens)
2. **`app/main.py`** lines 296-315 - generic catch-all `_unhandled_exception` handler that currently catches DB errors (~0.5K tokens)
3. **`app/gateway/errors.py`** lines 35-89, 127-148 - `ErrorEnvelope` shape, `error_response()` funnel, `register_gateway_error_handlers` pattern to follow (~1K tokens)
4. **`docs/standards/error-handling-observability.md`** - error taxonomy (expected vs operational), structured logging rules, no-PHI constraint (~0.5K tokens)
5. **`docs/architecture/internal-modules.md`** lines 301-337 - MOD-005 spec: state machines, interfaces, NFR allocation (~1K tokens)
6. **`frontend/src/app/(patient)/patient/intake/[id]/pre-summary/page.tsx`** - current pre-summary page to add polling (~1.5K tokens)
7. **`frontend/src/app/(patient)/patient/intake/text/page.tsx`** - current text page to add MIN_RECORD_MS guard (~1K tokens)
8. **`frontend/src/lib/i18n/dictionaries.ts`** - EN/HI dictionaries for new strings (~0.5K tokens)

## Do NOT read

- `docs/archive/` - superseded by PRD
- `modules/intake/facade.py` - already raises typed errors; no changes needed
- `app/gateway/jwt_verify.py` - auth middleware unchanged
- Media store modules - working correctly
- Outbox/dispatcher modules - unrelated to HTTP error handling

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 3 pre-existing failures expected (test_app_shell, test_seed_demo); 1615+ should pass
- `npm run test:unit:frontend` - should pass
- `npm run typecheck` - should pass

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - no new failures
- `npm run test:unit:frontend` - no new failures
- `npm run typecheck` - passes
- `npm run lint` - passes
- Manual: submit voice recording returns structured error on DB failure, not generic 500
- Manual: pre-summary page shows spinner on 404, polls, resolves or times out
- Manual: text page blocks voice notes <3s with preview preserved

## Handoff notes

- Parent #373 already fixed: media store wiring, text-mode voice notes, doctor playback. This ticket hardens error handling that #373 exposed.
- The 3 pre-existing test failures (`test_dev_otp_gated_outside_dev_test_environment`, `test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default`, `test_otp_surface_disabled_by_default`) are in `test_app_shell.py` and `test_seed_demo.py` - unrelated to intake.
- The intake module's error handler pattern matches `register_gateway_error_handlers` in `app/gateway/errors.py` - follow that pattern for the new `SQLAlchemyError` handler.
- Pre-summary polling should use the same constants as voice/text submit pages: `INTAKE_POLL_INTERVAL_MS` (2000ms) and `MAX_INTAKE_POLLS` (15).
- The `error_response()` function in `app/gateway/errors.py` is the single funnel for all rejection envelopes - use it for the new handler.
