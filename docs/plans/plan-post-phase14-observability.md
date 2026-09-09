# Post-Phase 14 Observability, Admin & Settings Plan

**Status:** ready for `/to-tickets`
**Scope:** Two post-Phase 14 workstreams: (1) observability / operator admin & settings features, and (2) the production-readiness remediation items carried from `docs/plans/production-readiness-audit.md` (superseded by section 7 below). Both implement after Phase 14 (E2E Integration, Observability & Release).
**Depends on:** Phase 14 complete, Phase 7 tracing prep (plan-phase7-tracing-prep.md) complete, `observability` schema + Langfuse SDK in place.
**Estimated effort:** 5-8 days, workstream 1 (operator split + settings UI + observability dashboard + cron) + workstream 2 (audit remediation, section 7 - harden, ~4-6 days)

## 1. Goal

After the full care loop is built and verified (Phases 7-14), implement:

1. Operator admin/non-admin role split with RBAC enforcement
2. Admin Settings tab (AI config, notification config, feature flags, user management)
3. Admin Observability tab (cost dashboard, usage metrics, quality indicators, Langfuse deep-link)
4. Full nightly rollup cron implementation (backfill from `ai_jobs`)

This completes the operator console as a real admin surface and makes the AI observability data actionable.

## 2. What gets built

| #    | Deliverable                                 | Where                                  | Depends On                             |
| ---- | ------------------------------------------- | -------------------------------------- | -------------------------------------- |
| 2.1  | Operator admin/non-admin schema + migration | `iam` schema                           | Nothing                                |
| 2.2  | RBAC extension for admin/non-admin routes   | Gateway middleware + `MOD-001`         | 2.1                                    |
| 2.3  | Settings tab - AI config panel              | Operator console frontend + API routes | 2.1, 2.2                               |
| 2.4  | Settings tab - Notification config panel    | Operator console frontend + API routes | 2.1, 2.2                               |
| 2.5  | Settings tab - Feature flags panel          | Operator console frontend + API routes | 2.1, 2.2                               |
| 2.6  | Settings tab - User management panel        | Operator console frontend + API routes | 2.1, 2.2                               |
| 2.7  | Observability tab - Cost dashboard          | Operator console frontend + API routes | 2.8                                    |
| 2.8  | Observability tab - Usage & quality metrics | Operator console frontend + API routes | 2.8                                    |
| 2.9  | Nightly rollup cron full implementation     | Worker (APScheduler)                   | `observability` schema, `ai_jobs` data |
| 2.10 | Langfuse evaluation setup                   | Langfuse Cloud UI + SDK                | Langfuse account                       |

## 3. Detailed work items

### 3.1 Operator Admin/Non-Admin Schema

**What:** Extend the IAM identity model to support two tiers of operators.

**Migration:** `v15.0__operator_tier.sql`

```sql
-- Add operator_tier to iam_identities
ALTER TABLE iam.iam_identities
    ADD COLUMN operator_tier TEXT DEFAULT NULL;

-- Constraint: only 'admin' or 'operator' when set
ALTER TABLE iam.iam_identities
    ADD CONSTRAINT chk_operator_tier
    CHECK (operator_tier IN ('admin', 'operator') OR operator_tier IS NULL);

-- Backfill: all existing operators become admin
UPDATE iam.iam_identities
SET operator_tier = 'admin'
WHERE id IN (
    SELECT identity_id FROM iam.iam_role_grants
    WHERE role = 'operator' AND status = 'Active'
);

-- Index for RBAC lookups
CREATE INDEX idx_identities_operator_tier ON iam.iam_identities(operator_tier)
    WHERE operator_tier IS NOT NULL;
```

**Why `operator_tier` on `iam_identities` (not a separate table):**

- Operators are already identified via `iam_identities` + `iam_role_grants`
- Adding a column is the minimal schema change
- Tier is an attribute of the identity, not a separate entity
- No new table means no new migration complexity

**JWT claim extension:**
The `issue_operator_session` method in `MOD-001` already issues JWTs for operators. Extend the JWT payload to include `operator_tier`:

```python
# In issue_operator_session, add to JWT claims:
claims = {
    "sub": identity_id,
    "scope": "operator",
    "operator_tier": identity.operator_tier,  # NEW
    "exp": expiry,
    "jti": session_jti,
}
```

### 3.2 RBAC Extension for Admin/Non-Admin

