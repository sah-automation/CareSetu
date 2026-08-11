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
- Follow the PRD telemetry event names exactly (`patient_registered`, `pre_summary_low_confidence`, `report_rejected_mismatch`, …). New events are registered in the whitebox §4.2 registry, not invented ad hoc.

## 3. Correlation & Tracing

- One `trace_id` per incoming request (or per outbox event) flows through every log line, outbound call, and error envelope.
- Webhooks: provider `X-Request-Id` is mapped into the trace so a payment/status callback can be correlated to the initiating call.
- Async: the outbox event's `event_id` is the correlation key for consumers.

## 4. Audit vs. Telemetry

- **Audit** (`MOD-011`, append-only hash chain) = regulated acts: consent, record access, prescription issuance, report filing, settlements, partner decisions, auth failures, tamper attempts. Never written directly by modules - published to the outbox (`FEAT-020`, `NFR-D01`).
- **Telemetry** = everything else (latency, retries, AI cost, fallbacks used). Same event bus, different consumer.

## 5. Metrics & Alerts (cost-aware)

- `NFR-001` forbids paid observability. Use free/self-hosted options (e.g. SQL-backed counters, Prometheus/Grafana OSS on the same VM, or plain structured logs).
- Minimum alert set: `MOD-011` tamper attempt; backup failure; AI budget meter > 80%; outbox backlog > threshold; repeated third-party failures (breaker open).
- All alerting must be reviewable from the operator console - no PHI in alert payloads.
