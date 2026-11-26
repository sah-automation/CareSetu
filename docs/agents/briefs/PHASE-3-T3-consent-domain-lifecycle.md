# Brief - T3 Consent domain - schema, state machine, lifecycle REST

**Ticket:** #212 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A patient shares part of their record with a specific doctor, lab, or chemist themselves, and cuts it off just as easily. Lands the consent-schema core (`consents`, `consent_events`, `consent_outbox`) as the alembic revision following the health one, the pure state machine, and the consent REST surface: patient-initiated grant, revoke with one confirm, list, plus request/decline (the requester channel arrives in Phases 8/9; the API exists now and produces Requested).

Binding state machine (prototype-derived): `Requested --grant--> Granted(v1..vN) --revoke--> Revoked`; regrant -> `Granted(vN+1)`; decline closes without a grant; revoke is terminal per version; only fresh re-grant continues the lineage.

Lineage rules: re-grant mints vN+1 in the same `(patient, counterparty type, counterparty id, record scope)` lineage referenced `C-YYYY-NNN`; versions immutable once terminal; different scope to same counterparty = new lineage at v1. Scope enum: `consultations | prescriptions | lab_results | metrics | full_record`. No TTL - "how long" renders as "Until you revoke". Every action publishes `consent.requested/granted/revoked` + audit events into the module outbox in the same transaction.

Acceptance criteria: see #212 body verbatim.

## Read-list (in order)

1. Roadmap PHASE-3 section + its testing-decisions block (~2K)
2. Internal-modules MOD-004 spec - facade interfaces you build; event publications (~1K)
3. CONTEXT.md glossary Record & consent block - canonical names to use verbatim (~0.5K)
4. Consent module scaffold (`modules/consent/`) - skeleton you fill (~0.5K)
5. IAM lockout domain tests - prior art for pure-domain transition-legality tests (~0.7K)
6. IAM facade shape + route unit test StubFacade pattern (~1K)
7. Round-trip harness test - proving `consent.*` + audit fan-out (~1K)
8. `docs/standards/api-standards.md` + `security-phii-standards.md` (~1K)

## Do NOT read

- check_consent cache design (T4's job); frontend consent components; provider channels; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; migration-check single head `bff3fd95f3db`; backend units 654 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run migration-check`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (state-machine legality suites green)
- `npm run test:integration` (lifecycle over real Postgres + event round-trip incl. audit-per-action green)
- `npm run migration-check`

## Handoff notes

- Migration split decision: this ticket owns the consent half of the spec's `v2.0__init_health_consent` content; chain continues after T2's health revision if landed first (otherwise after v1.2) - single-head gate is the arbiter.
- Audit events ride the module's own outbox in the SAME transaction as the audited change; MOD-011 consumption arrives Phase 4 - emission coverage is the KPI here (100% of consent actions).
- Unique key on `(patient, counterparty_type, counterparty_id, record_scope)` carries status + version - it IS the lineage identity.
- Counterparty identity in Phase 3 is whatever the caller passes (typed enum for counterparty type); directory resolution comes with later phases.
