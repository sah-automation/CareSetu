# Brief - 531 Consent: add health_background record scope

**Ticket:** #531 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A patient (or their doctor on the patient's behalf) can now grant and be gated on a new consent scope, `health_background`, independent of `full_record` but still subsumed by it - so patient-authored health background becomes a first-class shareable record area alongside consultations, prescriptions, lab results and metrics, and its permission makes sense to patients (US-35).

From the #529 Implementation Decisions:

- Extend the record-scope sources of truth: the `RECORD_SCOPES` tuple, the `RecordScope` Literal, and both database check constraints on the consent lineage and egress-log tables (additive Alembic migration - existing rows must stay valid; `full_record` continues to subsume every scope including the new one, per ADR-004).
- The Redis consent-gate cache key already includes the scope; confirm `_scope_subsumes` and `check_consent` match the new value and that `full_record` still passes for a `health_background` request.
- `grant_consent`, `revoke_consent` and the egress ledger accept and record the new scope unchanged in shape.

AC:

- [ ] `health_background` is a valid value in every record-scope surface (enum, Literal, both DB constraints) via additive migration; existing rows migrate unchanged
- [ ] `check_consent(..., scope="health_background")` returns allowed when a live `health_background` grant exists and when a live `full_record` grant exists (subsumption), denied otherwise
- [ ] Unit + route tests cover grant/revoke/egress with the new scope (prior art: existing consent check-gate and route tests); `npm run test:unit:backend`, `npm run migration-check` green

## Read-list (in order)

1. `RECORD_SCOPES` tuple in the consent domain state machine (`modules/consent/domain/state_machine.py`) - the closed enum to extend (~0.05K).
2. `RecordScope` Literal in `modules/consent/domain/events.py` and its duplicate in `modules/audit/domain/consumer.py` - both Literal sites must change together (grep `RecordScope`) (~0.05K).
3. The two DB CHECK constraints in `modules/consent/schema/models.py`: `consent_consents.record_scope` and `consent_egress_log.record_scope` - the `record_scope IN (...)` lists to swap plus the egress row shape (~0.7K).
4. Alembic additive CHECK-swap precedents in `apps/backend/alembic/versions/`: `7a5c02e3d481` (minimal drop/re-add of one CHECK) and `ee3394de5a38` (double CHECK swap) - copy this form; layout is flat versioned files, raw `op.execute` DDL, single-head linear chain (~1K).
5. `consent/facade.py`: `_scope_subsumes` (~0.1K), `check_consent` + `_check_consent_sql` (~0.7K), `grant_consent`/`grant_consent_on` (~0.6K), `revoke_consent` (~0.15K), and `record_egress_disclosure`/`_write_egress_log` (~0.6K) - confirm the new value flows through each unchanged.
6. The Redis consent-gate cache key in `consent/redis_cache.py` - scope is already part of the key; confirm invalidation per-scope still matches (~0.5K).
7. `docs/adr/0004-consent-gate-cache.md` - the subsumption/fail-closed contract this must not violate (~1.2K).
8. Consent route/check-gate tests under `tests/unit/` (`test_consent_*`, `test_access_history_*`) - the grant/revoke/egress test shapes to mirror (~1.5K).

## Do NOT read

- Frontend code, other schema modules (care/health/iam internals), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run migration-check` - confirmed green 2026-09-24 (single head `ca8d2419f2b6`, no cross-schema FK).
- `npm run lint` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new `health_background` grant/subsumption/denial/egress tests + existing consent suite green.
- `npm run migration-check` - still single head after the additive migration.

## Handoff notes

- `health_background` must be added to exactly five surfaces: `RECORD_SCOPES`, both `RecordScope` Literals (consent events + audit consumer), and both DB CHECK constraints. Missing any one is the classic failure mode.
- Existing rows must survive: the migration is additive (extend the `IN (...)` list), never a rewrite of stored values; `full_record` subsumption keeps old grants valid.
- No glossary/ADR work here: #530 owns the `health_background` vocabulary and the batch ADRs; run only after its terms are registered so the scope name is settled.
- No em-dashes anywhere (lint-gated); use simple dashes.
