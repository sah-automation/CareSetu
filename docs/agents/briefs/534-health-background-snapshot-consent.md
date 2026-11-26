# Brief - 534 Patient health background snapshot + first-save consent

**Ticket:** #534 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A patient can record their health background once - blood group, conditions, allergies, current medications, immunizations, family history - and edit it, with the first save carrying an explicit acknowledgement that this PHI becomes visible to their verified-relationship doctors (US-21, US-22). On that acknowledged first save the platform records a `health_background` standing grant to every doctor the patient currently has a live relationship with (live grant of any scope, or an open care case), per the agreed v1 mechanic - this is what later lets a gated doctor read see the data. Height/weight time series are a separate ticket (this one is the snapshot only).

The snapshot lives in its own health-schema tables keyed to the patient identity, distinct from care-generated record entries, and is surfaced to a doctor only through a `health_background` consent check later - never here. Editing after the acknowledged first save does not re-prompt.

AC:

- [ ] `GET`/`PUT` snapshot endpoints store/return the patient's health background (blood group, conditions, allergies, medications, immunizations, family history)
- [ ] The first `PUT` requires the acknowledgement flag; a first save without it is rejected; later edits do not require it (idempotent PUT preserved in the existing profile style)
- [ ] Acknowledged first save records the `health_background` grant to each live-relationship doctor atomically and durably
- [ ] Route/facade tests cover save/read/ack/re-grant, and that the snapshot is never returned to a doctor via this surface; `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run migration-check` green

## Read-list (in order)

1. The health module layout: `modules/health/facade.py` (owner-scoped reads, `get_record_as_owner` pattern), `adapters/routes.py` (the patient-owner route group + error handlers), `schema/models.py` (schema-qualified tables + CHECK style) (~1.5K).
2. A health-schema new-table migration precedent (`apps/backend/alembic/versions/9f2c41bae708_v2_0__init_health.py` or a later additive `b27d495bfe70`) - the CREATE TABLE + CHECK + index form for the new snapshot tables (~0.5K).
3. The consent facade grant surface from #531: `grant_consent`/`grant_consent_on` and the `health_background` scope (now accepted) - the atomically-durable grant call (~0.6K).
4. How a patient's live-relationship doctors are discovered: the consent grants read for a patient (grants to a counterparty, any scope, status granted) and the care open-case read (`CaseStage` != closed, assigned doctor) - grep the consent grants-list facade seam and the care case-assignment surface (~1K).
5. The `/v1/me/*` idempotent-PUT pattern from `app/main.py` (`run_idempotent`, profile PUT) - the save style the snapshot PUT must preserve (~0.4K).
6. Health route/facade test prior art (`tests/unit/test_health_record_route.py`) - the route-test forms to mirror (~1K).

## Do NOT read

- Frontend code, doctor-facing code, `docs/archive/`, the health record read/egress path (this surface never serves doctors - that is #540).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.
- `npm run migration-check` - confirmed green 2026-09-24 (single head `ca8d2419f2b6`).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - snapshot save/read/ack/re-grant tests + no-doctor-read test green.
- `npm run lint`, `npm run typecheck`, `npm run migration-check` - clean.

## Handoff notes

- Requires #531 landed: `health_background` is a live scope before this ticket can record grants with it.
- The snapshot is patient-owned health-schema data, NOT care record entries: own tables keyed by patient identity, and never wired into `read_consented_history` here (that is the doctor detail route's job in #540).
- The first-save acknowledgement is an explicit flag on the PUT request (like `verification_declaration` on approval); an idempotent replay of the first save carries the same flag.
- No em-dashes anywhere (lint-gated); use simple dashes.