**What:** Route-level access enforcement based on `operator_tier`.

**Route access matrix:**

| Route Pattern                            | Method       | Admin | Non-Admin       | Description                           |
| ---------------------------------------- | ------------ | ----- | --------------- | ------------------------------------- |
| `/v1/partner/verification-queue`         | GET          | Yes   | Yes             | Verification queue list               |
| `/v1/partner/verification/{id}`          | GET          | Yes   | Yes             | Verification detail                   |
| `/v1/partner/verification/{id}/decision` | POST         | Yes   | Yes             | Approve/reject decision               |
| `/v1/audit/events`                       | GET          | Yes   | Yes (read-only) | Audit trail query                     |
| `/v1/audit/access-history`               | GET          | Yes   | No              | Patient access history (all patients) |
| `/v1/operator/settings/*`                | GET/PUT      | Yes   | No              | All settings endpoints                |
| `/v1/operator/users/*`                   | GET/POST/PUT | Yes   | No              | User management                       |
| `/v1/operator/observability/*`           | GET          | Yes   | No              | Observability dashboard               |
| `/v1/operator/health`                    | GET          | Yes   | No              | System health                         |

**Implementation approach:**

- Gateway middleware reads `operator_tier` from JWT claims
- Route decorators specify required tier: `@require_operator_tier("admin")`
- Non-admin operators hitting admin-only routes get 403 with `INSUFFICIENT_OPERATOR_TIER` error code
- Audit every tier-gated denial (append to `audit_events`)

**Files to modify:**

- `apps/backend/gateway/middleware.py` (or equivalent) - extract `operator_tier` from JWT
- `apps/backend/modules/iam/operator_facade.py` - add tier to session issuance
- New decorator: `apps/backend/gateway/decorators.py` - `@require_operator_tier(tier)`
- All operator console API routes - add tier decorators

### 3.3 Settings Tab - AI Configuration Panel

**What:** Admin-only panel to configure AI model selection, confidence threshold, and budget limits.

**API routes:**

| Route                                 | Method | Purpose                         |
| ------------------------------------- | ------ | ------------------------------- |
| `GET /v1/operator/settings/ai`        | GET    | Read current AI config          |
| `PUT /v1/operator/settings/ai`        | PUT    | Update AI config                |
| `GET /v1/operator/settings/ai/budget` | GET    | Read budget limits per provider |
| `PUT /v1/operator/settings/ai/budget` | PUT    | Update budget limits            |

**Config shape (stored in `observability.app_config`):**

```json
{
  "ai": {
    "transcribe": {
      "provider": "gemini",
      "model": "gemini-2.0-flash",
      "fallback_provider": "nvidia",
      "fallback_model": "nvidia-nemotron"
    },
    "structure": {
      "provider": "gemini",
      "model": "gemini-2.0-flash",
      "fallback_provider": "nvidia",
      "fallback_model": "nvidia-nemotron"
    },
    "draft_rx": {
      "provider": "gemini",
      "model": "gemini-2.0-flash",
      "fallback_provider": "nvidia",
      "fallback_model": "nvidia-nemotron"
    },
    "confidence_threshold": 0.7,
    "timeout_seconds": 30,
    "max_retries": 3
  }
}
```

**Budget shape (stored in `observability.ai_cost_budget`):**

```json
{
  "provider": "gemini",
  "model": "gemini-2.0-flash",
  "monthly_limit_paise": 0,
  "alert_threshold_pct": 80.0
}
```

**Frontend:** Form with dropdowns for provider/model selection per task, number inputs for threshold and budget, save button. Reads/writes via the API routes above.

### 3.4 Settings Tab - Notification Configuration Panel

**What:** Admin-only panel to configure notification templates and channels.

**Config shape (stored in `observability.app_config`):**

```json
{
  "notifications": {
    "whatsapp": {
      "enabled": true,
      "templates": {
        "dosage_reminder": { "name": "caresetu_dosage_v1", "language": "hi" },
        "retest_30": { "name": "caresetu_retest30_v1", "language": "hi" },
        "retest_90": { "name": "caresetu_retest90_v1", "language": "hi" }
      },
      "fallback_to_sms": true
    },
    "in_app": {
      "enabled": true
    }
  }
}
```

**API routes:**

