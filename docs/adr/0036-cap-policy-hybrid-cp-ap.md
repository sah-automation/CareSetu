# ADR-0036: CAP policy: hybrid CP/AP

**Status:** accepted
**Date:** 2026-11-02
**Decides:** That CareSetu uses a hybrid consistency model. All writes and the critical read paths below are CP (strong consistency on the primary PostgreSQL). Allowlisted, read-only paths are AP (eventually consistent, with a SQL fallback). Read routing defaults to the primary; only an explicit allowlist may reach read replicas. AP caches are optional and Redis-backed. Profile and intake caches are gated by `PHI_CACHE_ENABLED` and `REDIS_URL`. Rate limiting can use Redis with an in-memory fallback. Circuit breakers are globally bypassable and fail open. The reserved scale settings are accepted and validated but stay inert.
**Traceability:** `docs/plans/architecture-improvements.md` Phase 1; `docs/plans/improvements/cap-policy-analysis.md`; `docs/plans/improvements/scale-ready-architecture.md`; `docs/plans/improvements/latency-improvement-plan.md`; tickets #811, #812, #813, #814, #815, #816, #817, #818, #819, #820, #821, #822, #823, #824. Related: `ADR-0007` (split-origin deployment), `ADR-0031` (accepted risk posture).

## Context

CareSetu is a modular monolith on a single PostgreSQL instance, deployed split-origin (frontend on Vercel, API on Render) within a low-cost budget. Consistency is a per-operation choice, not a global default: writes and the safety-critical reads need strong consistency, while most reads can tolerate bounded staleness behind a cache or a read replica. Redis is optional and there is no multi-region at the launch tier, so partition tolerance is best-effort on a single availability zone.

## Decision

### D1 - CP write path and critical reads stay on the primary

- All mutations run in a single PostgreSQL transaction and write an outbox row in the same transaction.
- The primary serves the CP reads: auth validation, consent grant/revoke/check, prescription approval and rejection, audit append, and partner activation/deactivation.
- CP paths never use a read replica or a stale cache. Primary-default routing is the safe baseline; caches and replicas are opt-in on top of it.

### D2 - AP routing: primary by default, explicit allowlist to replicas

- `READ_REPLICA_ENABLED` defaults to false and `DATABASE_READ_URLS` defaults to empty, so the system behaves as a single-primary deployment unless an operator opts in.
- A `GET` or `HEAD` may route to a replica only when its path is on the explicit allowlist:
  - `/v1/directory/search`
  - `/v1/directory/providers/...`
  - `/v1/care/cases`
  - `/v1/me/profile`
- The CP guard runs inside the allowlist and denies every path containing auth, consent, prescription, care `rx`, audit, partner verification, egress, or patient markers, so a future allowlist edit cannot route a critical path.
- Write-bearing GET exception: GETs that append audit or egress rows, specifically the doctor patients list/detail, the doctor cases list, and the intake review queue, and all prescription, consent, and audit reads, are never eligible even when they match the allowlist, because their result depends on transactional state and must be read from the primary.
- Replica selection is round-robin across healthy replicas, with a per-replica unhealthy cooldown and fallback to the primary when none is healthy. A failure that occurs after a transaction starts is not retried on the primary.
- `READ_REPLICA_LAG_TOLERANCE_MS` (default 1000) is validated and recorded for later replica-health work; it is not enforced in this phase.

### D3 - Cache policy and PHI gate

- A single shared async Redis client is created from `REDIS_URL` at boot, pinged, and closed at shutdown. An empty or unreachable Redis disables caching and every caller falls back to PostgreSQL.
- AP caches, with their defaults from `Settings`:
  - Directory search and provider directory: 300 seconds (`REDIS_DIRECTORY_TTL_SECONDS` and `REDIS_CONSENT_TTL_SECONDS` for consent status).
  - Patient profile: 300 seconds (`PROFILE_CACHE_TTL_SECONDS`).
  - Intake list: 120 seconds (`INTAKE_CACHE_TTL_SECONDS`).
  - Care cases: 60 seconds (`CARE_CASES_CACHE_TTL_SECONDS`).
  - Provider health: 30 seconds (`PROVIDER_HEALTH_CACHE_TTL_SECONDS`).
- Invalidation is event-driven through the outbox consumers; a cache miss, Redis error, or malformed payload always resolves to a miss and the caller recomputes from SQL, so a cache problem never fails a request.
- Degraded mode caps every cache write to `DEGRADED_CACHE_TTL_SECONDS` (default 30) and refuses to serve long-lived entries.
- PHI cache rule: the profile and intake caches are off unless Redis is configured and `PHI_CACHE_ENABLED` is true. The managed Redis portfolio demo must keep `PHI_CACHE_ENABLED=false`. Care-cases, directory, consent-list, and provider-health caches are not PHI-gated. Even when the flag is true, no cache is populated if `REDIS_URL` is empty.

### D4 - Redis-backed rate limiter with local fallback

