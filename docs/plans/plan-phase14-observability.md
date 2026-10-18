# Phase 14A - Observability & Monitoring Platform Plan

**Status:** proposed - ready for `/to-tickets` (Batch 1)
**Scope:** Carve the observability slice out of roadmap `PHASE-14` (`docs/roadmap/implementation-roadmap.md` §2.14), pull it forward to the current build point (Phase 8 + doctor-console batches), and expand it into a production monitoring system whose primary surface is the Operator dashboard, backed by third-party free tiers and OpenTelemetry.
**Supersedes:** `docs/plans/plan-post-phase14-observability.md` (deleted 2026-10-12; its still-relevant production-readiness items are carried forward in Appendix A below).
**Depends on:** Phase 8 complete (current), `plan-phase7-tracing-prep.md` implemented (Langfuse SDK + config + tracing gate in place).
**Does NOT cover:** the roadmap's full-loop E2E test suite and the launch/restore release gate - those stay in `PHASE-14B` (release readiness) because they cannot run until Phases 9-13 exist.

---

## 0. Locked decisions

| Decision              | Choice                                                                                                                           |
| :-------------------- | :------------------------------------------------------------------------------------------------------------------------------- |
| Topology              | Hybrid free tiers: Langfuse Cloud + Sentry + Grafana Cloud free for pillars; Postgres `observability` schema is system of record |
| Budget posture        | Strict free tiers only (`NFR-001`); no new recurring spend                                                                       |
| First delivered slice | Foundation + AI/cost + errors + operator dashboard (Batch 1 - see §12)                                                           |
| Plan artifact         | This document + `/to-tickets`                                                                                                    |
| Tracing depth         | Full OpenTelemetry now (traces + metrics + logs via OTLP)                                                                        |

---

## 1. Goal

Stand up an advanced monitoring system around CareSetu so the operator can observe, alert on, and act on production behaviour across seven concern areas - without violating `NFR-001` (no paid observability) or the module-isolation rule (`ADR-0003`):

1. **Application monitoring** - uptime/health, request latency/error rate, dependency health.
2. **Observability** - distributed traces, metrics, structured logs, correlation.
3. **Logging** - queryable structured JSON, trace-correlated, PHI-free.
4. **Latency & cost monitoring** - per-route and per-AI-task latency; real AI spend vs budget, per provider/model/task.
5. **Security & Guardrails** - audit-tamper, auth-failure/lockout, rate-limit/consent anomalies, webhook signature failures, CSP violations, AI-egress/PHI guardrails.
6. **Failures** - exception tracking, outbox backlog/dead-letter, circuit-breaker opens, degradation counts.
7. **Evals** - Langfuse datasets, LLM-as-judge, annotation queue fed by doctor review outcomes.

The decision loop is the point: every signal must be _actionable_ from the operator console, with documented runbooks and defined SLOs.

---

## 2. Current-state gap (docs vs. code)

The prior plan was written against assumptions that do not hold. Corrections this plan is built on:

| Prior-plan assumption                                   | Actual state                                                                                        |
| :------------------------------------------------------ | :-------------------------------------------------------------------------------------------------- |
| `observability` schema "in place"                       | Does not exist. `bus/bootstrap.py:MODULE_SCHEMAS` lists 11 schemas, no `observability`/`ops`.       |
| Aggregates from `intake.ai_jobs`                        | Real table is `intake.intake_ai_jobs` (`modules/intake/schema/models.py:144`).                      |
| Column `latency_ms`                                     | Real column is `duration_ms`.                                                                       |
| Column `low_confidence` on `ai_jobs`                    | It lives on `intake_pre_summaries`, derived from structuring confidence vs. the 0.70 threshold.     |
| Tables `ai_usage_daily`, `ai_cost_budget`, `app_config` | None exist; the names appear only in the deleted plan doc.                                          |
| Migration `v15.0__operator_tier`                        | Head is `v8_18`; scheme is per-module `vN_M__label`. New observability schema migration is ~`v9_0`. |
| "Post-Phase 14" scope                                   | Not scheduled, not built.                                                                           |

