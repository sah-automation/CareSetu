# Brief - 268 Phase-5 fix: credential invalidated + doc cleanup (S15 · US-27)

**Ticket:** #268 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

US-27 promises "credential deleted/invalidated after 30 days" but the permanent-rejection path does neither today (finding S15): `operator_decision` on rejection writes `partner_rejected_envelope` and - only if the profile was `Active` - a `credential_invalidated_envelope` with `credential_id=None`, and never touches the credential/artifact rows. Add the credential-row + document cleanup (30 days) to the rejection path, gated by round semantics.

Acceptance criteria (from #268):

- [ ] Permanent rejection marks the credential(s) invalidated with the real `credential_id` (not `None`), so the `credential_invalidated` audit/event carries a resolvable id.
- [ ] The 30-day document cleanup (US-27) is scheduled/marked (not necessarily run now - see Handoff on the "deliberately no scanner" doctrine).
- [ ] The `Active -> Rejected` non-permanent case still works (reject without deleting artifacts).

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `operator_decision` (877-963: updates `partner_verifications` round row 905-918, writes `partner_rejected_envelope` 927-938, and only if `profile.status == Active` writes `credential_invalidated_envelope` with `credential_id=None` 948-958); `appeal` (839-875) for the round/recovery context; `_load_live_credential_types` pattern (416-435) for how credentials map to rounds (~2K).
2. `apps/backend/modules/partner/domain/events.py` - `CredentialInvalidatedPayload` (line ~110) which documents "Fires on permanent rejection (document cleanup after 30 days)", plus `partner/domain/exceptions.py` for the rejection error surface (~0.5K).
3. `apps/backend/modules/partner/adapters/routes.py` - the `operator_decision` route (276-302) + error mapping for the rejection surface (~0.6K).
4. `docs/spec/phase-5-partner-onboarding.md` - US-27 (30-day credential deletion) + the rejection semantics; the T10 grace/deactivation brief (`docs/agents/briefs/`) for the deactivation/expiry context (~1.2K).
5. `tests/unit/` - rejection/decision tests (grep `operator_decision` / `credential_invalidated` / `rejected`) (~1.5K).

## Do NOT read

- notify/iam transport internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Rejection/decision tests green (grep `operator_decision` / `credential_invalidated`)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- Two gaps: (1) the `credential_invalidated` event uses `credential_id=None`, which breaks any consumer (audit/iam) that needs to act on the specific credential - resolve the round's credential id and pass it; (2) there is NO 30-day cleanup mechanism - `partner_credentials` has no `deleted_at`, and there's no scheduled scanner (grace_lapse docstring at facade.py:980-982 says "deliberately NO background scanner here").
- The docstring promise lives only in `partner/domain/events.py:110` + `audit/domain/consumer.py:250` + `iam/domain/consumer.py:52`. Decide with the spec: either add a `deleted_at`/`cleanup_due_at` timestamp on `partner_credentials` rows that the periodic (Phase-6) scanner clears, or make the `credential_invalidated` event carry a scheduled-removal signal. Do NOT build a new background scanner in this ticket unless the spec explicitly demands it (the "deliberately no scanner" doctrine applies - confirm).
- Keep the non-permanent case: if the profile is NOT being permanently rejected, still mark invalid but do not delete artifacts (US-27's 30-day window applies to permanent rejection).
- The `credential_id=None` at 949-958 is the concrete defect to fix first; round semantics from #266 (#263-#266 are round-gating peers - coordinate if both land) determine WHICH credential id to emit.