| Route                                     | Method | Purpose                    |
| ----------------------------------------- | ------ | -------------------------- |
| `GET /v1/operator/settings/notifications` | GET    | Read notification config   |
| `PUT /v1/operator/settings/notifications` | PUT    | Update notification config |

### 3.5 Settings Tab - Feature Flags Panel

**What:** Admin-only panel to enable/disable features per deployment phase.

**Config shape (stored in `observability.app_config`):**

```json
{
  "features": {
    "chronic_care": {
      "enabled": false,
      "description": "BP/sugar logging + follow-ups (Phase 12)"
    },
    "diagnostics": {
      "enabled": false,
      "description": "Lab booking + report filing (Phase 9)"
    },
    "pharmacy": {
      "enabled": false,
      "description": "Medicine fulfillment routing (Phase 10)"
    },
    "settlement": {
      "enabled": false,
      "description": "UPI settlement exception path (Phase 11)"
    },
    "notifications": {
      "enabled": false,
      "description": "WhatsApp notifications (Phase 13)"
    }
  }
}
```

**How it works:**

- Feature flags are checked by module facades before executing logic
- Disabled features return a clear "feature not available" response
- Flags are config-driven, not code-driven - changing a flag in settings takes effect immediately
- Flags are read from `observability.app_config` and cached in Redis (invalidated on write)

**API routes:**

| Route                                | Method | Purpose                |
| ------------------------------------ | ------ | ---------------------- |
| `GET /v1/operator/settings/features` | GET    | Read all feature flags |
| `PUT /v1/operator/settings/features` | PUT    | Update feature flags   |

### 3.6 Settings Tab - User Management Panel

**What:** Admin-only panel to manage operator accounts.

**API routes:**

| Route                                  | Method | Purpose                                               |
| -------------------------------------- | ------ | ----------------------------------------------------- |
| `GET /v1/operator/users`               | GET    | List all operators (paginated)                        |
| `POST /v1/operator/users/invite`       | POST   | Invite new operator (creates identity + sends invite) |
| `PUT /v1/operator/users/{id}/tier`     | PUT    | Change operator tier (admin <-> operator)             |
| `PUT /v1/operator/users/{id}/status`   | PUT    | Suspend/deactivate operator                           |
| `GET /v1/operator/users/{id}/activity` | GET    | View operator activity log                            |

**Invite flow:**

1. Admin enters phone number + tier selection
2. Backend creates `iam_identities` row with `operator_tier` set
3. Backend creates `iam_role_grants` row with `role = 'operator'`, `status = 'Pending'`
4. Backend sends OTP to the phone (reuses `EXT-001` SMS)
5. New operator completes registration + MFA enrollment
6. Role grant activated, operator can log in

**Frontend:** Table listing operators with columns: phone, tier, status, last login, actions (change tier, suspend). Invite button opens a modal form.

### 3.7 Observability Tab - Cost Dashboard

**What:** Admin-only dashboard showing AI cost metrics.

**Data source:** `observability.ai_usage_daily` + `observability.ai_cost_budget`

**Dashboard panels:**

| Panel                      | Query                                            | Visualization               |
| -------------------------- | ------------------------------------------------ | --------------------------- |
| Monthly spend vs budget    | `ai_cost_budget` WHERE billing_period = current  | Progress bar with burn rate |
| Cost by provider (30 days) | `ai_usage_daily` GROUP BY provider               | Horizontal stacked bar      |
| Cost trend (30 days)       | `ai_usage_daily` GROUP BY date                   | Line chart                  |
| Cost by task type          | `ai_usage_daily` GROUP BY task_type              | Pie chart                   |
| Token usage by provider    | `ai_usage_daily` GROUP BY provider               | Bar chart                   |
| Budget alerts              | `ai_cost_budget` WHERE current_spend > threshold | Alert banner                |

**API routes:**

| Route                                             | Method | Purpose                           |
| ------------------------------------------------- | ------ | --------------------------------- |
| `GET /v1/operator/observability/cost`             | GET    | Cost overview (current period)    |
| `GET /v1/operator/observability/cost/trend`       | GET    | Daily cost trend (query: days=30) |
| `GET /v1/operator/observability/cost/by-provider` | GET    | Cost breakdown by provider        |
| `GET /v1/operator/observability/cost/by-task`     | GET    | Cost breakdown by task type       |

**Charting:** Use `recharts` (React charting library, MIT license, ~40KB gzipped) for the dashboard visualizations. Lightweight, no paid dependencies.

