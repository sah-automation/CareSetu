# Phase 2 Remediation Fix Plan

**Status:** ready for `/to-ticket`
**Source:** Two-axis code review (Standards + Spec) of `git diff 763aca6...HEAD` (PHASE-2 T1-T11 + REM T1-T12). Decision on lockout counting rule made with the user: **SMS-cost rule**.
**Upstream targets:** `docs/roadmap/implementation-roadmap.md` §2.2, `docs/prd/project-prd.md` FEAT-001, `docs/architecture/internal-modules.md` MOD-001 §3.1 + §4.2, `docs/adr/0004-otp-challenge-and-brute-force-contract.md`, `docs/standards/third-party-integration-standards.md` §1, `docs/plans/phase2-iam-auth-plan.md`.

## Scope

Five must-fix findings from the code review plus one doc one-liner. No DB migrations, no frontend changes, no new dependencies. All changes are in-process code, config, or existing columns.

1. Circuit breaker for EXT-001 (hard `third-party-integration-standards.md` §1 breach)
2. Idempotency-Key on `POST /v1/auth/session`
3. Lockout streak consistency (SMS-cost rule, formalized)
4. Repo-wide `check_event_names` gate + extend to `otp`
5. Register-login challenge invalidation (latest-wins) + dedupe
6. Doc one-liner: roadmap migration-name drift

## Fix 1 - Circuit breaker for EXT-001

**Design:** in-process breaker at the SMS adapter seam, so the mock (dev/E2E) is untouched and the real provider gets the guard.

- `apps/backend/modules/iam/adapters/sms.py`:
  - Add `CircuitBreaker` - pure state machine (closed → open → half-open), injectable `clock` for testability.
  - Add `CircuitBreakerSmsAdapter(SmsAdapter)` wrapper. Only `SmsDeliveryError` with `retries_exhausted=True` counts (network/timeout/5xx/429 - genuine provider outage). `retries_exhausted=False` (4xx reject, bad payload) never trips the breaker.
  - While open: `send()` raises `SmsDeliveryError(..., retries_exhausted=True)` immediately, logs the `patient.auth_failed` marker with masked phone. The existing `SmsDeliveryQueue._deliver` then warns and fires `_on_delivery_failed` → `otp.failed(delivery)`, so degradation already flows through the audit path - no queue change.
  - After the cooldown, the first call is the half-open probe: success → closed (log recovery), failure → open again.
  - `build_sms_adapter`: wrap only the provider branch; mock stays unwrapped.
  - Update module docstring: drop the "later-phase concern" sentence, state the breaker contract.
- `apps/backend/app/config.py`: add `sms_circuit_breaker_threshold: int = 5` and `sms_circuit_breaker_cooldown_seconds: float = 30.0`, validated positive, read from env in `get_settings`.
- Tests in `tests/unit/test_iam_sms_adapter.py`: closed→open after N outage failures; open fast-fails without calling the wrapped adapter; contract errors do not trip; half-open probe success/failure; cooldown expiry with injectable clock. Plus a `build_sms_adapter` test asserting provider is wrapped, mock is not.

## Fix 2 - Idempotency-Key on `POST /v1/auth/session`

- `apps/backend/modules/iam/adapters/routes.py`: wrap `issue_session` in the existing `_run_idempotent` (one-line, same pattern as register/verify/resend at routes.py:145/165/186). Update the module docstring to include session in the idempotent mutations.
- No facade, store, or config change. The in-process store (TTL 300 s, non-locking in-flight duplicates) already covers this; a replayed key returns the same `SessionResult` without minting a second session.
- Tests in `tests/unit/test_iam_session_route.py`: same-key replay calls the facade once and returns the stored result; TTL expiry re-executes; no-key passes through (mirror the register route idempotency tests).

## Fix 3 - Lockout streak consistency (SMS-cost rule, formalized)

**Rule (decided):** only attempts against a challenge that was actually issued (SMS cost incurred) count toward the streak - `wrong_code`, `spent`, `expired`, `replay`. `no_challenge`, `suspended`, `locked` rejections do not count (no SMS was ever sent for `no_challenge`, so no cost; the guards are not attempts). Behavior is already correct under this rule; the fix is structural clarity + documentation + pinning tests.

