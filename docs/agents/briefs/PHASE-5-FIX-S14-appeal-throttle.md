# Brief - 267 Phase-5 fix: appeal honors re-submission throttle (S14)

**Ticket:** #267 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The spec says both the appeal AND the re-submission are rate-limited ("Both are rate-limited (max 3 re-submissions)") but `appeal` does NOT call `_persist_re_submission_throttle` - only `submit_credentials` does (finding S14). The appeal path can therefore be used to bypass the re-submission throttle. Gate the appeal through the same throttle budget.

Acceptance criteria (from #267):

- [ ] `appeal` calls/runs the throttle (`_persist_re_submission_throttle`) and is blocked when the partner's re-submission budget is exhausted, matching the spec's "max 3 re-submissions" for both paths.
- [ ] A blocked appeal produces the same throttle error/422 surface as a blocked re-submission.
- [ ] Existing appeal + re-submission tests extend; an appeal when budget exhausted is rejected.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - `appeal` (839-875: requires `REJECTED` else `PartnerNotRejectedError`, `not appeal_used` else `AppealAlreadyUsedError`, `_apply_transition(START_VERIFICATION...)`, sets `appeal_used=True`, writes `verification_started_envelope`) vs `_persist_re_submission_throttle` (632-668: loads profile, `None` unless `REJECTED`, `evaluate_re_submission`, persists `re_submission_blocked_until`). Confirm appeal does NOT call it today (~1.2K).
2. `apps/backend/modules/partner/domain/rejection.py` - `evaluate_re_submission` (39-68), `MAX_RE_SUBMISSIONS=3`, `RE_SUBMISSION_COOLDOWN=timedelta(days=30)` (~0.8K).
3. `apps/backend/modules/partner/domain/exceptions.py` + `routes.py` - the throttle error + its 422 mapping (from the `_persist_re_submission_throttle` / re-submission surface, mirror it for appeal) (~0.6K).
4. `docs/spec/phase-5-partner-onboarding.md` - the appeal/rejection/throttle requirements (REQ-008, US-29); the T09 rejection brief (`docs/agents/briefs/`) already analyzed `evaluate_re_submission` + `MAX_RE_SUBMISSIONS` (~1K).
5. `tests/unit/` - appeal + throttle tests (grep `appeal` / `re_submission` / `blocked_until`) (~1.2K).

## Do NOT read

- notify/audit/iam internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- Appeal + throttle tests green (grep `appeal` / `re_submission` tests and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The bug is a bypass: `appeal` currently does not guard on the re-submission budget, so a partner who exhausted their 3 re-submissions can still appeal to restart verification. The spec's "max 3 re-submissions" applies to both recovery paths.
- Reuse the EXACT same error + 422 shape as `submit_credentials`' throttle block (whatever `ReSubmissionThrottledError`-style domain exception it raises), so client handling is uniform.
- Preserve the appeal-vs-resubmit distinction: an accepted appeal still sets `appeal_used=True`, still emits `verification_started_envelope`, and STILL must not double-advance the counter - it should be rate-limited, not merged into the re-submission counter. The throttle budget check applies; the counter semantics stay distinct (per the T09 brief).
- The `_apply_transition(START_VERIFICATION, verification=True)` in appeal (857-859) must only fire if the throttle gate passes; otherwise the appeal is rejected before any transition side-effects.
