# Brief - 697 A3a - OTel bootstrap + request-path instrumentation

**Ticket:** #697 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

Stand up OpenTelemetry over the HTTP OTLP exporter, gated by `OTEL_ENABLED`. Instrument the request path - FastAPI (server spans), the SQLAlchemy async engine (DB spans), and httpx (outbound spans) - with resource attributes (`service.name`, `deployment.environment`, `service.version` = git SHA), a parent-based sampler, a span-attribute allow-list that blocks non-allow-listed keys, and a force-flush on shutdown so a Render spin-down does not drop buffered telemetry. With the gate off, nothing is instrumented and boot is unchanged.

Acceptance criteria (verbatim):

- [ ] `OTEL_ENABLED` on wires the SDK + HTTP OTLP exporter; off is a no-op.
- [ ] FastAPI, SQLAlchemy async, and httpx are instrumented automatically; resource attributes and sampler are set from config.
- [ ] Span attributes are restricted to an allow-list; a careless caller cannot attach a PHI-bearing key.
- [ ] Exporters force-flush on app and worker shutdown.
- [ ] A request emits a span with the propagated `traceparent` context; a vendor-gate test proves off = inert.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. The `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_TRACES_SAMPLER_RATIO`, and `OTEL_SERVICE_VERSION` gates on `Settings` (added by #693) - the wires this ticket reads (~0.4K).
2. Parent plan `docs/plans/plan-phase14-observability.md` §5 (OTel design: HTTP OTLP exporter, instrumentation set, resource attributes, parent-based `traceidratio` sampler, span-attribute allow-list, shutdown flush) (~1K).
3. `app/main.py` lifespan + `create_app` - the FastAPI app the server-span instrumentor wraps, and where init + force-flush belong (~2K of a ~12K file; skip the route/router/facade wiring below the middleware stack).
4. `worker/main.py` `run_worker_until_stopped` - the worker composition root where the same bootstrap runs and flushes on shutdown (~1.5K).
5. `app/gateway/trace.py` `resolve_trace_id` / `TraceMiddleware` - the request trace context a request span must continue (shared with A1/A2) (~0.7K).
6. `observability/__init__.py` + `observability/langfuse_client.py` (no-op-when-unconfigured singleton) and `modules/consent/redis_cache.py` (graceful-degradation init) - the shape of the OTel bootstrap module and its off path (~1.7K).
7. `apps/backend/pyproject.toml` `[project] dependencies` + `uv.lock` - where the `opentelemetry-*` packages are added (~0.6K).

## Do NOT read

- Domain module internals, facades, or adapters.
- Frontend.
- Migrations.
- The dispatcher/APScheduler internals (that is A3b, a separate ticket).
- The Sentry SDK code (A4) in depth.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:backend` - PASS (2925 passed).
- (Harness context: `npm run test:unit:frontend` - all 1910 tests in 133 files pass, but vitest exits non-zero with a worker-timeout error; environment flake, not a test failure. Not needed for this ticket.)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - green, including a vendor-gate unit test (`OTEL_ENABLED` off = no instrumentor wired, no exporter, init never raises) and a span-attribute allow-list unit test (a non-allow-listed / PHI-bearing key is dropped before export).
- `npm run typecheck` - green.

## Handoff notes

- **Blocked by A2 (#695) and A5 (#693).** A5 defines the gates; A2 defines the propagated `traceparent` context a request span continues. Build both first.
- **Add the dependencies, do not vendor them.** `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, and the instrumentation packages `opentelemetry-instrumentation-fastapi`, `-sqlalchemy`, `-httpx` go in `apps/backend/pyproject.toml`; run `uv lock` after.
- **Use the HTTP OTLP exporter, not gRPC.** gRPC is frequently blocked on PaaS free tiers (Render); `opentelemetry-exporter-otlp-proto-http` is the production path.
- **Configure once, at one shared module in `observability/`.** Mirror the `langfuse_client.py` no-op singleton and `redis_cache.init_redis_client` graceful-degradation shape: when `OTEL_ENABLED` is false (or the endpoint is unset) return early without importing/wiring the SDK; a failed init is caught, logged, and never raises at boot. Initialise at BOTH composition roots (`app/main.py` lifespan and `worker/main.py` boot) and force-flush on shutdown at both.
- **Instrument the request path only (A3a):** FastAPI server spans, the SQLAlchemy async engine (DB spans), and httpx (outbound spans). The dispatcher/APScheduler instrumentation is A3b - do not pull it into this ticket.
- **Resource attributes from config:** `service.name` (a stable service id, e.g. `caresetu-backend`), `deployment.environment` from `APP_ENVIRONMENT`, `service.version` from the A5 `OTEL_SERVICE_VERSION` gate (the same git-SHA source A4 uses - keep one source, coding-standards §9.2).
- **Sampling:** a parent-based sampler with the configurable `traceidratio` ratio (`OTEL_TRACES_SAMPLER_RATIO`), so a continued trace (the A2 `traceparent`) is not re-sampled differently.
- **Span-attribute allow-list is a hard PHI gate.** Wrap/extend the span processor so only allow-listed keys (pseudonymous ids, route, status, model/provider, latency, token counts - never phone/OTP/token/free text/raw payload) can attach; a careless caller's non-allow-listed key is dropped before export. Document the allow-list in the module.
- **Off path is byte-for-byte unchanged:** with `OTEL_ENABLED` false, no instrumentor, no exporter, no global tracer provider mutation, and boot/tests behave exactly as today.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
