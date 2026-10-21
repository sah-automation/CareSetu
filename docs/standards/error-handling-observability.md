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

Percentiles, not averages. Derived from the existing NFRs and the whitebox latency SLAs; the plan remains the source of truth for these numbers (`plan-phase14-observability.md` §11), restated here so the standard is checkable on its own. Every row names the source it was derived from, and no row introduces a new target: a new target is a new decision.

| SLO                                        | Target                                                              | Source of the target                             | Window measured over                      | Alert on breach               |
| :----------------------------------------- | :------------------------------------------------------------------ | :----------------------------------------------- | :---------------------------------------- | :---------------------------- |
| Auth - token validation (`validate_token`) | p95 < 100 ms                                                        | `internal-modules.md` §3.1 (MOD-001) latency SLA | the dashboard window, `now-6h` by default | none - an internal cause (D2) |
| Auth - OTP verification (`verify_otp`)     | p95 < 400 ms                                                        | `internal-modules.md` §3.1 (MOD-001) latency SLA | the dashboard window, `now-6h` by default | none - an internal cause (D2) |
| Directory search                           | p95 < 250 ms                                                        | `internal-modules.md` §3.2 (MOD-002) latency SLA | the dashboard window, `now-6h` by default | none - an internal cause (D2) |
| AI call (end to end, provider included)    | p95 <= 30 s                                                         | `internal-modules.md` §3.5 (MOD-005) latency SLA | the rolled day                            | `latency_objective_breach`    |
| Care-loop latency (`KPI-008`)              | tracked per stage; stage deltas recorded from Phase 9 (`PHASE-14B`) | PRD `KPI-008` (median loop completion, proposed) | a 30-day cohort window                    | none - tracked, not paged     |
| Error rate (5xx share of requests)         | < 1%                                                                | `plan-phase14-observability.md` §11              | the rolled day, silent below 100 requests | `error_rate_high`             |

**D1 - Every objective is derived, never chosen, and it says which slice it speaks about.** The set above is the six the plan names, and nothing outside it is a platform objective. The per-module latency SLAs, the frontend budget in `NFR-003`, the best-effort availability in `NFR-004` and the cost floor in `NFR-001` are real targets and are **not** platform objectives; they are enforced by their own gates. No row introduces a new target, and every row names the window it is measured over, because a target without a window cannot be checked - "< 1% error rate" says nothing about which requests it speaks about. The windows are the ones the platform already measures over, so naming them adds no number. The formal record, including why each of those stays where it is, is `ADR-0030`.

**D2 - An alert fires on a symptom, never on an internal cause.** No user experiences a token validation, a consent check or a directory search, so their p95s are measured and displayed but never paged. The AI call is different: the 30-second figure is the async pipeline's own timeout, so breaching it means the AI-assisted work is not produced and the pipeline degrades to forced doctor review, which the patient and the doctor both experience. It is the same figure the provider board shows, so the alert and the board cannot disagree. The alert kinds and the symptom each one names are tabulated in `ADR-0030` D3.

**D3 - The absence of an availability objective is a decision.** `NFR-004` states best-effort availability with no uptime SLA, so there is no availability objective, no availability alert and no error-budget burn-down. Availability is covered by the external free uptime monitor probing `GET /health`.

**D4 - The measurement's own liveness is alerted.** An empty error feed is ambiguous - a healthy system and a broken capture path look identical - so the capture path carries its own liveness signal. Without it, "no errors" would be a false all-clear.

### 5.2 Minimum alert set

| Alert                      | Trigger                                              | Signal source                                   |
| :------------------------- | :--------------------------------------------------- | :---------------------------------------------- |
| `audit_tamper`             | any `audit.tamper_detected`                          | `audit.*` events → `observability_alert_events` |
| backup failure             | drill or nightly backup reports failure              | `backup-drill.yml`                              |
| `ai_budget`                | meter/spend above 80% of the monthly cap (`NFR-001`) | `observability_ai_cost_budget`                  |
| `outbox_backlog`           | pending rows above threshold                         | `MOD-013` health read                           |
| `breaker_open`             | provider breaker state ≠ closed                      | `observability_ai_provider_health`              |
| `outbox_dead_letter`       | any dead-lettered event                              | dispatcher / `observability_alert_events`       |
| `provider_health_drop`     | success rate or p95 degrades                         | `observability_ai_provider_health`              |
| `error_rate_high`          | 5xx share of requests above the `< 1%` objective     | `observability_http_minute`                     |
| `queue_age`                | age of the oldest still-open job above threshold     | `observability_ai_queue_open`                   |
| `provider_rate_limited`    | upstream quota refusals above threshold              | `observability_ai_provider_health`              |
| `cost_outlier`             | one actor's day deviates from its own trailing week  | `observability_attribution_daily`               |
| `latency_objective_breach` | the AI call end to end breaches its `p95 <= 30 s`    | `observability_ai_provider_health`              |

Every name in backticks is a value the `observability_alert_events.kind` column carries; the backup drill is a workflow signal rather than a feed row, and it is listed here because a failed backup is an operational alert whether or not it lands in the feed. The symptom each kind names, and the reason a kind that measures an internal cause is not in this table, are in `ADR-0030` D3 and D4.

- All alerting must be reviewable from the operator console - the in-app `observability_alert_events` feed is the operator-visible record; delivery itself goes through the free channels (Sentry alerts, Grafana Cloud alerting to email/Slack webhook).
- Every kind in this table fires on a user-facing, business-facing or operator-facing **symptom**; an internal cause is measured and shown but never paged (`ADR-0030` D2, D3). The alert-rule set stays deliberately small: a new rule is argued for, not added.
- Acknowledgement is an in-app write against the feed: it changes who owns the response, never whether the condition still holds. Its statuses and the rules around it belong to the module that owns the feed, not here (`internal-modules.md` §3.14, `ADR-0029` D7).
