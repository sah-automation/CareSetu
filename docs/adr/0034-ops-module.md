# ADR-0034: MOD-014 Ops module - the operational configuration module

**Status:** accepted
**Date:** 2026-10-29
**Decides:** That a new module `MOD-014 Ops` owns the private `ops` schema (the thirteenth `MODULE_SCHEMAS` entry) and serves as the platform's operational configuration module - effective settings read with source precedence, allowlisted settings writes with versioned history and audit, feature flags with runtime/restart-required typing, and notification routing configuration. It is a configuration module, not a domain bounded context: it publishes `audit.event` and exposes no domain facade for other modules to call.
**Traceability:** `plan-phase14-observability.md` §10, §13; spec #761; parent #761; tickets #764, #771, #772, #773, #774. Related: `ADR-0002` (transactional outbox), `ADR-0003` (DB-per-module isolation), `ADR-0025` (observability module pattern), `ADR-0030` (SLOs and alert kinds), `internal-modules.md` §3.15.

## Context

The Phase 14 observability plan (§10, §13) identifies the need for an operational configuration surface: AI config (budget, timeout, fallback), notification routing (Slack/email recipients, per-alert-kind routing), feature flags (runtime vs restart-required), and a settings history/audit trail. Batch 3 delivered the operator console IA but left the Settings destination as a placeholder shell. The `ops` schema was originally planned in the roadmap (§2.14 §3) but its `cost_meters` table was subsumed by `PHASE-14A`'s `observability_ai_cost_budget`. The remaining configuration concerns - settings, feature flags, notification routing - need a module and schema.

## Decision

### D1 - New module `MOD-014 Ops` with private `ops` schema

`MOD-014` is registered as the thirteenth `MODULE_SCHEMAS` entry in `bus/bootstrap.py`. The migration `v9_9__init_ops` creates:

- `ops_settings` - key-value overrides (JSONB value) with version, updated_by, timestamps
- `ops_setting_history` - append-only history (key, value, version, changed_by, changed_at)
- `ops_feature_flags` - flag_key, enabled, flag_kind (`runtime` | `restart_required`), description, version, updated_by, timestamps
- `ops_feature_flag_history` - append-only history (flag_key, enabled, flag_kind, version, changed_by, changed_at)
- `ops_outbox` - transactional outbox (ADR-0002)
- `ops_consumed_events` - idempotency ledger (ADR-0002)

### D2 - Effective settings read with source precedence

The `GET /v1/operator/settings/effective` endpoint (admin-gated) returns all known settings with:

- `key` - the setting key
- `value` - the effective value (null for secrets/read-only keys)
- `source` - `database` | `environment` | `default`
- `editable` - boolean (true only for keys in `ALL_EDITABLE_KEYS`)
- `restart_required` - boolean (true for secrets, boot-time gates, provider credentials)

Precedence: database override → environment (`Settings`) → default. Read-only/sensitive keys (secrets, boot-time gates, provider credentials) are never returned raw; value is `null` with metadata.

### D3 - Allowlisted settings writes with history and audit

The `PUT /v1/operator/settings` endpoint (admin-gated) accepts writes only for keys in `ALL_EDITABLE_KEYS`:

- AI operational knobs: `ai.monthly_budget_paise`, `ai.budget_alert_threshold_pct`, `ai.timeout_seconds`, `ai.fallback_enabled`
- Notification routing: `notification.email.recipients`, `notification.channels.slack.enabled`, `notification.channels.email.enabled`, `notification.routing.{kind}` for each `ALERT_KIND`

Validation mirrors boot-time config so a database override can never carry a value the process would have refused from the environment. Every write:

1. Upserts `ops_settings` with incremented version
2. Appends to `ops_setting_history`
3. Emits `audit.event` (action: `setting.write`) in the same transaction
4. Invalidates the in-process TTL cache (`OpsSettingsCache`)

### D4 - Feature flags with runtime/restart-required typing

The `ops_feature_flags` table carries `flag_kind`:

- `runtime` - editable at runtime via `PUT /v1/operator/feature-flags/{flag_key}` (admin-gated)
- `restart_required` - read-only with explanation; requires service restart to change

Only runtime flags are editable. Every flag write:

1. Validates the flag exists and is `runtime` kind
2. Updates `ops_feature_flags` with incremented version
3. Appends to `ops_feature_flag_history`
4. Emits `audit.event` (action: `feature_flag.write`) in the same transaction
5. Is idempotent via the gateway's idempotency key middleware

### D5 - Notification routing configuration

The `notification.routing.{kind}` settings map each alert kind (from `ALERT_KINDS` in `ops/domain/settings.py`) to a routing target: `slack`, `email`, or `none`. The notification routing consumer (in `MOD-010` or a new alert delivery module) reads these at dispatch time. Channel enable/disable and recipient settings are also in the allowlist.

### D6 - No domain facade, publishes `audit.event` only

`MOD-014` exposes no domain facade for other modules to call. It is a configuration module, not a domain bounded context. Its only outbound event is `audit.event` (generic) on setting writes and feature flag writes, consumed by `MOD-011` (Audit) and `MOD-013` (Observability). It never queries another module's tables.

### D7 - In-process TTL cache for effective settings

Effective settings reads are cached in-process with a configurable TTL (default 30 s, `settings_cache_ttl_seconds` in `Settings`). The cache is invalidated on any setting write. This keeps the admin settings read latency p95 < 100 ms.

## Considered options

- **Fold settings into `MOD-013` (Observability).** Rejected - observability is telemetry (mutable aggregates, rollups); configuration is authoritative state with write precedence, validation, and audit. Different write patterns, different consumers.
- **Reuse the planned `ops` schema from the old roadmap.** Rejected - the old `ops.cost_meters` was subsumed by `observability_ai_cost_budget`. The new `ops` schema serves a different purpose (configuration, not cost metering).
- **Expose a domain facade for other modules to read settings.** Rejected - settings are operator-facing configuration. Other modules read boot-time config from `Settings` (environment). Database overrides are for operator-driven operational changes, not for module-to-module communication.
- **Allow writes to any setting key.** Rejected - secrets and boot-time gates must remain environment-only. The allowlist enforces this boundary.

## Consequences

- The private schema count grows to 13 (iam, partner, health, consent, intake, care, diagnostics, fulfillment, settlement, notify, audit, observability, ops).
- The operator Settings tab (AI, Notifications, Feature Flags, Users) is now backed by `MOD-014` with full history and audit.
- Feature flags are typed (runtime vs restart-required), so the operator knows which changes require a deploy.
- Notification routing is configurable per alert kind without code changes.
- All configuration writes are audited and versioned, meeting `KPI-006` and `NFR-D01`.
