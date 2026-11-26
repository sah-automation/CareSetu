# Brief - 263 Phase-5 fix: district default service area validation (S10 · US-27)

**Ticket:** #263 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

`register` accepts an unvalidated `service_area_id` and simply stores it; no FK, no existence check, and no Daltonganj default seed exists despite the launch promise (finding S10, US-27 "Daltonganj default at launch"). Add service-area validation on registration and a Daltonganj default for launch. This is the application-layer concern the route docstring defers to Phase-6 - the ticket scope is to close the gap now.

Acceptance criteria (from #263):

- [ ] A submitted `service_area_id` that doesn't resolve in `partner_service_areas` is rejected (clear error), not silently stored.
- [ ] When no `service_area_id` is given at launch, "Daltonganj" is the default (seeded), matching US-27.
- [ ] No new FK is auto-added unless migration-check passes; validate in the facade before insert (see Handoff).

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `register` (498-569), `_insert_registered_profile` (345-389) which writes `service_area_id` into the insert at 375; note there is NO existence check today (~1.2K).
2. `apps/backend/modules/partner/schema/models.py` - `partner_service_areas` table (43-53: id, name, created_at, unique name; created empty, never seeded) and `partner_profiles.service_area_id` (73, BigInteger nullable, NO FK) (~0.8K).
3. `apps/backend/modules/partner/adapters/routes.py` - `open_partner_registration` (109-135) and its docstring noting the Daltonganj default is "a Phase-6 application-layer concern, not validated here" (66-67). The 422 mapping pattern (415-422) (~0.6K).
4. The alembic migration `alembic/versions/9d3a81dfcfa0_v4_0__init_partner.py` (32-41) that creates `partner_service_areas` empty - for the seed migration/insert location (or a new migration) (~0.5K).
5. `tests/unit/test_partner_registration.py`-related tests - register-path tests that must accommodate validation + defaulting (grep `service_area` / `register` in tests) (~1.2K).

## Do NOT read

- audit/notify/iam internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Partner registration tests green with the new validation/default (grep `register`/`service_area` tests and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run migration-check` (single-head gate + cross-schema FK scan) if any migration is added.

## Handoff notes

- No FK exists now and the route explicitly defers Daltonganj to Phase-6. The ticket is the application-layer gap - validate `service_area_id` resolution in the facade BEFORE the profile insert (SELECT from `partner_service_areas`), and default to the seeded "Daltonganj" row when omitted.
- If adding an FK is desired, run `npm run migration-check` (cross-schema FK scan) - but the minimal change is facade-side validation + a Daltonganj seed migration (or bulk-insert in the init migration / a seed data migration).
- "Daltonganj" appears only in comments (models.py:8,47,71; routes.py:66) - it is the documented launch default; seed it and make omission resolve to it.
- Keep `register` public signature compatible (additive optional default behavior); existing duplicate-phone/accepted-criterion-6 logic at facade.py:142 must be preserved.
- The 422 mapping pattern (like the `INVALID_QUEUE_SORT` handler at routes.py:415-422) is how a new `UnknownServiceAreaError`-style domain exception should surface - add the exception type + handler.
