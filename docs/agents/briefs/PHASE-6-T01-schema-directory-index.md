# Brief - PHASE-6-T01 Directory Schema & Credential Expiry Fields

**Ticket:** #307 · **Parent:** #306 · **Refreshed:** 2026-09-05
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The database foundation for the provider directory: a `directory_index` table in the `partner` schema (one row per `[Active]` partner with geo point, partner type, specialty) and new credential fields enabling expiry/revocation tracking. A specialty enum for doctors and a `CredentialInvalidatedReason` enum (expired, revoked) are introduced. Existing `[Active]` doctor partners are backfilled into the index.

Acceptance criteria (from ticket):

- Migration creates `partner.directory_index` with: partner_id (PK/FK), practice_latitude, practice_longitude, partner_type, specialty (nullable, doctors only), is_active, created_at, updated_at
- Migration adds `revoked_at` (TIMESTAMPTZ), `revoked_by` (UUID), `invalidation_reason` (VARCHAR) to `partner_credentials`
- Specialty enum: General Physician, Pediatrician, Gynecologist, Dentist
- `CredentialInvalidatedReason` enum extended with `expired` and `revoked` values
- Idempotent backfill: all current `[Active]` doctor partners with valid credentials inserted into `directory_index`
- `npm run typecheck` and `npm run migration-check` pass

## Read-list (in order)

1. `CONTEXT.md` - glossary Phase 6 section (provider, directory entry, specialty, verified, credential expiry/revocation definitions) + "register changes there" rule. Gives the canonical vocabulary and the constraint that provider is display-only. (~2K)
2. `internal-modules.md` §3.2 (MOD-002 spec) and §5 traceability - module's storage list confirms `directory_index` (geo, specialties, active flag) is anticipated. (~1.5K)
3. `docs/adr/0012-directory-entry-unit-per-partner.md` - one entry per partner, one geo point, multi-location deferred. This is the governing shape decision. (~1K)
4. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - lazy read-hide + daily sweep, no scanner; the credential-field additions serve this. (~1.5K)
5. `apps/backend/modules/partner/schema/models.py` - existing `partner_profiles` (has practice_latitude/longitude NOT NULL, partner_type, status), `partner_credentials` (has expires_at already), `partner_service_areas`. New tables/columns join these. Mirror existing SQLAlchemy style (mapped columns, FK patterns). (~2K)
6. `apps/backend/modules/partner/domain/credentials.py` - `CredentialType` StrEnum + `ALLOWED_CREDENTIAL_TYPES_BY_PARTNER`; aligned enums go here. (~1K)
7. `apps/backend/alembic/versions/` - latest head is `2c9f3a7b5d41_v5_5__partner_credential_round.py`; new migration uses `down_revision` = that head, hand-written `op.execute` SQL (not autogenerate), never imports current source (ADR-0003). Migration style baseline. (~1K)

## Do NOT read

- Frontend code, consent/Redis module, IAM module, notify module, prototype files, `docs/archive/`, ADR-0008+ beyond 0011/0012.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1205 passed)
- `npm run migration-check` - PASSED 2026-09-05 (single head `2c9f3a7b5d41`, no cross-schema FK)

## Done-verify (acceptance criteria → commands)

- `npm run typecheck`
- `npm run migration-check` (single head, downgrade base clean)
- `npm run test:unit:backend` (existing tests stay green; backfill logic unit-tested)

## Handoff notes

- `partner_credentials.expires_at` already exists (nullable); Phase 6 adds the close-out fields `revoked_at`, `revoked_by`, `invalidation_reason` alongside it.
- Practice geo coordinates are already NOT NULL on `partner_profiles` - the directory index can read them directly; no backfill of geo needed.
- The directory index is a read-side cache of `[Active]` partners; the `is_active` flag is derived from partner status (de-index on activation loss). ADR-0012 confirms one entry per partner_id.
- Test infrastructure: integration tests use live Postgres + `alembic upgrade head` then `downgrade base`; keep migrations reversible.
