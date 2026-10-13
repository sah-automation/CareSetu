# ADR-0024: Observability topology and free-tier vendor choices

**Status:** accepted
**Date:** 2026-10-13
**Decides:** The observability topology and its vendor choices - a hybrid free-tier stack (Langfuse Cloud + Sentry + Grafana Cloud + an external uptime monitor) over a Postgres `observability` schema that is the system of record, with the operator dashboard as the primary surface.
**Traceability:** `plan-phase14-observability.md` §0, §3, §4, §14, §15; parent #692; batch tickets #693-#712. Related: `ADR-0025` (the `observability` module/schema), `ADR-0026` (OpenTelemetry), `NFR-001`, `NFR-SEC-006`, `NFR-PERF-003`, `internal-modules.md` §4.2 (`EXT-002` LLM/AI Provider).

## Context

The platform needs to observe, alert on, and act on production behaviour across seven concern areas - application health, traces/metrics/logs, AI latency and cost, security guardrails, failures, and evals (`plan-phase14-observability.md` §1). Two hard constraints shape the choice. `NFR-001` caps total monthly spend at ₹2,000, which forbids any paid observability tier, and the module isolation rule (`ADR-0003`) forbids aggregating by reading other modules' tables cross-schema.

Vendor free tiers are generous but bounded and can be lost or throttled: Grafana Cloud retains 14 days, Sentry 5k events/mo, Langfuse 50k observations. A monitoring system whose decision data lives only in a vendor's retention window would lose the history the operator needs exactly when investigating an incident. The AI provider (LLM/AI, `EXT-002`) is the domain egress system of record for inference; the observability stack must observe it without becoming a second, competing egress path.

## Decision

### D1 - Hybrid free-tier topology

Langfuse Cloud holds AI spans, cost enrichment, and (later) evals; Sentry holds errors and crashes; Grafana Cloud holds infra and app metrics, traces, and optional log export over OTLP; an external free uptime monitor probes `GET /health`. Nothing is self-hosted and nothing is paid. Delivered by the Batch 1 tickets (#693-#712).

### D2 - The Postgres `observability` schema is the system of record

Aggregates for cost, quality, and business behaviour are written to the Postgres `observability` schema (`ADR-0025`), which is the system of record; the operator dashboard reads it through the operator observability APIs, and the vendors are dimensional detail reached by deep-link. Vendor retention limits or vendor churn never destroy the decision data. This is a hybrid free-tier stack, not vendor-only.

### D3 - `EXT-002` (LLM/AI Provider) stays the domain egress system of record

Langfuse **observes** the AI calls made through the existing MOD-005 adapters; it does **not** replace `EXT-002` as the integration-of-record for inference. The AI provider registration and its consent-gated minimal-egress contract (`NFR-SEC-006`) are unchanged. This separation is stated here to prevent a later merge of the observability registry into the AI integration entry.

### D4 - Vendor clients are env-gated and no-op when unconfigured

Each vendor SDK mirrors the existing Langfuse/Redis no-op pattern: with no key/DSN/endpoint set the client constructs but sends nothing. Local development and CI are unchanged until a gate is set (`OTEL_ENABLED`, `SENTRY_DSN`, `LANGFUSE_PUBLIC_KEY`, `OBSERVABILITY_ENABLED`).

### D5 - Strict free tiers only

No new recurring spend is introduced; sampling, quota alerts, and the Postgres ledger keep the solution inside the free ceilings (`NFR-001`).

### D6 - Telemetry is PHI-free by construction

Redaction at the structlog processor, a Sentry `before_send` scrub, and an OTel attribute allow-list (pseudonymous ids only) keep phone, OTP, tokens, free text, and raw provider payloads out of every vendor (`NFR-SEC-006`; `plan-phase14-observability.md` §10). Bounded external-call timeouts and graceful degradation (`NFR-PERF-003`) apply to telemetry egress as to any other external call.

## Considered options

- **Paid APM (Datadog, New Relic, Honeycomb):** rejected - violates the `NFR-001` cost floor.
- **Self-hosted OSS stack (Prometheus + Grafana + Loki + Tempo):** rejected - the hosting and operational cost is not free, and it exceeds what a single Render free instance can carry.
- **Vendor-only, no Postgres ledger:** rejected - free-tier retention (14 days on Grafana, 50k observations on Langfuse) would make the decision data evaporate between incidents.
- **Reuse `EXT-002` (LLM/AI Provider) as the observability integration:** rejected - conflates domain egress with telemetry, and would break the consent-gated minimal-PHI contract of the AI path.

## Consequences

- **Free-tier ceilings** are the standing risk (`plan-phase14-observability.md` §15): mitigated by the Postgres system of record, OTel sampling, and quota alerts; losing a vendor loses only dimensional detail, never the ledger.
- **Render spin-down and restarts** can drop buffered telemetry: exporters force-flush on shutdown, and the external uptime monitor separately covers availability.
- **PHI leakage** into third-party telemetry is a standing risk: mitigated by the redaction/scrub/allow-list postures above and covered by tests (`plan-phase14-observability.md` §16).
- Three new external systems enter `system-context.md` as `EXT-005` (Langfuse), `EXT-006` (Grafana Cloud), and `EXT-007` (Sentry), each documented off-by-default and PHI-free.
- No change to `EXT-001..004` rows or contracts, and no change to the session/auth/CORS/deploy surface (`ADR-0007`).