- `apps/backend/modules/iam/facade.py`:
  - Extract the wrong-guess failure block (facade.py:474-524) into `_record_failed_attempt(connection, identity_id, phone_e164, decision, *, attempts, lockout_failed_attempts, lockout_until, now) -> VerifyOtpResult` - patient.auth_failed + `evaluate_failure` + counter update + otp.failed-on-threshold in one place.
  - `_reject` stays for `no_challenge`/`suspended`/`locked` (no counter, per the rule).
  - Update `verify_otp` docstring to state the rule explicitly.
- `apps/backend/modules/iam/domain/lockout.py`: clarify docstring - the facade's `FOR UPDATE` guard means `evaluate_failure` is never reached with an open window; the in-window growth line is defensive and in-window attempts never extend the lockout (genuinely temporary, ADR-0004 decision 4).
- `docs/adr/0004-otp-challenge-and-brute-force-contract.md`: decision 4 - record the counting rule (which rejection kinds count and why) and the guard's "never extends inside the window" statement.
- Tests: integration - a `no_challenge` verify attempt leaves `lockout_failed_attempts` unchanged; an `expired`/`spent` attempt increments it; a locked phone's verify attempt does not mutate the streak (confirm the existing `test_iam_resend_lockout.py` coverage and add what is missing).

## Fix 4 - Repo-wide `check_event_names` gate + extend to `otp`

- `.pre-commit-config.yaml`: `check-event-names` hook → `pass_filenames: false`, `always_run: true`, so pre-commit scans the full tree like `check-module-boundaries` does (currently only changed files pass; `test_repo_is_clean` catches the rest only in pytest).
- `apps/backend/scripts/check_event_names.py`: when invoked with no files, fall back to `git ls-files -z` (subprocess, stdlib - same as `_tracked_repo_files` in `test_event_names.py`); extend `_GATED_DOMAINS = ("patient", "otp")`; update the docstring's `otp.*` caveat.
- `tests/integration/test_iam_registration.py:168`: rename the local variable holding the `otp.sent` outbox row (the one legit snake_case token in the tree) to `sent_row` so gating `otp` has no false positive.
- `tests/unit/test_event_names.py`: add a case for the no-files → full-tree fallback path.

## Fix 5 - Register-login challenge invalidation (latest-wins) + dedupe

- `apps/backend/modules/iam/facade.py`:
  - Extract `_invalidate_pending_challenges(connection, identity_id)` (Pending → Expired) - reuse the logic already inline in `resend_otp` (facade.py:679-686).
  - In `register_patient`'s existing-phone "sent" branch, invalidate before the fresh insert, so login is latest-wins like resend (currently leaves `["Pending", "Pending"]`; the old code is shadowed, not invalidated - plan §2.4).
  - Extract the shared issue block (insert + `otp.sent` outbox + `enqueue`) into `_issue_challenge(...)` used by both `register_patient` and `resend_otp` - removes the ~25-line duplication the Standards axis flagged and pairs invalidation+issue in one helper.
  - Update `register_patient` docstring.
- Tests in `tests/integration/test_iam_registration.py`: mirror `test_resend_after_cooldown_issues_fresh_challenge_and_invalidates_pending` - existing-phone re-entry yields `["Expired", "Pending"]` and the old code no longer verifies.

## Fix 6 - Doc one-liner

- `docs/roadmap/implementation-roadmap.md:180`: "Migration Scripts: `v1.0__init_iam.sql`" → reference the shipped alembic series (`v1.0` / `v1.1` / `v1.2`).

## Suggested order & verification

Order: **5** (facade helpers first, shared by 3) → **3** → **2** → **1** → **4** → **6**. Fixes 1, 2, 4 are independent after 5/3 share the facade, so they can land in parallel PRs.

Verification per fix (repo harness, per `AGENTS.md`): `npm run test:unit:backend`, `npm run typecheck`, `npm run lint` (now exercises the repo-wide gate), `npm run test:integration` (needs native PostgreSQL), `npm run migration-check` (no schema changes expected - all changes are in-process code, config, or existing columns).

## Risks

- Breaker state resets on restart (documented, same posture as idempotency/rate-limit).
- The repo-wide event gate could surface pre-existing snake_case tokens - the only known one (a local variable at test_iam_registration.py:168) is renamed.
- Idempotency on `/session` inherits the store's documented in-process, non-locking semantics.
