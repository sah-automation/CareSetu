# Brief - T7 Patient access history API

**Ticket:** #241 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Expose the patient-facing access history API: a facade method on `HealthFacade` (delegated from `AuditFacade`) and a FastAPI route, both RBAC-protected (patient role, own record only).

Acceptance criteria: see #241 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/health/facade.py` - current `HealthFacade`, updated by T5 (~2K)
2. `apps/backend/modules/health/schema/models.py` - `health_record_access_history` model from T1 (~0.5K)
3. `apps/backend/modules/audit/facade.py` - current `AuditFacade`, updated by T4 (~0.5K)
4. `apps/backend/modules/audit/adapters/routes.py` - routes from T6 or create if not yet (~0.5K)
5. `apps/backend/modules/health/adapters/routes.py` - reference for patient RBAC patterns (~1.5K)
6. `docs/standards/api-standards.md` - REST conventions, error envelope (~0.5K)
7. `docs/standards/security-phii-standards.md` - patient data isolation requirements (~0.5K)

## Do NOT read

- Other module code beyond health and audit, bus infrastructure internals, docs/archive/, frontend code.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all access history tests green)

## Handoff notes

- `HealthFacade.get_access_history(patient_id)`: queries `health.record_access_history` for the given patient, returns `AccessHistoryView` (list of `AccessHistoryEntry`).
- `AuditFacade.get_access_history(patient_id)`: delegates to `HealthFacade.get_access_history()` via the cross-module facade seam (no direct DB access across schemas).
- Route: `GET /audit/access-history` with `patient_id` parameter. RBAC: patient role required, can only query own record (patient_id must match authenticated user's ID).
- Cross-patient rejection: if `patient_id != current_user.patient_id`, return 403.
- Empty history returns empty list, not an error.
- Pydantic models: `AccessHistoryEntry` (actor_id, actor_type, scope, accessed_at, denied, denial_reason), `AccessHistoryView` (entries list).
