# Brief - 698 A3b - OTel dispatcher/scheduler instrumentation + metrics + cache counters

**Ticket:** #698 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Extend the OpenTelemetry work to the async path and to metrics: instrument the outbox dispatcher loop and the APScheduler jobs so worker activity shows up in traces, enable OTel metrics export (request latency histograms, error counters, cache hit/miss counters) behind `METRICS_ENABLED`, and add hit/miss counters to the existing Redis caches with zero behaviour change. An optional Prometheus `/metrics` endpoint behind the same gate may be kept for local scraping.

### Acceptance criteria

- [ ] Dispatcher and APScheduler jobs produce spans that link to the originating request via the propagated context.
- [ ] OTel metrics export when `METRICS_ENABLED`; request latency and error counters exist.
- [ ] Cache hit/miss counters added to the consent and partner Redis caches with no behaviour change and no-op when Redis is absent.
- [ ] With the gate off, nothing is instrumented and boot is unchanged.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. The parent plan's §5 "OpenTelemetry design" - the instrumentation list (dispatcher loop + APScheduler jobs), the HTTP OTLP exporter choice, metrics-over-OTLP-to-Mimir, the `OTEL_ENABLED`/`METRICS_ENABLED` gates, and the shutdown-flush requirement. (~1K tokens)
2. The A3a OTel bootstrap in the `observability/` package (ticket #697) - the exported setup/instrument entrypoint, the span-attribute allow-list, and the meter accessor A3b must obtain counters from. A3a is the blocking predecessor; bind to its named interface, do not re-create a provider. (~1.5K tokens)
3. `bus.dispatcher.run_poll_loop`, `process_outbox_table`, `OutboxRow`, `TablePollResult` - the loop that must emit a span per poll pass / per row and adopt the `traceparent` A2 (#695) restored onto the claimed row; the counters already tracked here (claimed / fanned_out / retried / dead_lettered) are the natural metric points. (~4K tokens)
4. `worker.main.build_scheduler`, `run_worker_until_stopped`, `_run_credential_sweep` - the `AsyncIOScheduler` job to wrap in a span, and the worker composition root where the exporter init + shutdown flush land. (~2K tokens)
5. `modules.consent.redis_cache.get_cached_decision` / `set_cached_decision` - the hit/miss counter insertion points; a hit is a non-None read, a miss is a None return (including the `client is None` path). (~1.5K tokens)
6. `modules.partner.directory_cache.get_cached_search` / `set_cached_search` - the same hit/miss points for the directory-search cache. (~1.5K tokens)
7. The A5 Settings gates `OTEL_ENABLED`, `METRICS_ENABLED` (ticket #693) - the gate names and their disabled-by-default contract. (~250 tokens)

## Do NOT read

- Any domain module beyond the two named caches (consent + partner directory).
- The frontend.
- Migrations (A3b is migration-free).
- A3a's internal OTel module body beyond the interface it exports.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (current tree)
- `npm run test:unit:backend` - PASS (2925 passed)
- `npm run migration-check` - PASS

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- New cache-counter unit test: hit and miss each increment; Redis absent -> no-op and no raise.
- New vendor-gate test: `METRICS_ENABLED` off -> counters inert, boot unchanged, no raise.
- New trace test: a dispatched event row carries the propagated context onto the loop span.

## Handoff notes

- Mirror the existing Langfuse/Redis no-op pattern: gate off means nothing is registered and boot is byte-for-byte unchanged. Every vendor init failure must degrade, never take the worker/app down.
- Get counters from A3a's meter accessor rather than calling `opentelemetry.metrics.get_meter` directly, so the allow-list and gate stay in one place.
- Cache counters must be pure side-effects next to the existing `try/except` blocks - zero behaviour change, fail-silent on counter errors, and no-op on the `client is None` path.
- Dispatcher/worker spans must be children of the propagated request context (A2), which is the whole point of the async-path tracing; a detached root span is a miss.
- A3a is not yet in the tree - if `observability/` no longer exposes the expected setup/meter interface, re-grep the symbol and refresh this brief rather than widening the read-list.
