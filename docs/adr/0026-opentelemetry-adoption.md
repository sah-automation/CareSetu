# ADR-0026: OpenTelemetry adoption for traces, metrics, and logs

**Status:** accepted
**Date:** 2026-10-13
**Decides:** That CareSetu adopts OpenTelemetry as its instrumentation substrate - traces, metrics, and logs exported over OTLP to Grafana Cloud - with a configurable sampler, gated off by default, and trace context propagated API -> outbox -> worker.
**Traceability:** `plan-phase14-observability.md` §3, §5, §10, §14, §15; parent #692; batch tickets #695, #697, #698. Related: `ADR-0002` (transactional outbox), `ADR-0024` (observability topology), `NFR-PERF-003`, `NFR-001`, `error-handling-observability.md` §5.

## Context

The platform has an API-only `trace_id` (`app/gateway/trace.py`) but no distributed tracing: the outbox dispatcher and worker carry no correlation id, so an AI call made from a worker cannot be linked back to the request that scheduled it. There are no metrics beyond the API request path, no structured JSON logs, and no way to see dependency health or latency percentiles. The plan's locked decision is "Full OpenTelemetry now (traces + metrics + logs via OTLP)" (`plan-phase14-observability.md` §0). The constraints are the `NFR-001` cost floor (free-tier volume), the requirement that an unconfigured environment behaves exactly as before, and `NFR-PERF-003`'s bounded external calls.

## Decision

### D1 - Adopt OpenTelemetry, vendor-neutral, over OTLP/HTTP

Dependencies: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, plus the `-fastapi`, `-sqlalchemy`, `-httpx`, and `-logging` instrumentation packages. The **HTTP** exporter is used because gRPC is frequently blocked on PaaS free tiers. Delivered by #697 (bootstrap + request path) and #698 (dispatcher, metrics, cache counters).

### D2 - Instrumentation set

FastAPI (server spans), SQLAlchemy async engine (DB spans), httpx (outbound spans for the AI/SMS/WhatsApp/UPI adapters), the outbox dispatcher loop, and APScheduler jobs. No module emulates a span by hand where an instrumentation library covers the boundary.

### D3 - Resource attributes

`service.name`, `deployment.environment`, and `service.version` (= git SHA) identify every span, metric, and log record.

### D4 - Sampling is parent-based and configurable

A `traceidratio` default kept well above the low production volume, adjustable to keep free-tier ingest bounded (`plan-phase14-observability.md` §15).

### D5 - Trace context propagates API -> outbox -> worker

A W3C `traceparent` is carried in the outbox row (a nullable column where the payload has no metadata slot) so worker spans link back to the originating request. This is the net-new capability that makes end-to-end traces real (#695). The API's existing `trace_id` remains the in-request correlation handle.

### D6 - Metrics via OTLP to Grafana Cloud (Mimir)

An optional Prometheus `/metrics` endpoint stays behind `METRICS_ENABLED` for local or backup scraping, but OTLP is the production path.

### D7 - Logs: structlog JSON to stdout is the baseline; the OTel logging bridge is optional

When enabled, the bridge ships structured logs to Grafana Cloud (Loki).

### D8 - Gated off by default and no-op when unconfigured

`OTEL_ENABLED` plus endpoint/headers must be set before any span or metric leaves the process; with the gate off (or the endpoint absent) instrumentation constructs but exports nothing, so local dev and CI are unchanged (mirrors the Langfuse/Redis no-op pattern).

### D9 - Force-flush exporters on shutdown

OTel (and Sentry/Langfuse) exporters flush on shutdown so Render spin-down and restarts do not drop buffered telemetry.

### D10 - PHI-free attributes

An OTel attribute allow-list admits pseudonymous ids and metrics only - no phone, OTP, tokens, free text, or raw payloads (`NFR-SEC-006`; `plan-phase14-observability.md` §10). Telemetry egress respects the same bounded-timeout and degradation discipline as any external call (`NFR-PERF-003`).

## Considered options

- **Vendor-specific agents (Datadog/New Relic/Honeycomb SDKs):** rejected - not free-tier, and they would lock the instrumentation to one vendor (`NFR-001`, `ADR-0024`).
- **Prometheus-only scrape (no distributed tracing):** rejected - it cannot follow a request through the async outbox seam into the worker, which is the key gap this decision closes.
- **Defer distributed tracing; keep API-only `trace_id`:** rejected - the worker AI calls and outbox latency are exactly where the operator needs correlation; retrofitting propagation later is more disruptive.
- **gRPC OTLP exporter:** rejected - gRPC is frequently blocked on free PaaS tiers; HTTP is the reliable path.

## Consequences

- The dispatcher and worker gain a correlation id at last, closing the API -> outbox -> worker gap; outbox-span linkage depends on the `traceparent` column added by #695.
- Ingest volume is bounded by the sampler and the free-tier ceilings are a standing risk (`plan-phase14-observability.md` §15); the Postgres ledger (`ADR-0025`) keeps decision data even when vendor retention expires.
- An unconfigured environment is byte-for-byte unchanged in behaviour, and `ci.yml` builds the gates on and off so the no-op path cannot rot (`plan-phase14-observability.md` §16).
- Operator read APIs and the dashboard deep-link out to Grafana; the in-app views read the `observability` schema, not the OTel exporter.
