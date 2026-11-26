# Brief - 266 Phase-5 fix: credential invalidated round-gated (S13)

**Ticket:** #266 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

`submit_credentials` calls `_load_live_credential_types` which reads ALL `partner_credentials` rows for the profile regardless of status/round, so old rejected rounds' types still count as "live" types for the duplicate gate (finding S13). The caller tries to compensate with a status check (`Rejected`/`Active` pass `frozenset()`) but `Registered`/`Under Verification` still sees stale types. Restrict the duplicate gate to the CURRENT round's live credential types.

Acceptance criteria (from #266):

- [ ] `_load_live_credential_types` (or its caller) restricts the duplicate gate to the current round's live credential types, so a partner who was previously rejected and is re-submitting only fights the current round's types.
- [ ] The `Rejected`/`Active` passthrough of `frozenset()` is preserved or replaced by SQL-side round filtering - whichever is correct per the round semantics.
- [ ] Duplicate-gate tests pass; a previously-rejected type is now re-offerable in a fresh round.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `_load_live_credential_types` (416-435, WHERE only on `profile_id`), its caller `submit_credentials` duplicate gate (714-724), the `_persist_re_submission_throttle` (632-668) which bounds re-submission, and the re-submission counter increment (768-787). Understand the round/decision flow (~1.5K).
2. `apps/backend/modules/partner/schema/models.py` - `partner_credentials` (104-134: `verified` bool, `expires_at`, `artifact_refs`, timestamps - NO status column) and `partner_verifications` (the round/decision rows) to see how a credential maps to its round (~0.8K).
3. `apps/backend/modules/partner/domain/rejection.py` - `evaluate_re_submission` (39-68), `MAX_RE_SUBMISSIONS=3`, `RE_SUBMISSION_COOLDOWN=timedelta(days=30)` - the re-submission budget the duplicate gate must respect (from the T09 brief; read the actual file) (~0.8K).
4. `docs/spec/phase-5-partner-onboarding.md` - the duplicate/rejection/re-submission requirements; the T09 rejection brief (`docs/agents/briefs/`) analyzed the round semantics (~1K).
5. `tests/unit/` - duplicate-gate / re-submission tests (grep `duplicate_credential` / `evaluate_re_submission` / `submit_credentials`) (~1.5K).

## Do NOT read

- notify/audit/iam internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Duplicate-gate / re-submission tests green (grep `submit_credentials` / `duplicate` tests and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The core bug: `_load_live_credential_types` has no round/status filter - its docstring (419-427) CLAIMS non-rejected-only semantics the SQL does NOT implement (WHERE is only `profile_id`).
- The caller (714-724) compensates by passing `frozenset()` for `Rejected`/`Active`, but `Registered`/`Under Verification` still receive stale types from old rejected rounds. The fix is either SQL-side round filtering (join `partner_credentials` to the current round) or passing the round id into the loader.
- `partner_credentials` has no status column - the round is in `partner_verifications`. Find the FK/round linkage (each `partner_credentials_id` may map to a round via `partner_verifications.credentials` or a join) and restrict to the current round.
- US-27 credential re-submission: keep the `re_submission_count` increment and the appeal-vs-resubmit distinction intact (appeal is a distinct path that does NOT advance the throttle - T09 brief).
- After the fix: a partner who was previously rejected for type X can RE-OFFER type X in a fresh round without tripping the duplicate gate. That is the acceptance pivot.
