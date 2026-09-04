# Brief - 261 Phase-5 fix: show credential + audit chain in detail view (S7)

**Ticket:** #261 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

`PartnerVerificationDetail` already carries `credentials: list[CredentialDetail]` (from `get_verification_detail`), but the operator detail view does NOT show the partner's **audit chain** (finding S7). Surface the audit ledger rows for that partner in the detail view. Depends on the audit reading seam that already exists.

Acceptance criteria (from #261):

- [ ] `get_verification_detail` (or the route wrapping it) returns the partner's audit events for that `partner_id` alongside the existing detail.
- [ ] Uses the existing audit query seam (`AuditFacade.query_audit(target_id=...)` / `GET /v1/audit/events`) - no new audit write path.
- [ ] Detail view tests + audit round-trip tests pass.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `PartnerVerificationDetail` (248-266), `CredentialDetail` (226-233), `VerificationRound` (236-245), and `get_verification_detail` (the function around 1104-1170; note it currently emits `credential_reviewed_envelope` at 1153-1159 but has no read-back to the ledger) (~1.5K).
2. `apps/backend/modules/audit/facade.py` `query_audit(target_id=...)` (392-416) and `apps/backend/modules/audit/adapters/routes.py` `GET /v1/audit/events` (38-74) - the read seam to reuse (~0.8K).
3. `apps/backend/modules/audit/domain/consumer.py` - the `_partner_uuid(partner_id) = str(uuid5(_AUDIT_NAMESPACE, f"partner:{partner_id}"))` deterministic mapping (123-125) + the builders that set `target_id = _partner_uuid(payload.partner_id)` (197-237, 240-282, 285+) - this is how a partner's ledger rows are keyed (~1.5K).
4. `apps/backend/modules/partner/adapters/routes.py` - the `verification_detail` route (254-273) and how error/422 mapping works (the `InvalidQueueSortError` 422 handler at 415-422 for the pattern) (~0.8K).
5. The UI prototype for the operator verification detail view (`prototype/`, gitignored - read-only reference, do not edit) - to match what the operator expects to see (~1K).

## Do NOT read

- notify/iam's consumer internals, provider channels, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Partner detail + audit tests green; run `tests/unit/test_audit_round_trip.py`-related and the partner detail tests (grep for `verification_detail` in tests)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- A partner's audit chain is `audit_events` rows where `target_id = uuid5("caresetu.audit", "partner:{partner_id}")` (the deterministic `_partner_uuid`). The cleanest read is via `AuditFacade.query_audit(target_id=_partner_uuid(partner_id))`.
- The facade already closes over the audit facade or can call it - confirm the injection pattern from the existing `credential_reviewed_envelope` emission path. Do NOT add a new outbox event just to read the ledger; this is a read-only view augmentation.
- Avoid duplicating the `_partner_uuid` mapping in `partner/` - prefer calling the audit seam. If it's private to `audit/domain/consumer.py`, either expose it via the audit facade or accept the mapping via that facade.
- Keep `PartnerVerificationDetail` backward compatible (additive field only) so the console contract and existing tests don't regress.
- This is the audit READ side; do not touch audit WRITE/consumer behavior (related #256/T13 audit work remains separate - see its brief).
