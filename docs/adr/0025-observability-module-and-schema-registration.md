# ADR-0025: MOD-013 Observability and the `observability` schema registration

**Status:** accepted
**Date:** 2026-10-13
**Decides:** That a new module `MOD-013 Observability` owns its own `observability` schema and is registered as the twelfth `MODULE_SCHEMAS` entry - a one-schema-rule extension of the audit pattern, not a new seam.
**Traceability:** `plan-phase14-observability.md` §7, §10, §14, §15; parent #692; batch tickets #701, #702, #703. Related: `ADR-0002` (transactional outbox), `ADR-0003` (DB-per-module isolation), `MOD-011` (Audit), `NFR-001`, `NFR-SEC-006`, `internal-modules.md` §4.2.

## Context

The operator-facing aggregates - AI usage/cost, provider health, business rollups, and the alert feed - need a durable home that survives vendor retention limits (`ADR-0024`). The module isolation rule (`ADR-0003`) offers exactly one pattern for a schema that consumes other modules' signals without reading their tables: the audit pattern. `MOD-011` (Audit) owns its own schema, is fed by `audit.event` published into each producer's outbox in the same transaction as the audited change (published, never synthesized by the dispatcher), and exposes read APIs. The observability aggregates need the same shape, and the plan calls for exactly one new schema rather than a per-concern sprawl.

## Decision

### D1 - New module `MOD-013 Observability`

It owns its own `observability` schema, consumes existing outbox events, and exposes operator read APIs. It is a sibling of `MOD-011` (Audit): the same one-schema-rule extension of the audit pattern, applied to telemetry rather than to an audit trail. It is **telemetry, not a domain bounded context** - no domain tables, no facade for other modules to call.

### D2 - Registered as the twelfth `MODULE_SCHEMAS` entry

`bus/bootstrap.py:MODULE_SCHEMAS` grows by one entry (`observability`); the migration harness keeps its single-head gate (`npm run migration-check`). The bootstrap tuple is frozen per `ADR-0003`, so the schema arrives as a new additive migration `v9_0__init_observability`, never as an edit to an earlier revision.

### D3 - Fed only by outbox events

`MOD-013` subscribes to the existing `internal-modules.md` §4.2 registry (`ai_job.completed`, `ai_job.failed`, `case.*`, `partner.*`, `consent.*`, `record.accessed`, `audit.*`) and aggregates as events arrive. It never queries another module's tables. Where a needed field is absent from an event payload, the resolution is a **narrow read-only exception registered here** - not a cross-schema read bolted on quietly.

### D4 - Idempotent by its own ledger

`obs_consumed_events` records `event_id` before effects are applied, so a replayed delivery is a no-op (the same `consumed_events` pattern every module uses, `ADR-0002`).

### D5 - Schema surface (`v9_0`)

The module ships `obs_ai_usage_daily` (per date/provider/model/task_type counts, tokens, cost, latency), `obs_ai_cost_budget` (monthly limits vs spend), `obs_ai_provider_health` (rolling success rate, latency percentiles, breaker state), `obs_business_daily` (a registry-driven `metric_key`/`date`/`value` JSONB rollup so later phases add metrics without schema churn), `obs_alert_events` (the operator-visible alert feed), and `obs_consumed_events` (the idempotency ledger).

### D6 - No cross-schema foreign keys, single additive migration

`obs_*` tables reference only their own schema; the migration adds one schema, no edits to existing ones (`ADR-0003`; `plan-phase14-observability.md` §15).

### D7 - PHI-free

The schema stores pseudonymous ids and aggregate counters only - never transcript text, patient identity, or raw provider payloads (`NFR-SEC-006`; `plan-phase14-observability.md` §10).

## Considered options

- **Fold observability into `MOD-011` (Audit).** Rejected - audit is append-only and hash-chained; observability aggregates are mutable, reversible, and roll up, which are incompatible write patterns for one schema.
- **Reuse an existing `ops` schema or a vendor-only ledger.** Rejected - no cross-schema reads are permitted, and a vendor-only ledger loses the decision data to retention limits (`ADR-0024`).
- **Read other modules' tables directly for aggregates.** Rejected - a direct violation of the module isolation rule (`ADR-0003`); the event stream already carries what is needed.
- **A schema per concern (cost, health, alerts).** Rejected - multiplies migrations and boundary surface for no isolation benefit; one telemetry schema matches the one-schema rule.

## Consequences

- The module boundary checker (`ADR-0003`) now recognizes `observability` as a legitimate schema; `MOD-013` must ship the outbox consumer and the `obs_consumed_events` replay test like every other consumer.
- Aggregates depend on event completeness: any field the decision surfaces need but no event carries must be raised as a narrow read-only exception on this decision rather than silently read across a schema.
- The nightly rollup (`plan-phase14-observability.md` §8) recomputes percentile-based aggregates from `obs_ai_usage_daily`; the vendor data model stays API-first and independent of it.
- The `D2` tickets (#713, #715, #716) record the `MOD-013` spec and its §4.1/§4.2/§5 matrix rows; this ADR is the decision they cite.
