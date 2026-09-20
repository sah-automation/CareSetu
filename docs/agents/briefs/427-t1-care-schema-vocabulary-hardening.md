# Brief - T1 PHASE-8 review-close: care schema and vocabulary hardening

**Ticket:** #427 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~9.4K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T1. Care schema and vocabulary hardening so the database enforces the canonical Phase 8 vocabulary. After this ticket: a care case stage can only be PreSummary / PrescriptionPending / Closed (the `consult_complete` dwell value is dropped from the CHECK), a prescription status can only be the machine's real values (`approved` is dropped from the CHECK), the verification declaration is a real boolean with a false default, every care case carries a non-null `pre_summary_id`, and a `forced_review` boolean (false default) exists for the review-close record. The approval-view DTO and any model/constant token that still admits the forbidden values are removed, and the approval path persists the declaration as a boolean.

Acceptance criteria (verbatim from ticket):

- [ ] A care-schema migration: adds `forced_review` bool (default false), makes `pre_summary_id` NOT NULL, converts `verification_declaration` to a boolean (default false), drops `consult_complete` from the case-stage CHECK, drops `approved` from the prescription-status CHECK
- [ ] The schema models and canonical-vocabulary constants admit only the canonical stage/status values; the unused approval-view DTO is deleted
- [ ] `approve_prescription` persists `verification_declaration` as a real boolean (no text true write)
- [ ] `npm run migration-check` green (single head, no cross-schema FKs)
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

**Blocked by:** None - can start immediately.

## Read-list (in order)

1. `care/schema/models.py` - the canonical constant sets (`CANONICAL_STAGES`, `CANONICAL_RX_STATUSES`, `STAGE_*`, `RX_STATUS_*`) and the `care_cases` / `care_prescriptions` / `care_rx_approvals` table defs with their CHECK constraints (`ck_care_cases_stage`, `ck_care_prescriptions_status`, `ck_care_rx_approvals_decision`). This is where `consult_complete` and `approved` must be removed and `forced_review` / `NOT NULL pre_summary_id` / boolean declaration appear. (~2.4K)
2. `care/care_models.py` - the DTO boundary: `RxApprovalView` (the approval-view DTO to DELETE), `CaseDetailView` (must surface `forced_review` for T2), `PrescriptionDetailView`. The frozensets import from `schema.models`, so removing forbidden values here is mechanical after step 1. (~1.9K)
3. Both care alembic migrations (`145ca8587d12_v8_0__init_care.py`, `384cef07d101_v8_1__care_consult_complete.py`) - the alembic style, revision chain (head = `384cef07d101`), and raw-SQL upgrade/downgrade pattern to mirror in the new migration. (~2.4K)
4. `care/facade.py` `approve_prescription` block (~L643-782) plus the declaration-gate seam `_check_approval_declaration` (~L1067-1079) - the site that today writes `verification_declaration="true"` as free text; switch to a real bool. The DB model change and this write site must agree. (~2.1K)
5. `care/domain/state_machine.py` and `care/domain/prescription_machine.py` canonical vocabulary - confirm the machines already forbid `ConsultComplete` as a dwell stage and `approved` as a status (`CaseStage` has no CONSULT_COMPLETE; `PrescriptionStatus.APPROVED_ISSUED == "issued"`), so the schema drops are alignment, not behaviour change. Skim only. (~1.2K)
6. `test_module_layout.py` + the prescription-machine canonical-status-superset assertions in `test_care_prescription_state_machine.py` + migration single-head gate (`npm run migration-check`) - the living assertions your migration must keep green. (~0.8K)

## Do NOT read

- Outbox/dispatcher internals (`bus/` dispatcher loop), intake/partner/iam modules, the frontend, `docs/archive/`.
- The rest of `care/facade.py` beyond the approve block and declaration seam.
- The case/rx transition bodies beyond the vocabulary constants (machines are not changed by this ticket).

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head `384cef07d101`, no cross-schema FK), `npm run lint` (all pre-commit hooks passed), `npm run typecheck:backend` (no issues, 222 files).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new migration + vocab-token removals keep the unit suite green
- `npm run migration-check` - exactly one head (`384cef07d101` -> your new revision), no cross-schema FK
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- The prescription machine's actual status vocabulary is `draft | doctor_reviewed | issued | rejected | fulfilled`; `approved` exists only in the schema/models CHECK and constants today - that is the drift T1 removes. The approval persists via `care_rx_approvals` (decision `approved`, which stays - only the _prescription status_ vocabulary loses `approved`).
- `verification_declaration` is today written as the string `"true"` inside the approval insert; the check constraint on `care_rx_approvals` and the Pydantic model must accept a real bool after the migration.
- `consult_complete` lives in `CANONICAL_STAGES` and the `ck_care_cases_stage` CHECK only; the machine never emits it (milestone fields `consult_completed_at/by` added in migration `384cef07d101`, not a stage). Dropping it is pure alignment.
- `forced_review` and NOT NULL `pre_summary_id` are the contract for #428 (T2) - land them in the same migration so case birth is buildable.
- Upstream sibling #426 §Implementation Decisions, "Schema and vocabulary hardening" paragraph is the governing spec for column defaults and CHECK drops.
- If any existing row-level discussion moves `pre_summary_id` semantics, this migration is where the NOT NULL is enforced; there is no seed data in unit tests relying on nullable cases (verified: tests use fixture engines, not live rows).
