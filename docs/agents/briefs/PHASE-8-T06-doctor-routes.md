# Brief - T06 Doctor Routes & RBAC

**Ticket:** #422 · **Parent:** #416 · **Refreshed:** 2026-09-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

FastAPI route adapter with doctor RBAC for all MOD-006 endpoints. Each endpoint delegates to `CareFacade` on `app.state`.

9 endpoints: `POST /cases/{id}/consult-complete`, `GET /cases`, `GET /cases/{id}`, `POST /cases/{id}/doctor-input`, `POST /cases/{id}/rx/draft`, `POST /cases/{id}/rx/{rx_id}/revision`, `POST /cases/{id}/rx/{rx_id}/approve`, `POST /cases/{id}/rx/{rx_id}/reject`, `GET /prescriptions/{rx_id}`.

### Acceptance criteria

- [ ] All 9 endpoints registered and reachable
- [ ] Doctor RBAC enforced: non-doctor gets 403, unauthenticated gets 401
- [ ] Each endpoint delegates to the correct `CareFacade` method
- [ ] Request/response schemas match the typed DTOs from `care_models.py`
- [ ] `register_handlers` wires the router into the app
- [ ] Route tests pass

## Read-list (in order)

1. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - canonical route/domain terms (`care case`, `case stage`, `e-prescription`) (~0.5K)
2. `apps/backend/modules/intake/adapters/routes.py` - route pattern: `APIRouter`, `require_partner` dependency, `PartnerFacade.resolve_partner`, `partner_type == doctor` check, envelope responses, 401/403 (~1.5K tokens)
3. `tests/unit/test_patient_intake_routes.py` - the route-boundary test convention (tertiary seam): `create_app` + stub facade + test client, RBAC-skin assertions (~0.8K tokens - read pattern, adapt for care)
4. `apps/backend/modules/care/adapters/__init__.py` - current scaffold: `register_handlers(registry)` composition root (~0.2K tokens)
5. `apps/backend/modules/care/facade.py` - both facade halves from tickets 04/05: method signatures and return types (~1K tokens)
6. `apps/backend/modules/care/care_models.py` - DTOs for request/response schemas (~0.5K tokens)
7. `apps/backend/modules/partner/facade.py` - grep for `resolve_partner` signature only (~0.2K tokens)

## Do NOT read

- Intake facade implementation (not needed)
- Domain files (already implemented)
- Consent facade, health facade
- Prototype HTML

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `python -m pytest tests/unit/test_care_routes.py -v`

## Handoff notes

- Router: `router = APIRouter(prefix="/v1/care", tags=["care"])` - follows the intake route convention.
- RBAC pattern: `require_partner` is a FastAPI `Depends()` that resolves the authenticated partner. Check `partner.partner_type == "doctor"` and return 403 if not. Check active status.
- Every endpoint gets `doctor_id = partner.id` from the resolved partner and passes it to the facade method.
- Request bodies use Pydantic models from `care_models.py`. Response envelopes follow the `{ "data": ... }` pattern.
- `register_handlers(registry)` adds the router to the app's router registry - follow the intake adapter `__init__.py` pattern.
