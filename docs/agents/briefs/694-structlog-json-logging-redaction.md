# Brief - 694 A1 - structlog JSON logging + PHI redaction

**Ticket:** #694 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Structured logging for the API, the worker, and the outbox dispatcher: JSON log lines in production, readable console lines in dev, selected by `LOG_FORMAT`. Every line carries the request's trace id, and a redaction processor strips PHI/secrets by key (phones, OTPs, tokens, free text, raw provider payloads) before emit. This is the logging baseline the rest of the batch builds on.

Acceptance criteria (verbatim):

- [ ] `structlog` is configured once and used by app, worker, and dispatcher; `LOG_FORMAT=json` emits JSON, `console` emits readable output.
- [ ] Each log line carries `trace_id` (from the existing request trace context) and service identity.
- [ ] A redaction processor removes values under a documented key denylist; a unit test proves a phone/OTP/token/free-text value never reaches the rendered output.
- [ ] Logging setup failure never raises at boot.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. The `LOG_FORMAT` gate on `Settings` (field `log_format`, added by #693) - the console/json selector this ticket reads (~0.3K).
2. `app/main.py` lifespan + `create_app` boot sequence - the app composition root where the single `configure_logging(...)` call belongs (~2K of a ~12K file; skip the route/router/facade wiring below the middleware stack).
3. `worker/main.py` `run_worker_until_stopped` / `main` - the worker composition root boot where logging is configured once (~1.5K).
4. `bus/dispatcher.py` `process_outbox_table` / `run_poll_loop` and their existing `logger` calls (the fan-out, retry, dead-letter lines) - the dispatcher log lines that must carry `trace_id` (~1.5K of a ~4.6K file).
5. `app/gateway/trace.py` `resolve_trace_id` and `TraceMiddleware` - the one request-scoped trace source to bind into the logging context (a `ContextVar` set in middleware, read by the processor) (~0.7K).
6. `observability/__init__.py` and `observability/langfuse_client.py` (`get_langfuse_client`) - the shared-infra package and the no-op-when-unconfigured singleton shape the new logging module should mirror (~0.5K).
7. `docs/standards/error-handling-observability.md` §2 (JSON field contract, the hard "no PHI/OTP/token/raw provider payload" rule) and §3 (trace correlation) - the rendered-field contract and the reason the denylist exists (~1K).

## Do NOT read

- Domain modules and their facades.
- Frontend.
- Migrations.
- The Sentry/OTel SDK code (A4/A3) - this ticket defines the shared redaction surface they later reuse.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:backend` - PASS (2925 passed).
- (Harness context: `npm run test:unit:frontend` - all 1910 tests in 133 files pass, but vitest exits non-zero with a worker-timeout error; environment flake, not a test failure. Not needed for this ticket.)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - green, including a redaction unit test (asserting a phone / OTP / token / free-text value never reaches the rendered output for both `json` and `console` formats) and a logging-format unit test (`json` renders JSON, `console` renders readable lines).
- `npm run typecheck` - green.

## Handoff notes

- **Add the dependency, do not vendor it.** `structlog` goes in `apps/backend/pyproject.toml` `[project] dependencies`; run `uv lock` after. This mirrors how `langfuse` was added.
- **Configure once, from one module.** The natural home is a new module in the existing top-level `observability/` package (shared infra, no schema, imports nothing from `modules` - same contract as `langfuse_client.py`). Both `app/main.py` and `worker/main.py` call it once; the dispatcher and every existing `logging.getLogger(...)` call flow through it.
- **`LOG_FORMAT=console` in dev, `json` in prod.** Use structlog's console renderer for the readable path and a JSON renderer for the production path; the field set is the standard §2 contract (`timestamp`, `level`, `logger`, `module`, `trace_id`, `event`/`message`, context).
- **`trace_id` comes from the existing request context.** `resolve_trace_id(request)` mints/reads `request.state.trace_id`. The cleanest bridge is a `ContextVar` set by `TraceMiddleware` (and a worker-side setter for the dispatcher), read by a structlog processor so every line - including the dispatcher's - carries it without threading a `Request` through.
- **Redaction is by key, before emit.** A processor walks the event dict and replaces values under a documented key denylist (phone/msisdn/otp/code/token/secret/free-text/transcript/raw/payload, etc.) with a fixed placeholder. Document the denylist in the module docstring so Sentry's `before_send` (A4) can share the same rule.
- **Boot must never raise.** Wrap configuration in a try/except that logs a warning and falls back to the stdlib default - a logging failure must not take the app or worker down (mirror the Redis no-op discipline).
- **Downstream:** A2 (#695) relies on this to make the propagated worker trace id observable; A4 (#696) reuses this redaction surface in the Sentry scrubber.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