- `RATE_LIMIT_BACKEND` selects `memory` (default, in-process fixed window) or `redis` (shared, distributed).
- Redis selection is validated at boot: it requires a non-empty `REDIS_URL`, and the Redis key prefix is configurable via `REDIS_RATE_LIMIT_KEY_PREFIX` (default `ratelimit:`).
- When Redis is unavailable, the Redis limiter delegates to an in-memory limiter instead of failing the request. This is a local fallback, not a denial.
- `RATE_LIMIT_TIERS` is parsed and validated but is reserved in this phase; it does not change limiter behaviour yet.

### D5 - Degraded mode

- `DEGRADED_MODE` defaults to false and is a static boot setting in this phase.
- When enabled, degraded mode disables AI structuring (the pipeline falls back to mock), trims cache TTLs to `DEGRADED_CACHE_TTL_SECONDS`, and skips non-critical background work, to keep the system available under load or budget pressure. The toggle is flag-driven and adds no code path when off.

### D6 - Circuit-breaker bypass is fail-open

- `CIRCUIT_BREAKER_ENABLED` defaults to true and is a global switch.
- Every breaker wrapper (SMS, WhatsApp and notification delivery, the AI gateway, and profile media) accepts the flag. When false, the wrapper delegates directly to its inner callable: it does not count failures, cannot open, and never waits for a cooldown.
- Disabling breakers is fail-open by design, so the startup log emits a warning when they are disabled and requests continue to reach the inner adapter even after repeated failures.
- When enabled, threshold, open, and cooldown behaviour is unchanged.

### D7 - Reserved settings

- Module router flags: `MODULE_INTAKE_ENABLED`, `MODULE_CARE_ENABLED`, `MODULE_PARTNER_ENABLED`, `MODULE_AUDIT_ENABLED`, `MODULE_OBSERVABILITY_ENABLED`, and `MODULE_OPS_ENABLED` gate HTTP router inclusion at the composition root. `MODULE_NOTIFY_ENABLED`, `MODULE_SETTLEMENT_ENABLED`, `MODULE_FULFILLMENT_ENABLED`, and `MODULE_DIAGNOSTICS_ENABLED` are accepted and validated but have no matching HTTP router or other runtime effect in this phase. Flags gate routes only; they do not stop outbox handlers, worker jobs, or module facades. Directory search, IAM, health, CSRF, and the patient profile routes are never gated.
- Process identity and scale: `INSTANCE_ID` defaults to empty and is generated as a UUID per process start, stored on application state, and logged once with environment and region; it is never returned in responses. `UVICORN_WORKERS` (default 1) is templated into the deployment start command; boot fails if the in-process dispatcher runs with more than one worker.
- Dispatcher, sharding, and multi-region settings (`DISPATCHER_MODE`, `DISPATCHER_CLAIM_TIMEOUT_SECONDS`, `DISPATCHER_POLL_INTERVAL_SECONDS`, `DISPATCHER_BATCH_SIZE`, `SHARDING_ENABLED`, `SHARD_KEY`, `SHARD_COUNT`, `MULTI_REGION_ENABLED`, `REGION`, `CROSS_REGION_REPLICATION`) are accepted, validated, and intentionally inert in this phase: no dispatcher, query-routing, or region-selection behaviour changes.
- `RATE_LIMIT_TIERS` is also reserved: it is parsed and validated but does not affect limiter behaviour yet.

### D8 - Database pooling and the PgBouncer rule

- `DB_POOL_ENABLED` defaults to false (NullPool) and is enabled manually at 1K+ DAU. Pool size, overflow, timeout, and recycle are configurable.
- PgBouncer rule: operators using PgBouncer in transaction-pooling mode must keep application-side pooling off and must disable the asyncpg prepared-statement cache by appending `prepared_statement_cache_size=0` (or the driver equivalent) to `DATABASE_URL`. The application never detects PgBouncer at runtime and never selects behaviour based on it; the operator configures both.

## Deviations from the plan

1. Allowlist instead of default-allow for read replicas. The plan describes a CP denylist, but routing is implemented as an explicit allowlist of paths with the CP markers as an inner guard, so an allowlist edit cannot accidentally expose a critical path.
2. PHI cache gate. The plan treats the profile and intake caches as ordinary AP caches, but the implementation requires both Redis and `PHI_CACHE_ENABLED=true`, and keeps the managed demo off.
3. Inert reserved fields. Module reserved flags, dispatcher, sharding, and multi-region settings, and `RATE_LIMIT_TIERS`, are validated but deliberately have no runtime effect, so later features switch on through configuration rather than code changes.

## Consequences

- The default deployment stays single-primary, in-memory rate limited, and uncached when Redis is absent, so behaviour matches the pre-change baseline with all flags off.
- Stale reads remain possible only on the documented AP paths and caches; CP reads and writes never serve stale data.
- Operators bear the responsibility for the PgBouncer and PHI-cache settings; the application exposes variables but does not auto-detect topology or data classification.
- Circuit-breaker disabling is fail-open and must be treated as a debug or load-shedding switch, never as a silent default.

## Monitoring

- Cache hit and miss counters per cache namespace, Redis health, read-replica selection and unhealthy-cooldown events, outbox backlog, rate-limit fallback events, and circuit-breaker state transitions.