**Already built (reuse, do not rebuild):**

- `observability/langfuse_client.py` - Langfuse singleton - **but never called**; tracing works only via `@observe` + the SDK's env-configured global client.
- `@observe` on all MOD-005 AI adapters, enforced by `scripts/check_ai_tracing.py`.
- `intake.intake_ai_jobs` metering rows; events `ai_job.completed` / `ai_job.failed` carry provider/model/tokens/cost/duration/status.
- `budget_meter.py` (advisory, Postgres-first) + `pricing.py` (`PRICING_TABLE` deliberately empty, so every cost is currently 0).
- API-only `trace_id` (`app/gateway/trace.py`); worker/outbox has no correlation id.
- Hash-chained audit (`MOD-011`) + `GET /v1/audit/events`.
- Worker APScheduler with one job (credential sweep); flat `operator` RBAC (no tier).
- Frontend operator console = 2 live pages (queue at `/operator`, detail); no Settings/Observability pages; no chart library.

**Absent:** structured logging, Sentry, Prometheus/OTel, CSP collector, nightly rollup, and every `observability` table.

---

## 3. Target architecture

```
App (Render free web - FastAPI + in-process dispatcher)
  structlog JSON  ──stdout─────────────────► Render logs
  OTel SDK        ──OTLP(HTTP)──────────────► Grafana Cloud free (Tempo/Mimir/Loki, 14d)
  Sentry SDK      ──────────────────────────► Sentry free (errors, 5k/mo)
  Langfuse @observe ────────────────────────► Langfuse Cloud free (AI spans + evals)
  outbox events ──► MOD-013 observability consumer ──► Postgres `observability` schema
                                                            ▲
  nightly rollup (GitHub Actions schedule) ─────────────────┘
                                                            ▼
  Operator dashboard (Vercel) ── read APIs ──► observability schema
                          └── deep-links out ──► Grafana / Sentry / Langfuse
```

Design rules:

- **Vendor clients are env-gated and no-op when unconfigured** (mirror the existing Langfuse/Redis no-op pattern). Local dev and CI remain unchanged until a gate is set.
- **Postgres is the system of record** for cost/quality/business aggregates, so vendor retention limits or churn never lose the decision data.
- **Aggregation never crosses schemas.** `MOD-013` consumes existing outbox events into its own schema rather than reading other modules' tables (see §7).
- **No PHI anywhere in telemetry** - redaction by key at the structlog processor, `before_send` in Sentry, and an attribute allow-list on OTel spans; pseudonymous ids only.

---

## 4. Pillars & wiring

| Pillar                     | Tool                     | Gate (disabled by default)                      | Notes                                                                             |
| :------------------------- | :----------------------- | :---------------------------------------------- | :-------------------------------------------------------------------------------- |
| Structured logs            | structlog                | `LOG_FORMAT` (`console` in dev, `json` in prod) | JSON to stdout; optional OTel log export to Grafana Loki.                         |
| Errors / crashes           | Sentry SDK               | `SENTRY_DSN` empty = off                        | `before_send` scrubs phone/OTP/free text; release = git SHA; trace_id correlated. |
| Infra + app metrics/traces | OpenTelemetry SDK (OTLP) | `OTEL_ENABLED` + endpoint/headers               | FastAPI, SQLAlchemy(async), httpx, dispatcher, APScheduler instrumentation.       |
| AI spans + cost + evals    | Langfuse SDK             | `LANGFUSE_PUBLIC_KEY` (already present)         | Wire the singleton; enrich metadata; real pricing (see §6).                       |
| Uptime                     | External free monitor    | n/a (dashboard-configured)                      | Probes `GET /health`; complements OTel, survives Render cold starts.              |
| Business/AI aggregates     | Postgres `observability` | `OBSERVABILITY_ENABLED`                         | System of record; fed by MOD-013 event consumer + nightly rollup.                 |

