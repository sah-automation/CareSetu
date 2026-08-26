# Brief - FIX-10 Deduplicate event handler boilerplate in health module

**Ticket:** #230 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

`_run_handler` helper extracts the engine-lifecycle + consumed-event + shell-check pattern. Five handlers become one-liner callbacks.

**Acceptance criteria:**

- `_run_handler(envelope, payload_class, handler_fn)` helper in `health/adapters/__init__.py`
- Helper handles: engine creation, `record_consumed_event`, shell check, engine disposal
- `handle_report_filed`, `handle_prescription_issued`, `handle_prescription_delivered`, `handle_settlement_recorded` use the helper
- `handle_consent_granted`, `handle_consent_revoked` use the helper
- `npm run test:unit:backend` passes
- `npm run typecheck` passes

## Read-list (in order)

1. `apps/backend/modules/health/adapters/__init__.py` - full file, 301 tokens (~301 tokens)

**Total:** ~301 tokens of reading, well within budget.

## Do NOT read

- Facade code, route code, frontend code
- Other module handlers
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verify current state
- `wc -l apps/backend/modules/health/adapters/__init__.py` - confirm file length

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes
- `npm run typecheck` passes
- `wc -l apps/backend/modules/health/adapters/__init__.py` - file should be shorter (less boilerplate)

## Handoff notes

- All five handlers follow the same pattern: `_delivery_engine()` → `engine.begin()` → `record_consumed_event` → check `delivered` → extract payload → ensure shell → insert entry → dispose engine
- The `handle_consent_granted` and `handle_consent_revoked` handlers are placeholders (no actual work yet)
- The helper should accept: `envelope`, `payload_class`, and a `handler_fn(connection, payload)` callback
- The helper handles the boilerplate; the callback only does the unique work
- Consider: should the helper also handle `_ensure_record_shell`? Most handlers need it, but consent handlers don't.