### 3.8 Observability Tab - Usage & Quality Metrics

**What:** Admin-only dashboard showing AI usage, latency, and quality metrics.

**Data source:** `observability.ai_usage_daily` + `observability.ai_provider_health` + Langfuse

**Dashboard panels:**

| Panel                             | Query                                            | Visualization                    |
| --------------------------------- | ------------------------------------------------ | -------------------------------- |
| Calls per day (30 days)           | `ai_usage_daily` GROUP BY date                   | Line chart                       |
| Success rate by provider          | `ai_provider_health`                             | Gauge per provider               |
| Latency percentiles (p50/p95/p99) | `ai_provider_health`                             | Comparison table                 |
| Low-confidence rate trend         | `ai_usage_daily` GROUP BY date                   | Line chart                       |
| Error breakdown                   | `ai_usage_daily` failure_count GROUP BY provider | Bar chart                        |
| Langfuse deep-link                | External URL                                     | "View traces in Langfuse" button |

**API routes:**

| Route                                         | Method | Purpose                                    |
| --------------------------------------------- | ------ | ------------------------------------------ |
| `GET /v1/operator/observability/usage`        | GET    | Usage overview (current period)            |
| `GET /v1/operator/observability/usage/trend`  | GET    | Daily usage trend                          |
| `GET /v1/operator/observability/quality`      | GET    | Quality metrics (confidence, success rate) |
| `GET /v1/operator/observability/latency`      | GET    | Latency percentiles by provider            |
| `GET /v1/operator/observability/langfuse-url` | GET    | Langfuse project URL for deep-linking      |

### 3.9 Nightly Rollup Cron Implementation

**What:** Full implementation of the cron job (skeleton created in Phase 7 prep plan).

**Location:** `apps/backend/worker/scheduler.py` (or equivalent APScheduler setup)

**Schedule:** Daily at 02:00 UTC

**What it does:**

```python
async def nightly_observability_rollup():
    """Aggregate yesterday's ai_jobs into observability tables."""

    yesterday = date.today() - timedelta(days=1)

    # 1. Aggregate ai_jobs -> ai_usage_daily
    rows = await db.execute("""
        SELECT
            DATE(created_at) as date,
            provider,
            model,
            task_type,
            COUNT(*) as total_calls,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failure_count,
            SUM(CASE WHEN status = 'timeout' THEN 1 ELSE 0 END) as timeout_count,
            SUM(CASE WHEN low_confidence = true THEN 1 ELSE 0 END) as low_confidence_count,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(cost_paise) as total_cost_paise,
            AVG(latency_ms) as avg_latency_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) as p95_latency_ms
        FROM intake.ai_jobs
        WHERE DATE(created_at) = :yesterday
        GROUP BY DATE(created_at), provider, model, task_type
    """, {"yesterday": yesterday})

    for row in rows:
        await upsert_ai_usage_daily(row)

    # 2. Update provider health
    # 3. Update budget spend
    # 4. Snapshot system health
    # 5. Check alert thresholds
```

**Backfill:** On first run, the cron should process all existing `ai_jobs` (not just yesterday). Subsequent runs process only the previous day.

### 3.10 Langfuse Evaluation Setup

**What:** Configure Langfuse's eval features for CareSetu's AI quality.

**Steps:**

1. In Langfuse Cloud UI, create a **dataset** for pre-summary quality:

   - Import sample transcripts + expected structured outputs
   - Use for regression testing when switching models/providers

2. Set up **LLM-as-judge evaluations:**

   - Confidence score validation: does the model's self-reported confidence match actual quality?
   - Pre-summary completeness: are all required fields populated?
   - Rx draft accuracy: do the drafted items match the doctor's voice note?

3. Configure **prompt management:**

   - Version the transcribe/structure/draft prompts in Langfuse
   - A/B test prompt changes with Langfuse's experiment framework

4. Set up **annotation queue:**
   - Doctor reviews of pre-summaries can be logged back to Langfuse as human feedback
   - This creates a feedback loop for evaluating AI quality over time

## 4. Frontend Implementation

**Route structure in operator console:**