---

## 5. OpenTelemetry design

- **Dependencies:** `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, and instrumentation packages `-fastapi`, `-sqlalchemy`, `-httpx`, `-logging`. Use the **HTTP** OTLP exporter (gRPC is frequently blocked on PaaS free tiers).
- **Instrumentation:** FastAPI (server spans), SQLAlchemy async engine (DB spans), httpx (outbound spans for AI/SMS/WhatsApp/UPI adapters), the outbox dispatcher loop, and APScheduler jobs.
- **Resource attributes:** `service.name`, `deployment.environment`, `service.version` = git SHA.
- **Sampling:** parent-based with a `traceidratio` default well above 1.0 at low volume; configurable to keep free-tier volume bounded.
- **Trace propagation into the worker (net-new):** the API mints `trace_id` today; the outbox does not. Carry a W3C `traceparent` in the outbox row (a nullable column if the outbox payload is not already JSONB with a metadata slot) so worker spans link back to the originating request. This is the key gap that makes end-to-end traces real.
- **Shutdown flush:** force-flush the OTel/Sentry/Langfuse exporters on shutdown so Render spin-down / restarts do not drop buffered telemetry.
- **Metrics:** OTel metrics exported over OTLP to Grafana Cloud (Mimir). A Prometheus `/metrics` endpoint behind `METRICS_ENABLED` may be kept for local/backup scraping, but OTLP is the production path.
- **Logs:** structlog JSON to stdout is the baseline; the OTel logging bridge is optional and, when enabled, ships to Grafana Loki.

---

## 6. AI cost, quality & pricing

- **Fix cost = 0:** `modules/intake/pricing.py:PRICING_TABLE` is empty, so `compute_cost_paise` always returns 0 and `budget_meter.py` has no signal. Populate pricing from Settings/env (per model input/output rates in paise); free models price at 0 naturally; unknown models price at 0 and are flagged.
- **Langfuse wiring:** call `get_langfuse_client` at boot (app + worker) so tracing is explicit; keep zero behavior change when keys are absent.
- **Span metadata:** `task_type`, `provider`, `model`, `input_tokens`, `output_tokens`, `duration_ms`, `cost_paise`, `confidence`, `status`, pseudonymous `intake_id`/`ai_job_id`, `trace_id`, prompt version. **Never** transcript text, patient identity, or raw provider payloads.
- **PHI-free test:** a unit test asserts the Langfuse trace metadata admits only the allow-listed keys.

---

## 7. `observability` data model and MOD-013

### 7.1 New module `MOD-013 Observability`

Sibling of `MOD-011 Audit`: owns its own schema, consumes outbox events, exposes read APIs. Register it as the twelfth `MODULE_SCHEMAS` entry in `bus/bootstrap.py`. This is a one-schema-rule extension of the audit pattern, recorded in an ADR (§15). It is telemetry, not a domain bounded context.

### 7.2 Schema (`v9_0__init_observability`)

| Table                    | Purpose                                                                                                                            |
| :----------------------- | :--------------------------------------------------------------------------------------------------------------------------------- |
| `obs_ai_usage_daily`     | Per (date, provider, model, task_type): calls, success/failure/timeout, low-confidence, tokens, cost_paise, avg/p95 `duration_ms`. |
| `obs_ai_cost_budget`     | Per provider/model: monthly limit, alert threshold, current spend, billing period.                                                 |
| `obs_ai_provider_health` | Rolling window per provider: success rate, p50/p95/p99 `duration_ms`, breaker state, last error.                                   |
| `obs_business_daily`     | Generic registry-driven rollup (`metric_key`, `date`, `value` JSONB) so future phases add metrics without schema churn.            |
| `obs_alert_events`       | `severity`, `kind`, `title`, `payload` JSONB, `status`, `created_at`, `acked_by`.                                                  |
| `obs_consumed_events`    | Idempotency ledger (`event_id`), same pattern as every other module.                                                               |

### 7.3 Event consumer

Subscribes to the existing §4.2 registry: `ai_job.completed`, `ai_job.failed`, `case.*`, `partner.*`, `consent.*`, `record.accessed`, `audit.*`. Records `event_id` in `obs_consumed_events` before applying effects so replay is a no-op. Where an event payload lacks a needed field, register a narrow read-only exception rather than reaching into another module's tables.

---

## 8. Rollup

- **Event-driven (near-real-time):** the MOD-013 consumer accumulates counts/cost/status as events arrive.
- **Nightly job:** recompute percentile-based rollups, refresh `obs_ai_provider_health`, snapshot budget spend, and evaluate alert thresholds. Runs as a **GitHub Actions scheduled workflow** (`observability-rollup.yml`, matching `backup-drill.yml`) connecting to Supabase via a secret - Render free sleeps at 15 min idle, so an in-process cron is unreliable.
- **Backfill:** first run processes all existing `intake_ai_jobs`; subsequent runs process the previous day.

**Delivery (B5a #704 + B5b #705).** The engine is `python -m worker.rollup`; the
schedule is `.github/workflows/observability-rollup.yml` (nightly 02:45 UTC +
`workflow_dispatch`).

- **What a run covers is decided by the database, not by the workflow.** With no
  flag, the entry point reads `observability_rollup_runs` (one row per rolled UTC
  day) and plans itself: nothing recorded means the backfill sweeps the whole
  `observability_ai_usage_daily` history; otherwise it rolls every day since the
  ledger's newest entry. The steady state is the previous day, and a night the
  workflow missed is a gap the next pass fills rather than a lost day.
- **Re-run safety** is structural: every write is an upsert keyed on the rolled
  date, and the ledger row commits in the SAME transaction as the aggregates it
  describes, so the `last_rolled` marker can never advance past work that did not
  commit. Planning an already-current ledger yields no dates.
- **Budget-period reset** needs no monthly job: `observability_ai_cost_budget`
  carries a calendar-month period, so the first pass whose target date falls in
  the new month resets the closed month's spend to zero and moves the row onto the
  new period - in practice the 2nd's run, one day after the 1st's pass rolls the
  old month's last day.
- The `ai_budget` alert threshold is `AI_MONTHLY_BUDGET_PAISE`, supplied to the
  workflow as a repo **variable** so the scheduled alert and the runtime
  `BudgetMeter` compare against one cap (deployment plan §6.2).

---

## 9. Operator API & UI (Batch 1)

### 9.1 Read APIs (flat `require_operator`; tier split deferred to Batch 2)

| Route                                       | Purpose                                         |
| :------------------------------------------ | :---------------------------------------------- |
| `GET /v1/operator/observability/overview`   | Headline KPIs                                   |
| `GET /v1/operator/observability/cost`       | Spend vs budget (current period)                |
| `GET /v1/operator/observability/cost/trend` | Daily cost trend (`days=30`)                    |
| `GET /v1/operator/observability/usage`      | Calls/tokens by provider/task                   |
| `GET /v1/operator/observability/quality`    | Low-confidence rate, success rate               |
| `GET /v1/operator/observability/latency`    | p50/p95/p99 by provider/route                   |
| `GET /v1/operator/observability/health`     | Dependency + outbox health                      |
| `GET /v1/operator/observability/alerts`     | Alert feed                                      |
| `GET /v1/operator/observability/deeplinks`  | Parameterised Grafana/Sentry/Langfuse link sets |

### 9.2 Frontend

- Routes under `apps/frontend/src/app/(operator)/operator/observability/*` (overview, cost, usage, quality, health).
- `lib/operator/observability.ts` API client; `nav-config.ts` Observability entry (flip a `soon` placeholder live).
- Reuse the doctor dashboard `KpiTile`/`KpiRow` pattern (`(doctor)/doctor/page.tsx`).
- **Chart library:** shadcn/ui charts (recharts under the hood) for design-system consistency; measured against the `NFR-003` 1.5 MB page-weight gate.
- Deep-links out to Grafana/Sentry/Langfuse; inline alert feed. Since #736 each vendor's link is a SET carrying its own filters - a dashboard with its relative range and template variables, an Explore pane for one trace, a Sentry query pre-filtered to this service and error type, Langfuse views for this model/task/actor/session - and an unconfigured vendor is absent from the response rather than a `null` in it. The Grafana dashboard UID is the `GRAFANA_DASHBOARD_UID` constant in `modules/observability/domain/deeplinks.py`, which the dashboard provisioning (#748) must declare.

---

## 10. Security & Guardrails and PHI

Batch 1 keeps the foundational guardrails; full security monitoring lands in Batch 2.

**Batch 1:**

- PHI/secret redaction at the structlog processor, Sentry `before_send`, and an OTel attribute allow-list (no phone, OTP, tokens, free text, or raw payloads).
- AI-egress minimization already enforced (`AiEgressContext` rejects identity fields; Phase 7 guardrail test) - surfaced as a monitored signal, not rebuilt.
- Audit-tamper events (`audit.tamper_detected`) surfaced in the alert feed.

**Batch 2:** CSP report-only + a report-uri collector endpoint, XSS sanitizer, auth-failure/lockout and consent/rate-limit anomaly detectors, webhook-signature-failure monitoring, prompt-injection heuristics, alert routing (Slack/email).

---

## 11. SLOs & alerting

- Define SLOs from existing NFRs and whitebox latency SLAs: auth `validate_token` p95 < 100 ms, `verify_otp` p95 < 400 ms, directory search p95 < 250 ms, AI call p95 <= 30 s, care-loop latency (`KPI-008`), error rate < 1%.
- Minimum alert set (`error-handling-observability.md` §5) plus: audit tamper, backup failure, AI budget meter > 80%, outbox backlog > threshold, circuit-breaker open, dead-letter row, provider health drop.
- Alert delivery via free channels: Sentry alerts, Grafana Cloud alerting to email/Slack webhook; the in-app `obs_alert_events` feed is the operator-visible record. No PHI in alert payloads.

---

## 12. Batch 1 ticket breakdown

| #   | Ticket                                                                     | Blocked by | Est. |
| :-- | :------------------------------------------------------------------------- | :--------- | :--- |
| A1  | structlog JSON logging + redaction (app/worker/dispatcher)                 | -          | M    |
| A2  | Trace-context propagation API -> outbox -> worker                          | -          | M    |
| A3  | OTel SDK + FastAPI/SQLAlchemy/httpx/dispatcher instrumentation + OTLP gate | A1         | L    |
| A4  | Sentry integration + PHI scrub + release tracking                          | A1         | S    |
| A5  | Observability Settings gates + `.env.example` + `render.yaml`              | -          | S    |
| B1  | Real AI pricing table (fix cost = 0)                                       | A5         | S    |
| B2  | Wire Langfuse singleton + enrich spans + PHI-free test                     | A5         | S    |
| B3  | MOD-013 scaffold + `v9_0__init_observability` + bootstrap registration     | A5         | M    |
| B4  | Event consumer -> usage/provider-health aggregates + idempotency ledger    | B3         | L    |
| B5  | Registry rollup + nightly GitHub Actions job + budget reset                | B4         | M    |
| C1  | Operator observability read APIs + RBAC                                    | B4,B5      | M    |
| C2  | Operator Observability tab + charts + nav + client                         | C1         | L    |
| C3  | Deep-links (Grafana/Sentry/Langfuse) + alert feed                          | C1         | S    |
| D   | Docs/ADRs/roadmap/standards/CONTEXT reconciliation                         | -          | M    |
| E   | Combined review + E2E                                                      | A1-C3,D    | M    |

---

## 13. Deferred to Batch 2

- Operator admin/non-admin (`operator_tier`) schema, JWT claim, and tier RBAC decorator.
- Settings tab: AI config, notification config, feature flags, user management.
- **Langfuse Evals:** datasets, LLM-as-judge (completeness, confidence calibration, rx-draft accuracy), annotation queue fed by doctor review outcomes.
- Full Security & Guardrails monitoring (CSP report-uri, sanitizer, anomaly detectors, injection heuristics, alert routing).
- SLO formalization + business-metrics dashboards populated by Phases 9-13 data (`obs_business_daily` registry makes this additive).

---

## 14. Docs & ADR changes

- **ADRs:** (1) observability topology and free-tier vendor choices; (2) `MOD-013` + `observability` schema registration (one-schema-rule extension of the audit pattern); (3) OpenTelemetry adoption.
- **`docs/architecture/system-context.md`:** add observability vendor entries (`EXT-005` Langfuse, `EXT-006` Grafana Cloud, `EXT-007` Sentry).
- **`docs/architecture/internal-modules.md`:** `MOD-013` spec; §4.1 sync matrix, §4.2 event subscriptions, §5 traceability.
- **`docs/roadmap/implementation-roadmap.md`:** add `PHASE-14A - Observability & Monitoring Platform`; retitle the remaining release gate as `PHASE-14B`. Reconcile the `ops` tables: `cost_meters` subsumed by `obs_ai_cost_budget`; `restore_validations` / `e2e_runs` stay with `PHASE-14B`.
- **`docs/standards/error-handling-observability.md`:** update §5 to the new stack and SLO list.
- **`docs/standards/ai-engineering-standards.md` A7:** correct `latency_ms` -> `duration_ms`; add eval detail.
- **`docs/plans/deployment-plan/portfolio-deployment-plan.md`:** add Sentry/OTel/Grafana env vars.
- **`CONTEXT.md`:** register this plan.

---

## 15. Risks

| Risk                                                      | Mitigation                                                                   |
| :-------------------------------------------------------- | :--------------------------------------------------------------------------- |
| Free-tier ceilings (Grafana 14d, Sentry 5k, Langfuse 50k) | Postgres system of record; sampling; alert on quota.                         |
| PHI leakage into third-party telemetry                    | Processor redaction, `before_send` scrub, span attribute allow-list, tests.  |
| Render spin-down drops buffered telemetry                 | Force-flush exporters on shutdown; uptime monitor for availability.          |
| Bundle budget (`NFR-003`)                                 | Charts measured against the 1.5 MB page-weight gate.                         |
| Module-isolation violation                                | Aggregation only via outbox events; no cross-schema SQL.                     |
| Migration complexity                                      | Single-head gate (`npm run migration-check`); one additive `v9_0` migration. |
| OTel overhead / cost                                      | Configurable sampler; HTTP exporter; gate off by default.                    |

---

## 16. Verification

- Repo harness: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend|frontend`, `npm run migration-check`.
- New tests: OTel/structlog/Sentry no-op when unconfigured; structlog redaction; Sentry scrub; Langfuse PHI-free metadata; consumer idempotency (`event_id` replay = one row); rollup correctness against seeded `intake_ai_jobs`; operator observability routes RBAC.
- E2E: an operator opens the Observability tab and sees population from seeded data; deep-links resolve.
- CI gate: `ci.yml` builds the observability gates on and off so the no-op path cannot rot.

---

## 17. Implementation order

1. A5 (config gates) -> A1 (logging) -> A2 (trace propagation) -> A4 (Sentry) -> A3 (OTel).
2. B1 (pricing) -> B2 (Langfuse) -> B3 (module + schema) -> B4 (consumer) -> B5 (rollup + nightly).
3. C1 (APIs) -> C2 (dashboard) -> C3 (deep-links + alerts).
4. D (docs) threaded alongside; E (review + E2E) last.

---

## Appendix A - Carried-forward hardening (was `plan-post-phase14-observability.md` §7)

The production-readiness audit (deleted `docs/plans/production-readiness-audit.md`) recommendations are preserved here. This appendix remains the source of truth for those items. Items overlapping Batch 1 reference the ticket above; the rest are scheduled with `PHASE-14B` or as noted.

### A.1 Prioritised table

| #   | Item                                                           | Grade  | When  | Overlap / home                  |
| :-- | :------------------------------------------------------------- | :----- | :---- | :------------------------------ |
| 1   | Structured JSON logging (structlog)                            | C      | Now   | Batch 1 -> A1                   |
| 2   | Error tracking (Sentry or equiv)                               | High   | Now   | Batch 1 -> A4                   |
| 3   | Basic metrics + `/metrics` (prometheus-fastapi-instrumentator) | C      | Now   | Batch 1 -> A3 (OTel primary)    |
| 4   | Cache hit/miss counters on Redis caches                        | C      | Now   | Batch 1 -> A3                   |
| 5   | CSP header (report-only first)                                 | High   | Now   | Batch 2 (Security & Guardrails) |
| 6   | XSS / HTML sanitizer (bleach/nh3)                              | High   | Now   | Batch 2 (Security & Guardrails) |
| 7   | SQLAlchemy pool sizing config                                  | C+     | Now   | `PHASE-14B` (config-only)       |
| 8   | Dockerfile for backend                                         | C+     | Now   | `PHASE-14B` (additive)          |
| 9   | Redis-backed distributed rate limiter                          | C      | Later | Launch prep / multi-instance    |
| 10  | Rate limiting beyond `/v1/auth/*`                              | C      | Later | Depends on #9                   |
| 11  | Redis-backed idempotency store                                 | C+     | Later | Multi-instance only             |
| 12  | Business metrics dashboard (funnel, OTP, consent rate)         | Medium | Later | Batch 2 (`obs_business_daily`)  |

### A.2 Safety pattern (applies to all items)

(a) Additive-only; (b) feature-flagged behind `Settings` env vars, disabled by default; (c) graceful degradation - init failure never takes the app down (mirror the Redis no-op pattern); (d) no PostgreSQL schema changes except the `v9_0` observability migration; (e) backend-only, no frontend or session/CORS changes (`ADR-0007`).

### A.3 Ship-now detail

- **Structured JSON logging** -> A1. `LOG_FORMAT` (`json` | `console`).
- **Sentry** -> A4. `SENTRY_DSN` gate, release = git SHA, `before_send` scrub.
- **Metrics** -> A3. OTel metrics as primary; optional `/metrics` behind `METRICS_ENABLED`; request latency histograms, error counters, cache hit/miss counters.
- **Cache counters** -> A3. Counters on `consent/redis_cache.py` and `partner/directory_cache.py`; zero behavior change.
- **CSP report-only** -> Batch 2. `Content-Security-Policy-Report-Only` in `app/gateway/security_headers.py` behind `CSP_REPORT_ONLY`; enforce-mode flip verified against the deployed Vercel frontend (`ADR-0007`).
- **XSS sanitizer** -> Batch 2. `nh3`/`bleach` util wired where free text is stored/rendered.
- **SQLAlchemy pool sizing** -> `PHASE-14B`. Pool size / max_overflow / pool_timeout via `Settings`; defaults for the single Render instance.
- **Backend Dockerfile** -> `PHASE-14B`. Multi-stage build; enables local parity and the future horizontal-scaling path.

### A.4 Later detail

Redis-backed distributed rate limiter, per-user/per-route rate limiting, Redis-backed idempotency store, horizontal-scaling runbook, and the business-metrics dashboard stay deferred until real traffic or the single-VM path (`ADR-0007`). The outbox poll loop stays a single process by design (exactly-one-worker rule).
