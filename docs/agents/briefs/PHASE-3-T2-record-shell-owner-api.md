# Brief - T2 Record shell + owner-only record API

**Ticket:** #211 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Every newly registered patient automatically owns a longitudinal health record shell - zero setup. Owner reads their own (initially empty) reverse-chronological timeline through the record REST surface behind gateway middleware; any non-owner read attempt is denied with the shared error envelope AND recorded. Lands the health-schema core (`patient_records`, `record_entries`, `record_access_history`) as the next alembic revision continuing the linear chain after v1.2, plus the app's first real bus subscriber: `patient.registered` -> shell creation via the consumed-events ledger.

Acceptance criteria: see #211 body verbatim.

## Read-list (in order)

1. Roadmap PHASE-3 section - phase scope, the two-ledger division, dormant-producer stance (~2K)
2. Internal-modules MOD-003 spec - interfaces you are building (`create_record`, `get_own_record` owner-only), subscribed events (~1K)
3. Health module scaffold (`modules/health/`: empty facade class, placeholder table, outbox constant, no-op register_handlers) + `scripts/scaffold_module.py` - the skeleton you fill (~0.8K)
4. IAM module as structural prior art: facade construction + sub-facade split (ADR-0006), router mounting + error handlers in `create_app()`, schema models under a module MetaData (~1.5K)
5. Prior-art tests: IAM register-route unit test (StubFacade pattern); integration conftest (native Postgres engine, skip-if-unreachable); IAM registration integration test (~2K)
6. Round-trip integration harness (write_outbox -> dispatcher claim -> fan-out -> consumed_events ledger -> replay no-op) - the proof pattern for the subscriber (~1.5K)
7. `docs/standards/api-standards.md` + `security-phii-standards.md` - error envelope, RBAC dependency, PHI rules (~1K)

## Do NOT read

- MOD-004/consent design beyond the two-ledger note; provider/diagnostics/settlement modules; OTP/session internals of IAM beyond shape; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; migration-check single head `bff3fd95f3db`; backend units 654 passed; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run migration-check`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (new route-unit suites green)
- `npm run test:integration` (shell-on-registration round-trip + denial-row suites green; needs local native Postgres, skips otherwise)
- `npm run migration-check` (single head preserved, no cross-schema FKs)

## Handoff notes

- Migration continues the linear chain after `bff3fd95f3db_v1_2__session_refresh_tokens`; the spec's literal `v2.0__init_health_consent.sql` was split by decision - this ticket owns the health half (`v2_0__init_health.py` style), T3 lands the consent half.
- No cross-schema imports/SQL/FKs ever; only legal seams are facade calls + outbox events (boundary checker enforces).
- The access-history ledger records EVERY read attempt here (owner reads included) - it feeds FEAT-003 trust view in Phase 4.
- Worker composition root mirrors `register_handlers` against `MODULE_SCHEMAS` order at import time - keep the mirror exact when health gains real handlers.
