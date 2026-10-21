# Phase 14A - Observability & Monitoring Platform Plan

**Status:** Batch 1 delivered (#693-#716). Batch 3's feature waves are delivered (#718-#754); the closeout is still open - #755 (this reconciliation), #756 (E2E across the redesigned sidebar) and #757 (combined review) close the wave. Batch 2 was never ticket-rolled: Batch 3 superseded the parts of it an operator actually needed, and §13 states precisely what is still deferred.
**Scope:** Carve the observability slice out of roadmap `PHASE-14` (`docs/roadmap/implementation-roadmap.md` §2.14), pull it forward to the current build point (Phase 8 + doctor-console batches), and expand it into a production monitoring system whose primary surface is the Operator dashboard, backed by third-party free tiers and OpenTelemetry.
**Supersedes:** `docs/plans/plan-post-phase14-observability.md` (deleted 2026-10-12; its still-relevant production-readiness items are carried forward in Appendix A below).
**Depends on:** Phase 8 complete (current), `plan-phase7-tracing-prep.md` implemented (Langfuse SDK + config + tracing gate in place).
**Does NOT cover:** the roadmap's full-loop E2E test suite and the launch/restore release gate - those stay in `PHASE-14B` (release readiness) because they cannot run until Phases 9-13 exist.

---

## 0. Locked decisions

| Decision               | Choice                                                                                                                           |
| :--------------------- | :------------------------------------------------------------------------------------------------------------------------------- |
| Topology               | Hybrid free tiers: Langfuse Cloud + Sentry + Grafana Cloud free for pillars; Postgres `observability` schema is system of record |
| Budget posture         | Strict free tiers only (`NFR-001`); no new recurring spend                                                                       |
| First delivered slice  | Foundation + AI/cost + errors + operator dashboard (Batch 1 - see §12)                                                           |
| Second delivered slice | Business + reliability + product analytics and the operator console IA redesign (Batch 3, #717 - see §12.1)                      |
| Plan artifact          | This document + `/to-tickets`                                                                                                    |
| Tracing depth          | Full OpenTelemetry now (traces + metrics + logs via OTLP)                                                                        |

---

## 1. Goal

Stand up an advanced monitoring system around CareSetu so the operator can observe, alert on, and act on production behaviour across seven concern areas - without violating `NFR-001` (no paid observability) or the module-isolation rule (`ADR-0003`):

1. **Application monitoring** - uptime/health, request latency/error rate, dependency health.
2. **Observability** - distributed traces, metrics, structured logs, correlation.
3. **Logging** - queryable structured JSON, trace-correlated, PHI-free.
4. **Latency & cost monitoring** - per-route and per-AI-task latency; real AI spend vs budget, per provider/model/task.
5. **Security & Guardrails** - audit-tamper, auth-failure/lockout, rate-limit/consent anomalies, webhook signature failures, CSP violations, AI-egress/PHI guardrails.
6. **Failures** - exception tracking, outbox backlog/dead-letter, circuit-breaker opens, degradation counts.
7. **Evals** - the golden dataset and the code evaluators over it, the annotation queue fed by doctor review outcomes, and LLM-as-judge (still deferred).

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

### 7.2 Schema (`v9_0__init_observability`, extended through `v9_7`)

Batch 1 (`v9_0`, `v9_1`):

| Table                              | Purpose                                                                                                                                                                       |
| :--------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `observability_ai_usage_daily`     | Per (date, provider, model, task type): calls, success/failure/timeout, low-confidence, tokens, cost_paise, avg/p95 `duration_ms`.                                            |
| `observability_ai_cost_budget`     | Per provider/model: monthly limit, alert threshold, current spend, billing period.                                                                                            |
| `observability_ai_provider_health` | Rolling window per provider: success rate, p50/p95/p99 `duration_ms`, breaker state, last error, plus the `timeout_count` and `rate_limit_count` columns `v9_4` adds.         |
| `observability_business_daily`     | Generic registry-driven rollup (`metric_key`, `metric_date`, `value` JSONB) so future phases add metrics without schema churn.                                                |
| `observability_alert_events`       | `severity`, `kind`, `title`, `payload` JSONB, `status`, `created_at`, `acked_by`, `acked_at`.                                                                                 |
| `observability_rollup_runs`        | One row per rolled UTC day, so the nightly rollup can plan its own coverage (`v9_1`).                                                                                         |
| `consumed_events`                  | Idempotency ledger (`event_id`), same pattern as every other module; the one table here whose name carries no `observability_` prefix, because `bus/outbox_ddl.py` builds it. |

Batch 3 adds ten more tables, all additive on the same single-head chain: `observability_ai_job_spend`, `observability_care_attribution_edges` and `observability_attribution_daily` (`v9_2`), `observability_error_events`, `observability_http_minute`, `observability_product_events` and `observability_product_daily` (`v9_3`), `observability_ai_queue_open` (`v9_5`), `observability_product_actor_daily` (`v9_6`), and `observability_evaluation_scores` (`v9_7`). The per-table purpose and the ticket that owns each one live in `docs/architecture/internal-modules.md` `MOD-013` §3.14.

### 7.3 Event consumer

Subscribes to the §4.2 registry: `ai_job.queued`, `ai_job.completed`, `ai_job.failed`, `intake.doctor_assigned`, `intake.composer_opened`, `case.*`, `partner.*`, `consent.*`, `record.accessed`, `audit.*`. Batch 3 published three of these names itself - `ai_job.queued` (#729), `intake.doctor_assigned` (#720) and `intake.composer_opened` (#721) - and the rest were already registered. Records `event_id` in `consumed_events` before applying effects so replay is a no-op. Where an event payload lacks a needed field, register a narrow read-only exception rather than reaching into another module's tables.

---

## 8. Rollup

- **Event-driven (near-real-time):** the MOD-013 consumer accumulates counts/cost/status as events arrive.
- **Nightly job:** recompute percentile-based rollups, refresh `observability_ai_provider_health`, snapshot budget spend, and evaluate alert thresholds. Runs as a **GitHub Actions scheduled workflow** (`observability-rollup.yml`, matching `backup-drill.yml`) connecting to Supabase via a secret - Render free sleeps at 15 min idle, so an in-process cron is unreliable.
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

Batch 3 added three lenses over the same `observability` schema - business, reliability and product - and rebuilt the operator shell around them (§12.1). Those surfaces are the tickets' own scope, not this plan's.

---

## 10. Security & Guardrails and PHI

Batch 1 keeps the foundational guardrails; full security monitoring lands in Batch 2, which was never ticket-rolled - §13 records what of it is still deferred.

**Batch 1:**

- PHI/secret redaction at the structlog processor, Sentry `before_send`, and an OTel attribute allow-list (no phone, OTP, tokens, free text, or raw payloads).
- AI-egress minimization already enforced (`AiEgressContext` rejects identity fields; Phase 7 guardrail test) - surfaced as a monitored signal, not rebuilt.
- Audit-tamper events (`audit.tamper_detected`) surfaced in the alert feed.

**Batch 2:** CSP report-only + a report-uri collector endpoint, XSS sanitizer, auth-failure/lockout and consent/rate-limit anomaly detectors, webhook-signature-failure monitoring, prompt-injection heuristics, alert routing (Slack/email).

**Batch 3:** the reliability lens added symptom-based alerting with auto-resolution and an operator acknowledgement write (#734, #735), and the SLOs were formalised in `ADR-0030` (#754). It brought in none of the Batch 2 security work - no CSP collector, no sanitizer, no anomaly detectors, no injection heuristics, no Slack/email routing. Those stay deferred (§13).

---

## 11. SLOs & alerting

- Define SLOs from existing NFRs and whitebox latency SLAs: auth `validate_token` p95 < 100 ms, `verify_otp` p95 < 400 ms, directory search p95 < 250 ms, AI call p95 <= 30 s, care-loop latency (`KPI-008`), error rate < 1%.
- Minimum alert set (`error-handling-observability.md` §5) plus: audit tamper, backup failure, AI budget meter > 80%, outbox backlog > threshold, circuit-breaker open, dead-letter row, provider health drop.
- Alert delivery via free channels: Sentry alerts, Grafana Cloud alerting to email/Slack webhook; the in-app `observability_alert_events` feed is the operator-visible record. No PHI in alert payloads.
- Since #754 these are formalised rather than implied: `docs/adr/0030-service-level-objectives-and-symptom-alerting.md` fixes the objective set, the symptom-vs-cause split and the accepted-risk register (`docs/adr/0031-accepted-risk-ai-tracing-vendor-free-tier.md`).

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

### 12.1 Batch 3 ticket breakdown

Batch 3 is #717: Business, Reliability and Product analytics + the operator console IA redesign. Forty tickets in five waves. It added no new module and no new schema - the ten Batch 3 tables land inside the existing `observability` schema - and it reads only events in the §4.2 registry: most of them were already there, and the three it published itself (`ai_job.queued`, `intake.doctor_assigned`, `intake.composer_opened`) are now registered. The producer-side tickets (#719-#722 and #729) land in `MOD-005`; the rest in `MOD-013`.

### Wave 1 - Identity and capture foundation (#718-#729)

| #   | Ticket                                                               | Delivers                                                                            |
| :-- | :------------------------------------------------------------------- | :---------------------------------------------------------------------------------- |
| 718 | Consolidate observability integration fixtures                       | one fixture set for the whole module, so the waves do not each grow their own       |
| 719 | AI job events carry the patient, a nullable doctor and the trace id  | the widened `ai_job.*` payload - attribution without a join                         |
| 720 | Care-attributed event at doctor selection                            | `intake.doctor_assigned`, published with the doctor assignment                      |
| 721 | Composer-opened funnel entry step                                    | `intake.composer_opened`, the product funnel's first step                           |
| 722 | Meter the prescription-drafting leg                                  | the third AI leg metered on the same events, `doctor_id` null                       |
| 723 | Attribution table set and per-job AI spend rows                      | `observability_ai_job_spend` and the attribution tables - the granular spend source |
| 724 | Care-attribution edge table fed by the care-attributed event         | `observability_care_attribution_edges` - one edge per intake, one doctor            |
| 725 | Daily per-actor attribution aggregate with nullable revenue and tier | `observability_attribution_daily`, recomputed in full each pass                     |
| 726 | Gateway error capture and the runtime capture table set              | `observability_error_events` - the fingerprint-collapsed live error stream          |
| 727 | Per-minute HTTP counter, throughput and error rate                   | `observability_http_minute`, one row per route per minute                           |
| 728 | Degraded provider board with the last error written                  | the provider board's last error, written from the per-job grain                     |
| 729 | Queue depth and oldest age with a high queue-age alert               | `observability_ai_queue_open` - the open set, so depth is exact and age is real     |

### Wave 2 - Business, reliability and product reads (#730-#743)

| #   | Ticket                                                                      | Delivers                                                                  |
| :-- | :-------------------------------------------------------------------------- | :------------------------------------------------------------------------ |
| 730 | Live error feed read                                                        | `GET .../errors`                                                          |
| 731 | Business read: period spend, cap, projected burn and breakdown              | `GET .../business` - period spend and the cap                             |
| 732 | Business read: unit metrics, attribution and the not-captured margin reason | unit metrics and the attribution breakdown                                |
| 733 | Cost-outlier alert from the actor's own trailing baseline                   | the cost-outlier alert kind                                               |
| 734 | Reliability alert kinds with the auto-resolve policy                        | the alert kinds and the auto-resolve policy                               |
| 735 | Alert acknowledgement endpoint                                              | `POST .../alerts/{alert_id}/acknowledge`                                  |
| 736 | Parameterised deep links                                                    | each vendor link as a set carrying its own filters                        |
| 737 | Business lens page                                                          | `operator/observability/business`                                         |
| 738 | Reliability lens page                                                       | `operator/observability/reliability`                                      |
| 739 | Product event ledger, funnel-step registry and daily rollup                 | `observability_product_events`, `observability_product_daily`             |
| 740 | Funnel read                                                                 | `GET .../product/funnel`                                                  |
| 741 | Active users read                                                           | `GET .../product/active-users`                                            |
| 742 | Retention cohorts read                                                      | `GET .../product/retention-cohorts` + `observability_product_actor_daily` |
| 743 | Product lens page                                                           | `operator/observability/product`                                          |

### Wave 3 - Operator console IA (#744-#747)

| #   | Ticket                                                            | Delivers                                                 |
| :-- | :---------------------------------------------------------------- | :------------------------------------------------------- |
| 744 | Nav configuration children and prefix-matched parent active state | one nav config drives the whole console tree             |
| 745 | Operator sidebar groups with the Observability disclosure         | grouped sidebar with a collapsible Observability section |
| 746 | Mobile bottom bar and More sheet from one configuration           | the mobile bar and its More sheet, from the same config  |
| 747 | Sub-navigation replaces the page-level panel strip                | sub-navigation as the page-level navigation              |

### Wave 4 - Vendor assets and evaluation (#748-#753)

| #   | Ticket                                                             | Delivers                                                                      |
| :-- | :----------------------------------------------------------------- | :---------------------------------------------------------------------------- |
| 748 | Grafana dashboards, datasource and alert rules as repository files | `deploy/grafana/` - dashboards, datasource, alert rules                       |
| 749 | OpenTelemetry collector configuration as the cardinality firewall  | the collector config that bounds label cardinality                            |
| 750 | Langfuse daily batch pull into the observability schema            | the daily Langfuse pull into `observability`                                  |
| 751 | Code evaluators over a synthetic golden dataset                    | code evaluators over a golden dataset, into `observability_evaluation_scores` |
| 752 | Annotation queue fed by doctor review outcomes                     | the annotation rows in `observability_evaluation_scores`                      |
| 753 | New configuration gates and CI gate-job coverage                   | the new Settings gates, plus the CI job that runs them on                     |

### Wave 5 - Closeout (#754-#757)

| #   | Ticket                                                                | Delivers                                                    |
| :-- | :-------------------------------------------------------------------- | :---------------------------------------------------------- |
| 754 | Design records, service level objectives and the accepted-risk record | `ADR-0027`..`ADR-0031`                                      |
| 755 | Docs reconciliation: event registry, plan status, traceability        | this section, §13, the §4.2 footnotes, §5 rows, the roadmap |
| 756 | End-to-end pass across the redesigned sidebar                         | E2E over the Batch 3 IA                                     |
| 757 | Combined review of Batch 3 with fixes applied                         | the two-axis review and its fixes                           |

---

## 13. Deferred to Batch 2 (reconciled after Batch 3)

Batch 2 was never ticket-rolled. Batch 3 superseded the parts of it an operator actually needed; what follows is now the record of what is still deferred and what is not.

**Superseded by Batch 3:**

- Business and product dashboards. The Business lens, the product funnel / active-user / retention reads and their pages (#731-#743) replaced the "business-metrics dashboard populated by Phases 9-13 data" aspiration with what today's events can actually compute. The dashboard is delivered; only the Phases 9-13 population is outstanding, because those phases do not exist.
- SLO formalization. `ADR-0030` (#754) fixes the objective set, the symptom-vs-cause split and the accepted-risk register, so this is no longer a deferral.
- Evals, part one. The Langfuse daily batch pull, the code evaluators over a synthetic golden dataset and the annotation queue fed by doctor review outcomes (#750-#752) landed - the evaluator scores and the annotation rows live in the `observability` schema, not in the vendor.
- Reliability alerting, part one. The alert kinds, the auto-resolve policy and the operator acknowledgement write (#734, #735) landed.

**Still deferred:**

- Operator admin/non-admin (`operator_tier`) schema, JWT claim, and tier RBAC decorator. Batch 3 shipped the navigation shell only.
- Settings tab: AI config, notification config, feature flags, user management. `operator/observability/settings` is a placeholder destination, not a settings surface.
- **Evals, part two:** LLM-as-judge (completeness, confidence calibration, rx-draft accuracy), judge-vs-human agreement measurement, and the richer dataset workflow on top of the golden dataset and the annotation queue.
- **Full Security & Guardrails monitoring:** CSP report-only plus the report-uri collector, the XSS/HTML sanitizer, auth-failure/lockout and consent/rate-limit anomaly detectors, webhook-signature-failure monitoring, prompt-injection heuristics, and Slack/email alert routing. Batch 3's reliability work is symptom alerting over the `observability` schema, which is a different thing.

---

## 14. Docs & ADR changes

- **ADRs:** (1) observability topology and free-tier vendor choices; (2) `MOD-013` + `observability` schema registration (one-schema-rule extension of the audit pattern); (3) OpenTelemetry adoption.
- **`docs/architecture/system-context.md`:** add observability vendor entries (`EXT-005` Langfuse, `EXT-006` Grafana Cloud, `EXT-007` Sentry).
- **`docs/architecture/internal-modules.md`:** `MOD-013` spec; §4.1 sync matrix, §4.2 event subscriptions, §5 traceability.
- **`docs/roadmap/implementation-roadmap.md`:** add `PHASE-14A - Observability & Monitoring Platform`; retitle the remaining release gate as `PHASE-14B`. Reconcile the `ops` tables: `cost_meters` subsumed by `observability_ai_cost_budget`; `restore_validations` / `e2e_runs` stay with `PHASE-14B`.
- **`docs/standards/error-handling-observability.md`:** update §5 to the new stack and SLO list.
- **`docs/standards/ai-engineering-standards.md` A7:** correct `latency_ms` -> `duration_ms`; add eval detail.
- **`docs/plans/deployment-plan/portfolio-deployment-plan.md`:** add Sentry/OTel/Grafana env vars.
- **`CONTEXT.md`:** register this plan.

**Batch 3 (docs deltas across the wave, #718-#757):**

- **ADRs:** `docs/adr/0027-cost-attribution-model-event-carried-doctor-attribution.md` (attribution rides the event, not a join), `0028-product-analytics-in-the-system-of-record.md` (the ledger is the system of record), `0029-console-and-grafana-split-and-the-cardinality-firewall.md` (console vs Grafana, and the collector as the firewall), `0030-service-level-objectives-and-symptom-alerting.md`, `0031-accepted-risk-ai-tracing-vendor-free-tier.md`. `0024` and `0025` also carry Batch 3 corrections: `0024` gains the consequence that its "(later) evals" landed in Postgres, and `0025`'s `obs_*` table shorthand becomes the real `observability_*` names.
- **`docs/architecture/internal-modules.md`:** `MOD-013` §3.14 storage list (the ten Batch 3 tables); §4.1 sync matrix (the Batch 3 read surfaces); §4.2 footnotes for the widened `ai_job.*` payload, the `intake.doctor_assigned` edge and the three metered AI legs; §5 traceability rows for the Batch 3 lenses, the console IA and the vendor assets.
- **`docs/architecture/system-context.md`:** the `EXT-005` (Langfuse) description - the evals and the annotation queue are Batch 3, and they run in the `observability` schema, not in the vendor.
- **`docs/standards/ai-engineering-standards.md`:** A7 - the evals bullet now says what landed (#750-#752) and what is still deferred (LLM-as-judge).
- **`docs/standards/coding-standards.md`:** the private-schema count is 12, not 11 - `observability` is the twelfth.
- **`docs/roadmap/implementation-roadmap.md`:** `PHASE-14A` §2.14a Batch 3 scope, schema delta and deferred list; the §3 phased traceability matrices.
- **`docs/plans/plan-phase14-observability.md`:** §7.2 (the schema, `v9_0`..`v9_7`), §12.1 (the Batch 3 ticket breakdown), §13 (the reconciled deferral list).
- **`CONTEXT.md`:** the nav guide points at the Batch 3 section.

---

## 15. Risks

| Risk                                                      | Mitigation                                                                                                      |
| :-------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------- |
| Free-tier ceilings (Grafana 14d, Sentry 5k, Langfuse 50k) | Postgres system of record; sampling; alert on quota.                                                            |
| PHI leakage into third-party telemetry                    | Processor redaction, `before_send` scrub, span attribute allow-list, tests.                                     |
| Render spin-down drops buffered telemetry                 | Force-flush exporters on shutdown; uptime monitor for availability.                                             |
| Bundle budget (`NFR-003`)                                 | Charts measured against the 1.5 MB page-weight gate.                                                            |
| Module-isolation violation                                | Aggregation only via outbox events; no cross-schema SQL.                                                        |
| Migration complexity                                      | Single-head gate (`npm run migration-check`); the additive `v9_0`..`v9_7` chain, no rewrite of a shipped table. |
| OTel overhead / cost                                      | Configurable sampler; HTTP exporter; gate off by default.                                                       |

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

| #   | Item                                                           | Grade  | When  | Overlap / home                                                                                                                                                             |
| :-- | :------------------------------------------------------------- | :----- | :---- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Structured JSON logging (structlog)                            | C      | Now   | Batch 1 -> A1                                                                                                                                                              |
| 2   | Error tracking (Sentry or equiv)                               | High   | Now   | Batch 1 -> A4                                                                                                                                                              |
| 3   | Basic metrics + `/metrics` (prometheus-fastapi-instrumentator) | C      | Now   | Batch 1 -> A3 (OTel primary)                                                                                                                                               |
| 4   | Cache hit/miss counters on Redis caches                        | C      | Now   | Batch 1 -> A3                                                                                                                                                              |
| 5   | CSP header (report-only first)                                 | High   | Now   | Batch 2 (Security & Guardrails)                                                                                                                                            |
| 6   | XSS / HTML sanitizer (bleach/nh3)                              | High   | Now   | Batch 2 (Security & Guardrails)                                                                                                                                            |
| 7   | SQLAlchemy pool sizing config                                  | C+     | Now   | `PHASE-14B` (config-only)                                                                                                                                                  |
| 8   | Dockerfile for backend                                         | C+     | Now   | `PHASE-14B` (additive)                                                                                                                                                     |
| 9   | Redis-backed distributed rate limiter                          | C      | Later | Launch prep / multi-instance                                                                                                                                               |
| 10  | Rate limiting beyond `/v1/auth/*`                              | C      | Later | Depends on #9                                                                                                                                                              |
| 11  | Redis-backed idempotency store                                 | C+     | Later | Multi-instance only                                                                                                                                                        |
| 12  | Business metrics dashboard (funnel, OTP, consent rate)         | Medium | Later | Batch 3 delivered the Business and Product lenses (#731-#743) over `observability_business_daily` and `observability_product_*`; the Phases 9-13 population stays deferred |

### A.2 Safety pattern (applies to all items)

(a) Additive-only; (b) feature-flagged behind `Settings` env vars, disabled by default; (c) graceful degradation - init failure never takes the app down (mirror the Redis no-op pattern); (d) no PostgreSQL schema changes except the `observability` migrations (`v9_0`..`v9_7`); (e) backend-only, no frontend or session/CORS changes (`ADR-0007`).

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

Redis-backed distributed rate limiter, per-user/per-route rate limiting, Redis-backed idempotency store, horizontal-scaling runbook, and the business-metrics dashboard stay deferred until real traffic or the single-VM path (`ADR-0007`). The business-metrics dashboard is delivered as far as today's events allow (Batch 3 delivered the Business and Product lenses, #731-#743); what remains is its population from Phases 9-13, which do not exist yet. The security-and-guardrails programme is deferred on its own track (plan §10, §13), not on the traffic or single-VM trigger. The outbox poll loop stays a single process by design (exactly-one-worker rule).
