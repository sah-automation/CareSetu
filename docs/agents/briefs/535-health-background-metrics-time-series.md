# Brief - 535 Patient health background height/weight time series

**Ticket:** #535 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

A patient can append and view timestamped height/weight entries alongside their health-background snapshot, kept as a time series so a trend view can extend naturally later (US-23). This is owner-only authoring - the snapshot ticket already gates doctor visibility; this ticket adds the series with append/list endpoints in the same health-schema surface.

AC:

- [ ] Append and list endpoints store/return timestamped height/weight rows for the session patient, newest-first, bounded pagination
- [ ] Validation: plausible ranges, required timestamp, no client-supplied ids
- [ ] Route/facade tests cover append, empty list, list ordering, and owner scoping; `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The delivered health-background snapshot from #534 (schema tables + facade + route group) - the surface this series joins; grep `health_background` in the health module (~1.5K).
2. The health module route/facade layout from the snapshot ticket's files (`modules/health/facade.py`, `adapters/routes.py`, `schema/models.py`) - owner-scoping and route-group patterns (~1K).
3. A bounded, ordered list precedent in the module tree (newest-first paging) - e.g. the record entries / consent log / egress list read shapes (~0.5K).
4. Health route test prior art (`tests/unit/test_health_record_route.py`) - the test forms to mirror (~0.8K).

## Do NOT read

- Frontend code, consent internals beyond the gate, `docs/archive/`, anything doctor-facing (this surface is owner-only).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - append/list/ordering/scoping/validation tests green.
- `npm run lint`, `npm run typecheck` - clean.

## Handoff notes

- Runs directly on #534's delivered surface: if the snapshot ticket's schema/facade internals differ from expectation, conform to what shipped, not to this brief.
- No client-supplied ids and no DELETE/UPDATE this ticket - append/list only; revise-in-place is out of scope (v1 stores timestamped rows, per the parent spec's out-of-scope note).
- No em-dashes anywhere (lint-gated); use simple dashes.
