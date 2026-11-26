# Brief - 696 A4 - Sentry integration + PHI scrub + release tracking

**Ticket:** #696 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Wire Sentry for exception tracking behind the `SENTRY_DSN` gate: initialise the SDK at app and worker boot with `release` = git SHA and the request `trace_id` attached, and a `before_send` hook that scrubs phones, OTPs, tokens, and free text before an event leaves the process. With the gate off the integration is inert and boot is unchanged.

Acceptance criteria (verbatim):

- [ ] Sentry initialises when `SENTRY_DSN` is set, at both composition roots; a no-op when it is empty.
- [ ] Events carry `release` (git SHA) and trace correlation.
- [ ] `before_send` removes the documented PHI/secret denylist from event payloads; a unit test proves a phone/OTP/token never reaches the outgoing event.
- [ ] A vendor init failure never takes the app down.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. The `SENTRY_DSN` and `SENTRY_TRACES_SAMPLE_RATE` gates on `Settings` (fields `sentry_dsn`, `sentry_traces_sample_rate`, added by #693) - the on/off switch and sample rate (~0.3K).
2. `app/main.py` lifespan + `create_app` boot - the app composition root where Sentry is initialised and flushed (~2K of a ~12K file; skip the route/router/facade wiring).
3. `worker/main.py` `run_worker_until_stopped` / `main` - the worker composition root init + shutdown flush (~1.5K).
4. `observability/__init__.py` and `observability/langfuse_client.py` (`get_langfuse_client`) - the shared-infra package and the no-op-when-unconfigured lazy singleton the Sentry bootstrap should mirror; this is also where the A1 redaction key denylist lives and should be reused (~0.7K).
5. `modules/consent/redis_cache.py` `init_redis_client` / `get_redis_client` - the canonical graceful-degradation pattern: absent config returns early, a failed init is caught, logged, and never raises at boot (~1.3K).
6. `app/gateway/trace.py` `resolve_trace_id` - the request trace id to attach to events (via the shared context established in A1) (~0.7K).
7. Parent plan `docs/plans/plan-phase14-observability.md` §4 (gate row: release = git SHA, trace_id correlated, PHI scrub) and §10 (Batch-1 PHI guardrails), plus `docs/standards/security-phii-standards.md` §4 (secrets never in code/config/logs) (~1.2K).

## Do NOT read

- Domain modules and their facades.
- Frontend.
- Migrations.
- The OTel SDK code (A3) in depth - only the shared init/no-op shape matters here.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:backend` - PASS (2925 passed).
- (Harness context: `npm run test:unit:frontend` - all 1910 tests in 133 files pass, but vitest exits non-zero with a worker-timeout error; environment flake, not a test failure. Not needed for this ticket.)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - green, including a vendor-gate unit test (`SENTRY_DSN` empty = inert, no client, init never raises) and a scrub unit test (a phone / OTP / token value in an event payload never reaches the outgoing event via `before_send`).
- `npm run typecheck` - green.

## Handoff notes

- **Blocked by A1 (#694):** A4 reuses the shared redaction denylist that A1 defines. Build A1 first.
- **Add the dependency, do not vendor it.** `sentry-sdk` goes in `apps/backend/pyproject.toml` `[project] dependencies`; run `uv lock` after (mirrors how `langfuse` was added).
- **Inert when unset, and never crash boot.** Initialise only when `sentry_dsn` is truthy; an empty DSN returns immediately (like `get_langfuse_client` with no key). Wrap `sentry_sdk.init(...)` in a try/except that logs a warning and leaves the integration off - a vendor or transport failure must never take the app or worker down. Initialise at BOTH composition roots (app lifespan and worker boot).
- **Release = git SHA, single source.** There is no existing git-SHA settings field; reuse the A5 `OTEL_SERVICE_VERSION` gate (field `service_version` / `otel_service_version`) as the one source rather than adding a second knob (coding-standards §9.2 single-source rule), and default it to the app version when unset. Do not commit a hardcoded SHA.
- **Trace correlation.** Attach the request trace id (the A1 `ContextVar` set by `TraceMiddleware`) to events so Sentry errors correlate with structured logs; use the same W3C context A2 propagates where available.
- **`before_send` scrubs by the documented key denylist, not by regex alone.** Reuse A1's key denylist (phones, OTPs, tokens, free text, raw provider payloads); walk `event` (and `event["extra"]` / request data / breadcrumbs) and replace denylisted values with a fixed placeholder. The unit test must prove a denylisted value cannot survive.
- **Flush on shutdown.** Call the SDK's flush during app/worker shutdown so a Render spin-down does not drop queued events (same discipline as the OTel/A3 flush).
- **No secret committed.** `SENTRY_DSN`/headers are placeholders in docs, `sync: false` in `render.yaml` - never real values.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