```
src/app/(operator)/operator/
  page.tsx                          # Dashboard home (existing)
  verifications/
    page.tsx                        # Verification queue (existing)
    [id]/page.tsx                   # Verification detail (existing)
  settings/
    page.tsx                        # Settings overview
    ai/page.tsx                     # AI configuration
    notifications/page.tsx          # Notification configuration
    features/page.tsx               # Feature flags
    users/page.tsx                  # User management
  observability/
    page.tsx                        # Observability overview
    cost/page.tsx                   # Cost dashboard
    usage/page.tsx                  # Usage & quality metrics
```

**Navigation:** Admin operators see Settings + Observability in sidebar. Non-admin operators see only Verifications + Audit (read-only).

**Shared components:**

- `OperatorSettingsLayout.tsx` - settings page wrapper
- `OperatorObservabilityLayout.tsx` - observability page wrapper
- `CostChart.tsx` - recharts-based cost visualization
- `UsageChart.tsx` - recharts-based usage visualization
- `LatencyTable.tsx` - provider latency comparison table
- `UserManagementTable.tsx` - operator list with actions
- `FeatureFlagToggle.tsx` - toggle component for feature flags
- `BudgetConfigForm.tsx` - budget limit configuration form

## 5. Implementation order

| Step | What                                    | Blocks      | Estimated time |
| ---- | --------------------------------------- | ----------- | -------------- |
| 1    | Operator tier schema migration          | 2           | 1 hour         |
| 2    | RBAC extension + tier decorators        | 3,4,5,6,7,8 | 4 hours        |
| 3    | Settings API routes (all 4 panels)      | 4,5,6       | 6 hours        |
| 4    | Settings frontend (all 4 panels)        | -           | 8 hours        |
| 5    | Observability API routes                | 7,8         | 4 hours        |
| 6    | Observability frontend (dashboards)     | -           | 8 hours        |
| 7    | Nightly rollup cron full implementation | -           | 4 hours        |
| 8    | Langfuse eval setup                     | -           | 2 hours        |
| 9    | Integration testing + E2E               | -           | 4 hours        |
| 10   | Doc updates (roadmap, standards)        | -           | 1 hour         |

**Total estimated time:** ~42 hours (5-8 working days)

## 6. Verification checklist

- [ ] Operator tier migration applied to Supabase
- [ ] Existing operators backfilled to `admin` tier
- [ ] New operators created with specified tier
- [ ] Non-admin operator gets 403 on admin-only routes
- [ ] Admin operator can access all routes
- [ ] Settings tab renders for admin only
- [ ] Settings tab hidden for non-admin
- [ ] AI config form reads/writes correctly
- [ ] Notification config form reads/writes correctly
- [ ] Feature flags toggle and take effect
- [ ] User management: invite flow works end-to-end
- [ ] User management: tier change works
- [ ] User management: suspend/deactivate works
- [ ] Observability dashboard: cost charts render with real data
- [ ] Observability dashboard: usage charts render with real data
- [ ] Observability dashboard: latency table populated
- [ ] Langfuse deep-link opens correct project
- [ ] Nightly cron job runs successfully
- [ ] Nightly cron backfills historical data correctly
- [ ] Budget alert triggers at threshold
- [ ] `npm run lint` green
- [ ] `npm run typecheck` green
- [ ] `npm run migration-check` green
- [ ] E2E test: admin can access all console features
- [ ] E2E test: non-admin can only access verification queue

---

## 7. Production-Readiness Audit Remediation (Workstream 2)

Supersedes `docs/plans/production-readiness-audit.md` (that file was deleted on 2026-09-08; this section carries its recommendations forward). These are the remediation items from the production-readiness audit that we deliberately defer past Phase 14. They split into **ship now** (additive hardening, low risk) and **later** (needs real traffic / broad coordination).

> **Purpose of this section:** a single home for the audit's recommendations so nothing is lost. It is a living plan - each item becomes a `/to-tickets` source of truth only when it is actually scheduled. None of this blocks Phases 7-13 or Phase 14.

### 7.0 Summary of the audit verdict

The codebase is well above demo quality in auth/JWT, RBAC, error handling, CI/CD, backups, load testing, and migrations. Real gaps are concentrated in **observability**, **scaling**, and a few **security** items. The audit's "Critical" and "High" ranking reflects a production-launch bar; since we are still building features (Phases 7-13) with no real traffic, most can wait until launch prep.

### 7.1 Recommended remediation order

Prioritised from the audit. Items with **"When: Now"** are additive hardening that can be threaded into any phase without risk; **"When: Later"** items need real traffic or Phase-14 coordination.

