# Brief - T10 Facade guard-state & reject-path refactor

**Ticket:** #82 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~9K tokens (budget ~10K) - within budget

## Scope (verbatim)

The iam facade's internal plumbing gets the shape its four call sites deserve. The identity row-lock returns a small typed guard-state object instead of a 4-tuple destructured everywhere; the three near-identical verification rejections collapse into one shared helper; and the issue/refresh session results stop being two identical six-field models. Behaviour is unchanged - this is the refactor that makes the settled phase-2 shape easier to extend. The refresh seam stays backend-only and its status is documented.

Acceptance criteria:

- [ ] The identity guard state is a typed object consumed at every row-lock call site (no 4-tuple destructuring)
- [ ] The three verification rejections share one helper (no triplicated decision -> auth-failed-outbox -> result)
- [ ] Session results are one model, not two identical ones
- [ ] Full unit suite passes with zero behaviour change; the refresh seam's backend-only status is documented

## Read-list (in order, token estimates)

1. The iam facade - the `_lock_identity_row` guard-state helper and the four destructuring call sites (`register_patient`, `verify_otp`, `resend_otp`, `refresh_session` via `_lock_identity_by_id`); the three reject helpers (`_reject_no_challenge`, `_reject_suspended`, `_reject_locked`) and their shared decision -> `patient.auth_failed` outbox -> `VerifyOtpResult` shape; the two session-result models (`IssueSessionResult`, `RefreshSessionResult`, identical six fields); the refresh path (`refresh_session` + `_session_for_refresh` + `_mint_session_row`) whose seam is backend-only (~5K).
2. The challenge machine's failure-decision vocabulary - `Outcome`/`FailureReason`, the `AttemptDecision`/`ChallengeWriteBack` dataclasses, the `no_challenge`/`suspended`/`locked` decision constructors, plus the sibling resend and refresh decision cores - this is the vocabulary the shared reject helper must keep emitting (~1.5K).
3. The events envelope writer (`patient_auth_failed_envelope`) - the outbox payload shape the three reject paths repeat and the shared helper keeps (~0.5K).
4. The facade unit suites for verify, resend, session, and refresh - they pin the exact outcome strings, statuses, and emitted events that must survive the refactor unchanged (~2K).

## Do NOT read

Frontend, dispatcher internals, `docs/archive/`, and the behaviour-fix tickets themselves (T2/T3/T4/T7) - their results arrive as handoff, not as reading.

## Baseline verify

- `npm run test:unit:backend` (already verified green centrally: 494 passed on 2026-08-13)

## Done-verify

- `npm run test:unit:backend`
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- From parent #75: this is a smell-fix (guard-state 4-tuple, triplicated reject paths, duplicate session-result models, backend-only refresh seam), not a behaviour change. The blockers T2 (#85 lockout), T3 (#76 register cooldown), T4 (#86 async delivery), T7 (#87 access-denial audit) land first; their behaviour fixes touch the pre-refactor shape, so T10 refactors the _settled_ shape and lands last.
- Emitted events (`patient.auth_failed`, `patient.verified`) and result statuses (`verified`, `wrong_code`, `expired`, `spent`, `locked`, `sent`, `cooldown`, `suspended`, `no_identity`) must be byte-identical before and after - the PWA renders these and the unit suites pin them.
- The shared reject helper replaces the three bodies exactly: decision -> `patient.auth_failed` outbox in the same transaction -> `VerifyOtpResult`. T7 extends where `patient.auth_failed` is emitted but does not change this write.
- The refresh seam stays backend-only: no route, no frontend consumer, no outbox event - just document its status (internal-only rotation path) as part of the refactor.
