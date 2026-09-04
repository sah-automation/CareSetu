# Brief - T6 Operator audit query API

**Ticket:** #240 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Expose the operator-facing audit query API: a facade method on `AuditFacade` and a FastAPI route, both RBAC-protected, that queries `audit_events` with filters and pagination.

Acceptance criteria: see #240 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/audit/facade.py` - current facade, updated by T4 (~0.5K)
2. `apps/backend/modules/audit/schema/models.py` - `audit_events` model from T1 (~0.5K)
3. `apps/backend/modules/audit/adapters/` - routes directory, create `routes.py` if needed (~0.3K)
4. `apps/backend/modules/health/adapters/routes.py` - reference for FastAPI route patterns and RBAC enforcement (~1.5K)
5. `docs/standards/api-standards.md` - REST conventions, pagination, error envelope (~1K)
6. `docs/standards/security-phii-standards.md` - RBAC requirements for audit access (~0.5K)
7. `tests/unit/test_health_record_route.py` - example of route unit tests (~1K)

## Do NOT read

- Other module code beyond health routes, bus infrastructure internals, docs/archive/, frontend code.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all query API tests green)

## Handoff notes

- `query_audit()` on `AuditFacade`: accepts `actor_id`, `event_type`, `target_id`, `scope`, `from_ts`, `to_ts`, `page`, `page_size`. Returns `AuditPage` (paginated list + total count).
- Route: `GET /audit/events` with query parameters. RBAC: operator role required, 403 for non-operator.
- Pagination: ordered by `timestamp` DESC, default `page_size=20`, max 100.
- Pydantic models: `AuditEventView` (single event), `AuditPage` (events list + total_count).
- RBAC enforcement: use the same pattern as health routes (check user role from JWT claims).
- The query is a SELECT with optional WHERE clauses built dynamically from the filter parameters.