| #   | Item                                                            | Grade  | Why it matters                                                     | When      | Risk                                            | Effort |
| --- | :-------------------------------------------------------------- | :----- | :----------------------------------------------------------------- | :-------- | :---------------------------------------------- | :----- |
| 1   | Structured JSON logging (structlog)                             | C      | stdout logs are unqueryable; needed before any log aggregation     | **Now**   | None - drop-in                                  | Small  |
| 2   | Error tracking (Sentry or equiv)                                | High   | unhandled exceptions go to logs only, no alerting / stack grouping | **Now**   | None - SDK init                                 | Small  |
| 3   | Basic metrics + `/metrics` (prometheus-fastapi-instrumentator)  | C      | request latency / error rate visibility                            | **Now**   | None - middleware                               | Small  |
| 4   | Cache hit/miss counters on Redis caches                         | C      | eat observable cache health                                        | **Now**   | None - additive counters                        | Small  |
| 5   | CSP header (report-only first)                                  | High   | currently only HSTS + nosniff set                                  | **Now**   | Low - start Report-Only                         | Small  |
| 6   | XSS / HTML sanitizer (bleach/nh3)                               | High   | user free text may later be re-rendered in a browser               | **Now**   | Low - wire before Phase-7 frontend renders text | Small  |
| 7   | SQLAlchemy pool sizing config                                   | C+     | connection pooling beyond defaults                                 | **Now**   | None - config-only                              | Small  |
| 8   | Dockerfile for backend                                          | C+     | enables local parity + future horizontal scaling                   | **Now**   | None - additive                                 | Small  |
| 9   | Redis-backed distributed rate limiter                           | C      | in-memory limiter multiplies budget across workers                 | **Later** | Medium - needs budget design                    | Medium |
| 10  | Extend rate limiting beyond `/v1/auth/*` (per-user + per-route) | C      | auth-only today; no guard on health/consent/partner abuse          | **Later** | Medium - depends on #9                          | Medium |
| 11  | Redis-backed idempotency store                                  | C+     | in-process store dies on restart; only matters multi-instance      | **Later** | None - swap when multi-instance                 | Small  |
| 12  | Business metrics dashboard (funnel, OTP success, consent rate)  | Medium | needs real traffic to be meaningful                                | **Later** | None                                            | Medium |

### 7.2 Ship-now items (additive, safe)

**Safety pattern that applies to all of these:** (a) additive-only - append, never rewrite; (b) feature-flagged behind `Settings` env vars, disabled by default; (c) graceful degradation - init failure never takes the app down (mirror the existing Redis no-op pattern); (d) no PostgreSQL schema changes; (e) backend-only, no frontend or session/CORS changes (respect ADR-0007).

#### 7.2.1 Structured JSON logging (structlog)

Add `structlog` as a runtime dependency (`uv add structlog`). Configure a JSON formatter in `app/main.py` and `worker/main.py`. Adopt **file-by-file** - replace `logging.getLogger(__name__)` + `f"..."` printf lines with structlog bindings. Keep trace_id propagation. Config gate: `LOG_FORMAT` env (`json` | `console`), default `console` in dev, `json` in prod.

- Files: `app/main.py`, `worker/main.py`, `bus/dispatcher.py`, `app/gateway/*`, all module files that log.
- No behavior change - only formatting.

#### 7.2.2 Error tracking (Sentry)

Add `sentry-sdk[fastapi]`. Init in the app lifespan guarded by a `SENTRY_DSN` env - absent DSN = no-op, so dev/local is untouched. Configure release tracking (from git SHA). Capture unhandled exceptions; keep trace_id binding to correlate with logs. PII minimisation: never send raw OTP, phone, or text bodies (scrub via `before_send`).

- Config gate: `SENTRY_DSN` (empty = disabled).
- Follows `observability/langfuse_client.py`'s lazy/no-op singleton pattern.

#### 7.2.3 Basic metrics + `/metrics` endpoint

Add `prometheus-fastapi-instrumentator`. Mount in `create_app` behind an `METRICS_ENABLED` flag. Expose `/metrics` for scraping. Add request latency histograms, error-rate counters, and cache hit/miss counters (7.2.4). No numeric dashboard yet - that comes in Section 3.7/3.8 (operator Observability tab) once there is traffic.

#### 7.2.4 Cache hit/miss counters

