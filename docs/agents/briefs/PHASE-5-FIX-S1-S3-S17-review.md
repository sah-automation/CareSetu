# Brief - 257 Phase-5 review+commit of completed S1/S2/S3/S17

**Ticket:** #257 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Label:** `ready-for-human` (review + commit; the work is DONE, not to be re-implemented)
**Reading surface:** ~8K tokens - within budget

## Scope

NOT a fix ticket. #257 asks a human to REVIEW + COMMIT the already-completed S1/S2/S3/S17 work sitting in the working tree (uncommitted).

## What to review (read-list, in order)

1. `apps/backend/modules/partner/facade.py` - S1: `grace_lapse` writes `verification_started` outbox event (the new emit + docstring); S2: `re_submission_max=3` / `re_submission_cooldown_days=30` params threaded into `evaluate_re_submission` + `_persist_re_submission_throttle` (~0.8K).
2. `apps/backend/app/config.py` + `apps/backend/app/main.py` + `.env.example` - S2: `DEFAULT_PARTNER_RE_SUBMISSION_MAX`/`COOLDOWN_DAYS` settings, `partner_re_submission_max`/`_cooldown_days` field validators ("must be positive"), env reads `PARTNER_RE_SUBMISSION_MAX`/`COOLDOWN_DAYS` (~0.8K).
3. `apps/backend/modules/iam/domain/events.py` + `apps/backend/modules/iam/identity_facade.py` - S3: removed `PartnerRegisteredPayload` + `partner_registered_envelope` + `EVENT_PARTNER_REGISTERED` import; `create_credential_account` now does NO outbox write. This is the `partner.registered` sole-producer sourcing (MOD-002 Partner owns it) (~0.6K).
4. `apps/backend/modules/audit/domain/consumer.py` + `apps/backend/modules/audit/facade.py` + `apps/backend/modules/audit/adapters/__init__.py` - S17: mirrors `PartnerRegisteredPayload`/`CredentialInvalidatedPayload`, `build_partner_registered_row` (scope `partner_registration`) / `build_credential_invalidated_row` (scope `partner_credentials`), `append_*` events, `partner.registered` payload-model registration (iam already owns `credential.invalidated` - no duplicate registered) (~1.2K).
5. The verified test edits: `tests/unit/test_partner_verification_facade.py` (`test_grace_lapse_drops_active_to_under_verification_and_requeues`), `tests/unit/test_iam_partner_credential.py` (rewritten: `test_creates_identity_only_in_one_transaction` / `test_writes_no_outbox_event` / `test_never_grants_a_role`, with `_FakeResult`/`_FakeScalar`), `tests/unit/test_audit_consumer.py` (row-builder + handler + registry-slot tests), `tests/integration/test_iam_partner_credential_account.py` + `tests/integration/test_partner_registration.py` (~2K).

## Baseline verify (before committing)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q` - anticipated 1105 passing
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/integration/test_iam_partner_credential_account.py tests/integration/test_partner_registration.py tests/integration/test_audit_round_trip.py -q` - expected green (baseline pre-existing failures in `test_bootstrap_schemas::test_upgrade_head`, `test_consent_check_gate::test_p95_latency`, `test_iam_schema::test_upgrade_head` are NOT caused by this work - verified against a fresh HEAD worktree at 81b8d56)
- `npm run typecheck` + `npm run scan` + `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- The reviewer confirms the four items match the ticket's S1/S2/S3/S17 descriptions and the two-axis review intent (STANDARDS + SPEC axes), then COMMITS.
- Commit message should reference #243 and identify S1/S2/S3/S17. Follow the repo commit style (grep recent `git log --oneline`).

## Handoff notes

- Do NOT re-implement; the work is already in the tree. This ticket exists so the changes get a deliberate two-axis review before landing (the code-review skill's own deferral note: "reviewer must close or push a ticket").
- S3 scope reminder: `credential.invalidated` payload OWNER stays iam (iam/adapters/**init**.py:106) - audit registers NO duplicate for it; `partner.registered` is the only registered payload model in audit's `adapters/__init__.py`.
- The three integration baseline failures were reproduced on a clean commit; if the reviewer sees them, attribute to baseline, not this work (note in the review).
- After #257 lands, the S4-S19 fix tickets (#258-#270) remain open; each got its own brief in `docs/agents/briefs/PHASE-5-FIX-*`.
