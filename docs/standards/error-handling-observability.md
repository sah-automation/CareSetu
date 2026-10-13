# Error Handling & Observability Standards

**Scope:** How failures are classified, logged, correlated, and surfaced - without violating `NFR-001`'s cost floor.
**Upstream:** PRD §5.2 (error scenarios & fallbacks), telemetry events per feature, `NFR-004`, `NFR-D01`.

---

## 1. Error Taxonomy

Classify every failure into exactly one bucket; handling differs per bucket:

| Class                 | Meaning                                                                                        | Handling                                                                                   |
| --------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Expected (client)** | User/partner input errors, policy violations (`CONSENT_DENIED`, out-of-stock, mismatch upload) | `4xx` envelope, PRD §5.2 message, no alarm                                                 |
| **Operational**       | Bugs, DB/queue failures, resource exhaustion                                                   | `5xx`; log + alarm; retry/backoff for transient                                            |
| **Third-party**       | Provider timeout/error/outage                                                                  | `502/503/504`; circuit-breaker state; **degrade, never block** (see third-party standards) |
| **Security**          | Authn/authz failures, tamper attempts, webhook verification failures                           | Log + alarm; audit append; never return internal detail                                    |

- Expected errors are not exceptions across module boundaries - they are typed results/domain errors. Exceptions are reserved for operational/security bugs.

## 2. Structured Logging

- JSON logs: `{ timestamp, level, logger, module, trace_id, actor_id?, event, message, ...context }`.
- **No PHI, no OTPs, no tokens, no raw provider payloads in logs** - PHI redaction is a hard rule (`NFR-SEC`). Redact field values by schema, and scrub on write.
- Log levels: `debug` local only; `info` for lifecycle/telemetry events; `warning` for degradations and retries; `error` for operational failures; `critical` for data-integrity/security.
- Event names follow the registry dot-notation in `internal-modules.md` §4.2 (e.g. `patient.auth_failed`, `pre_summary.low_confidence`, `report_rejected_mismatch`) - that registry is the single source of truth, not the PRD's legacy snake_case telemetry names. New events are registered in the whitebox §4.2 registry, not invented ad hoc.

## 3. Correlation & Tracing

- One `trace_id` per incoming request (or per outbox event) flows through every log line, outbound call, and error envelope.
- Webhooks: provider `X-Request-Id` is mapped into the trace so a payment/status callback can be correlated to the initiating call.
- Async: the outbox event's `event_id` is the correlation key for consumers.

## 4. Audit vs. Telemetry

- **Audit** (`MOD-011`, append-only hash chain) = regulated acts: consent, record access, prescription issuance, report filing, settlements, partner decisions, auth failures, tamper attempts. Never written directly by modules - published to the outbox (`FEAT-020`, `NFR-D01`).
- **Telemetry** = everything else (latency, retries, AI cost, fallbacks used). Same event bus, different consumer.

## 5. Metrics & Alerts (cost-aware)

- `NFR-001` forbids paid observability. The stack is hybrid free-tier plus Postgres as the system of record (`PHASE-14A`, `ADR-0024`/`0025`/`0026`):

  | Signal                     | Tool                                 | Gate (off by default)                           | Landing                                                                              |
  | :------------------------- | :----------------------------------- | :---------------------------------------------- | :----------------------------------------------------------------------------------- |
  | Structured logs            | structlog JSON to stdout             | `LOG_FORMAT` (`console` in dev, `json` in prod) | Render logs; optional OTel log bridge to Grafana Loki                                |
  | Errors / crashes           | Sentry SDK                           | `SENTRY_DSN` empty = off                        | Sentry free; `before_send` scrubs PHI, release = git SHA                             |
  | Infra + app metrics/traces | OpenTelemetry SDK (OTLP/HTTP)        | `OTEL_ENABLED` + endpoint/headers               | Grafana Cloud free (Mimir/Tempo/Loki)                                                |
  | AI spans + cost            | Langfuse SDK                         | `LANGFUSE_PUBLIC_KEY` (already present)         | Langfuse Cloud free                                                                  |
  | Uptime                     | external free monitor                | dashboard-configured (probes `GET /health`)     | survives Render cold starts                                                          |
  | AI/business aggregates     | Postgres `observability` (`MOD-013`) | `OBSERVABILITY_ENABLED`                         | **system of record** - vendor retention limits or churn never lose the decision data |

- Every vendor client is env-gated and no-ops when unconfigured, so local dev and CI boot unchanged until a gate is set; exporters force-flush on shutdown so a Render spin-down does not drop buffered telemetry.
- Aggregation never crosses schemas: `MOD-013` consumes outbox events into its own `observability` schema rather than reading other modules' tables (`ADR-0003`, `ADR-0025`).
- **No PHI in logs, spans, error payloads or alert payloads** - redaction at the structlog processor, `before_send` in Sentry, and an attribute allow-list on OTel spans; pseudonymous ids only (`NFR-SEC-006`).

### 5.1 SLOs

Percentiles, not averages. Derived from the existing NFRs and the whitebox latency SLAs; the plan remains the source of truth for these numbers (`plan-phase14-observability.md` §11), restated here so the standard is checkable on its own.

| SLO                                        | Target                                                              |
| :----------------------------------------- | :------------------------------------------------------------------ |
| Auth - token validation (`validate_token`) | p95 < 100 ms                                                        |
| Auth - OTP verification (`verify_otp`)     | p95 < 400 ms                                                        |
| Directory search                           | p95 < 250 ms                                                        |
| AI call (end to end, provider included)    | p95 <= 30 s                                                         |
| Care-loop latency (`KPI-008`)              | tracked per stage; stage deltas recorded from Phase 9 (`PHASE-14B`) |
| Error rate (5xx share of requests)         | < 1%                                                                |

### 5.2 Minimum alert set

| Alert                | Trigger                                              | Signal source                                   |
| :------------------- | :--------------------------------------------------- | :---------------------------------------------- |
| Audit tamper         | any `audit.tamper_detected`                          | `audit.*` events → `observability_alert_events` |
| Backup failure       | drill or nightly backup reports failure              | `backup-drill.yml`                              |
| AI budget            | meter/spend above 80% of the monthly cap (`NFR-001`) | `observability_ai_cost_budget`                  |
| Outbox backlog       | pending rows above threshold                         | `MOD-013` health read                           |
| Circuit breaker open | provider breaker state ≠ closed                      | `observability_ai_provider_health`              |
| Dead-letter row      | any dead-lettered event                              | dispatcher / `observability_alert_events`       |
| Provider health drop | success rate or p95 degrades                         | `observability_ai_provider_health`              |

- All alerting must be reviewable from the operator console - the in-app `observability_alert_events` feed is the operator-visible record; delivery itself goes through the free channels (Sentry alerts, Grafana Cloud alerting to email/Slack webhook).