Add counters to `modules/consent/redis_cache.py` and `modules/partner/directory_cache.py`: increment on cache hit/miss, expose via the Prometheus registry. Zero behavior change; pure instrumentation.

#### 7.2.5 CSP header (report-only first)

Add `Content-Security-Policy-Report-Only` to `app/gateway/security_headers.py`, behind a `CSP_REPORT_ONLY` flag. Start permissive (allow current frontend origins, `unsafe-inline` for dev), then tighten to a full enforce-mode CSP during launch prep (Phase 14). Enforce-mode flip must be verified against the deployed Vercel frontend first - split-origin (ADR-0007).

#### 7.2.6 XSS / HTML sanitizer

Add `bleach` (or `nh3`). Add a sanitizer util and wire it at the point where user-provided free text is stored and/or rendered. There is no user-text rendering in a browser yet (Phase 7 frontend is pending) - the guard must be in place **before** Phase-7/8 frontends render free text back. Pydantic `extra="forbid"` rejects unknown fields but does not sanitise values.

#### 7.2.7 SQLAlchemy pool sizing config

Expose pool size / max_overflow / pool_timeout via `Settings` env vars and apply to the async engine in the DB bootstrap. Config-only; no behavior change. Defaults chosen for the single Render instance (small pool, e.g. size 5 / overflow 10).

#### 7.2.8 Dockerfile for the backend

Add a `Dockerfile` (multi-stage: build with `uv sync --frozen --no-dev`, runtime with `uv run uvicorn app.main:app`), plus a `.dockerignore`. Purely additive - the existing Render native `render.yaml` deploy stays the path of record; the Dockerfile enables local parity and is the first step toward the horizontal-scaling path (#8 in the audit, 7.3 below).

### 7.3 Later items (defer to launch prep / real traffic)

These stay fog until there is either real traffic or a scaling decision. Not scheduled now; revisit in Phase 14 release readiness.

- **Redis-backed distributed rate limiter** (`Redlock`-style or a Redis INCR fixed/sliding window over the existing `redis.asyncio` pool). Requires a design decision on per-user vs per-route budgets. Only matters once there are multiple uvicorn workers or instances. Until then the in-memory limiter + Caddy edge (future) is sufficient. Config gate: `GATEWAY_RATE_LIMIT_BACKEND=memory|redis`.
- **Per-user / per-route rate limiting** - extend beyond `/v1/auth/*` to health, consent, partner routes. Depends on the distributed-backend decision above; overkill for current single-instance / no-traffic state.
- **Redis-backed idempotency store** - swap the in-process `app/gateway/idempotency.py` store for one over Redis. Only required with multiple instances (a restarted single instance loses in-flight keys, acceptable at current scale).
- **Horizontal scaling runbook + worker count tuning** - single uvicorn instance + PaaS-native (Render) today; the Dockerfile (7.2.8) is the seed. Needs an orchestration decision (single VM same-origin edge path, per ADR-0007) before any multi-instance work.
- **Business metrics dashboard** (registration funnel, OTP success rate, consent grant rate, pre-summary accuracy) - meaningful only with real traffic; design it in Workstream 1 (Section 3.7/3.8) and populate once live.

### 7.4 Already covered elsewhere (do not duplicate)

| Audit item                                                 | Where it lives                                                                           |
| :--------------------------------------------------------- | :--------------------------------------------------------------------------------------- |
| LLM API flow (provider, validation, prompt assembly)       | Phase 7 tickets T02-T13 (`docs/agents/briefs/PHASE-7-*`)                                 |
| Token metering + cost tracking                             | Phase 7 T06 budget meter                                                                 |
| Langfuse `@observe` decorators                             | Phase 7 tracing prep (`plan-phase7-tracing-prep.md`)                                     |
| Context management engine                                  | Future phase (chronic care / later) - schema columns exist, engine is not Phase-14 scope |
| E2E + audit completeness + cost telemetry + launch runbook | Phase 14 release readiness                                                               |

### 7.5 Verification / completion notes

- Every ship-now item must be feature-flagged and disabled by default so local dev / CI remain unchanged until enabled.
- `security_posture.py` gate (live TLS/HSTS) should have a companion check for the CSP + sanitizer additions.
- `npm run lint`, `npm run typecheck`, `npm run migration-check` all stay green (no schema changes).
- CI gate for the Dockerfile: build it in CI so it does not rot (add a job that builds and runs a smoke check).
