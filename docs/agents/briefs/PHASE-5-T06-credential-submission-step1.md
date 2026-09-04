# Brief - T06 Credential submission + Step-1 pre-filter

**Ticket:** #251 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Partner self-service credential submission (credential types per partner type: `medical_registration | lab_license | drug_license`); the Step-1 automated pre-filter domain logic (format/duplicate validation) - auto-fail -> `[Rejected]` never queued, pass -> `[Under Verification]` + queues + emits `partner.verification_started` (round 1); encrypted document upload under `partner/` object-storage prefix with access limited to owner + reviewing operator + audit trail (sensitive-class, not PHI).

Acceptance criteria: see #251 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - current empty `PartnerFacade` from T04/T05 (~0.2K)
2. `apps/backend/modules/partner/schema/models.py` - `partner_credentials`, `partner_verifications` tables from T01 (~0.3K)
3. `apps/backend/modules/partner/domain/` - lifecycle state machine from T04 with transition logic (~0.5K)
4. `tests/unit/test_consent_state_machine.py` - state-machine test pattern to mirror for pre-filter transitions (~1K)
5. `docs/standards/security-phii-standards.md` - credential document storage/access rules (sensitive-class, not PHI) (~0.5K)
6. `apps/backend/modules/iam/adapters/routes.py` - route pattern for multipart upload handling (~4K)
7. `apps/backend/modules/partner/outbox.py` - `PARTNER_OUTBOX_TABLE` for emitting `partner.verification_started` (~0.2K)

## Do NOT read

- operator console internals, notify internals, audit internals, docs/archive/.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (pre-filter/state unit tests green)
- `npm run typecheck`
- `npm run test:integration`

## Handoff notes

- Credential-type enum is closed per partner type: doctor -> `medical_registration`, lab -> `lab_license`, chemist -> `drug_license`. Reject submission if credential type doesn't match partner type.
- Step-1 pre-filter is pure domain logic: format validation (required fields present, non-empty), duplicate check (no same credential type already in `[Under Verification]` or `[Active]` for this partner), and known-bad value detection. Auto-fail returns partner to `[Rejected]` with a specific reason and is never queued. Pass moves partner to `[Under Verification]` (or stays if already there for a different credential type) and emits `partner.verification_started` (round 1) into the outbox.
- Document upload: encrypted object storage under the `partner/` prefix. Access limited to: the partner (owner), the reviewing operator, and the audit trail. Classification is sensitive-class (NOT PHI) per `security-phii-standards.md`. Use the existing upload/sealing pattern from the intake module if one exists, or the simplest encrypted write path.
- Re-verification: if a partner was `[Rejected]` and submits new credentials, this opens a new verification round (round N+1) with a fresh `partner.verification_started` event.
- Tests: mirror `test_consent_state_machine.py` style - pure domain unit tests for every valid and invalid transition path through the pre-filter.
