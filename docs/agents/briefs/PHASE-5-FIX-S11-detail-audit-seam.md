# Brief - 264 Phase-5 fix: surface audit chain in verification detail view (S11)

**Ticket:** #264 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Confirm - S11 and S7 overlap. Reconcile: the #261 scope (S7) covers surfacing the audit chain in the verification detail view. #264 (S11) is the audit READ-side shaping of that detail view (the "associated records + document hash chain" part of the review). Both touch `get_verification_detail` + the audit read seam. Coordinate: either merge or keep #264 as the audit-side glue that #261's detail view consumes. If both tickets are open, negotiate the seam so they don't both write the same view field.

**For this brief's primary scope:** `PartnerVerificationDetail` must expose the partner's audit ledger as a first-class field of the detail view, using the deterministic `_partner_uuid` mapping, WITHOUT duplicating the mapping in `partner/` (no `uuid5` re-implementation, no hardcoded namespace).

Acceptance criteria (from #264):

- [ ] The detail view carries an audit-chain field populated from the audit read seam (not a new write).
- [ ] The `_partner_uuid` mapping is not re-implemented in `partner/` - it's reached via the audit facade.
- [ ] If #261 already added the chain to the view, this ticket narrows to the seam/signing glue and empty-chain handling.

## Read-list (in order)

1. `apps/backend/modules/audit/domain/consumer.py` - `_partner_uuid(partner_id)` (123-125, namespace `caresetu.audit` line 39), the builders that set `target_id = _partner_uuid(payload.partner_id)` (197-237, 240-282, 285-303, 348) - the canonical mapping + row shapes (~1.5K).
2. `apps/backend/modules/audit/facade.py` `query_audit(target_id=...)` (392-416) and `apps/backend/modules/audit/adapters/routes.py` `GET /v1/audit/events` (38-74) - the read seam (~0.8K).
3. `apps/backend/modules/partner/facade.py` `get_verification_detail` (1104-1170 incl. the `credential_reviewed_envelope` emission at 1153-1159) and the view classes 226-266 (~1.2K).
4. The T13 audit brief (`docs/agents/briefs/PHASE-5-T13*`) + `tests/unit/test_audit_round_trip.py` (or the audit read test) - confirm what the T13 audit work already exposes and what's still glue (~1.2K).

## Do NOT read

- notify/iam consumer internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Audit read tests + partner detail tests green (grep `query_audit` / `verification_detail`)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The audit ledger keys a partner's rows by `target_id = uuid5("caresetu.audit", "partner:{partner_id}")`. The `_partner_uuid` helper is private in `audit/domain/consumer.py`; the fix is to reach it via the audit facade (expose it if needed), not re-derive in `partner/`.
- Do NOT start a new audit WRITE path - the chain already exists on the ledger; this is read-side surfacing.
- Overlap with #261 (S7) is real: S7 = "detail view includes the audit chain", S11 = the audit row/document-hash shaping of that view. If both land, pick ONE to add the field to the view and the other to only expose the seam. Coordinate with the #261 author (blocking edge likely exists).
- If #261 already added the field, make this ticket narrow to "document hash chain surfaced + empty-chain behavior" per S11 wording, and update acceptance criteria accordingly.
- Keep the view backward compatible (additive field) for console + tests.
