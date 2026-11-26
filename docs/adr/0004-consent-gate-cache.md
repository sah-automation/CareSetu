# ADR-004: Standing Grants with Fail-Closed Consent Gate and Redis Cache

**Date**: 2026-08-24
**Status**: Accepted

## Context

PHASE-3 T4 (#213) requires a fail-closed `check_consent` gate that answers
the pure four-field contract `(allowed, consent_id, version, effective_scope)`
for a given `(patient_id, counterparty_type, counterparty_id, record_scope)`.

The gate must:

- Use Redis cache keyed on `patient+scope+counterparty` for p95 < 50ms
- Fall back to SQL on `consent.consent_consents` when Redis is unavailable
- Invalidate cache on grant/revoke operations
- Subsume scopes: `full_record` grants match all specific scopes
- Be pure: no side effects, no egress writing
- Fail closed on cache miss, DB error, or unknown state

## Decision

### 1. Four-Field Contract (`ConsentDecision`)

```python
class ConsentDecision(BaseModel):
    allowed: bool
    consent_id: int | None
    version: int | None
    effective_scope: str | None
```

Returned by `ConsentFacade.check_consent()`. All fields are `None` on deny.

### 2. Redis Cache Contract

- **Key**: `consent:{patient_id}:{record_scope}:{counterparty_type}:{counterparty_id}`
- **Value**: Hash with `allowed`, `consent_id`, `version`, `effective_scope`
- **TTL**: Configurable via `Settings.redis_consent_ttl_seconds` (default 60s)
- **Behavior**: Best-effort writes, fail-closed reads (returns `None` on any error)

### 3. Cache Invalidation

- `grant_consent` → invalidates cache for the granted scope
- `grant_requested` → invalidates cache for the granted scope
- `revoke_consent` → invalidates cache for the revoked scope
- Invalidation happens **after** transaction commit (outside DB transaction)

### 4. Scope Subsumption

```python
def _scope_subsumes(requested: str, granted: str) -> bool:
    if requested not in RECORD_SCOPES:
        return False
    if granted == "full_record":
        return True
    return requested == granted
```

`RECORD_SCOPES = ("consultations", "prescriptions", "lab_results", "metrics", "full_record")`

### 5. SQL Fallback

When Redis is unavailable or `settings=None` is passed:

1. Query `consent_consents` for `status=GRANTED` matching patient+counterparty
2. Check each granted scope against requested scope using `_scope_subsumes`
3. Return first matching decision (latest version wins due to query ordering)

### 6. Fail-Closed Semantics

Any of the following → deny (`allowed=False, consent_id=None, version=None, effective_scope=None`):

- Redis connection error
- Redis read error
- SQL query error
- No matching granted consent
- Unknown `record_scope`
- Unknown patient/counterparty

### 7. App Integration

- Redis client initialized in `create_app` lifespan
- `init_redis_client(settings)` called at startup
- `close_redis_client()` called at shutdown
- Client stored in module-level variable, gracefully `None` if unavailable

## Consequences

### Positive

- p95 latency target met via Redis cache
- Zero-downtime degradation: SQL fallback works without Redis
- Cache invalidation is deterministic (after commit)
- Scope subsumption is explicit and testable
- Pure gate enables safe composition in egress paths

### Negative

- Extra Redis dependency (optional, graceful degradation)
- Cache TTL tuning required for consistency/performance trade-off
- Cache invalidation is per-scope, not per-patient (broad invalidation available but not default)

## Testing

- **Unit**: Property-style tests over `RECORD_SCOPES` enum (30 tests)
- **Integration**: Cache invalidation, SQL fallback, fault injection, full_record subsumption, isolation, latency
- All integration tests skip cleanly when PostgreSQL unavailable

## Alternatives Considered

1. **No Redis, SQL only**: Simpler but cannot meet p95 < 50ms under load
2. **Cache on grant only (not revoke)**: Stale reads after revoke - security risk
3. **Write-through cache on every check**: More complex, not needed for read-heavy workload
4. **Global patient cache invalidation**: Over-invalidates, reduces cache hit rate

## References

- Ticket #213
- CONTEXT.md glossary: "record scope", "consent lineage"
- ADR-002: Transactional Outbox as Async Seam (pattern for cache invalidation after commit)
- ADR-003: Module Isolation (facade pattern)
