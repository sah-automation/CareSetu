# Brief - 486 Rx editor frequency + edited-items tracker + reg-no attribution

**Ticket:** #486 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

The prescription editor carries a complete schedule: add a `frequency` field per medicine (additive MOD-006 delta: `care_rx_items.frequency` column + DTOs), show "N items edited by you" derived against the immutable draft snapshot in the approval view, and surface the reg-no attribution on issued e-prescriptions (the visible reg number, not the static "Attributed to you"). Frequency flows through create/manual, revision save, and the issued read.

AC:

- [ ] `care_rx_items` gains a nullable `frequency` column (additive migration, no cross-schema); `RxItemInput`/`RxItemView` carry it
- [ ] The editor renders a frequency input per medicine and it persists through revision save and issued read
- [ ] The approval view shows "N items edited by you" derived from comparing the working revision against the immutable draft snapshot (audit-transparent `edited_yn`)
- [ ] An issued e-prescription shows the doctor's reg-no attribution
- [ ] Manual authoring and AI draft both flow frequency; blank frequency is allowed
- [ ] Tests: backend route/facade (frequency round-trip, edited-count), frontend editor + approval tests, bilingual parity

## Read-list (in order)

1. `modules/care/schema/models.py` `care_rx_items` (L168-184; no `frequency` column today) + a care alembic migration (`5df27e3710db` v8_3 pattern, chain HEAD `0f205ff8f67d` v8_7) - the additive column + migration to match (~600 tokens)
2. `modules/care/care_models.py` `RxItemInput` (L88-100) / `RxItemView` (L77-85) / `PrescriptionDetailView` (L103-138, has `attributed_doctor: int | None`) - the DTOs gaining `frequency` (~400 tokens)
3. `modules/care/rx_facade.py` - `_write_rx_items` (L889-910, item persistence that must carry frequency), `create_rx_draft` manual branch (L234-280), `save_rx_revision` (L317-406), `approve_prescription` (L407-541) + `_derive_edited_yn` (L89-109) - the round-trip and the edited-count derivation (~1.6K tokens)
4. `app/(doctor)/doctor/cases/[caseId]/page.tsx` - editor section (L624-749, Medicine/Dose/Duration inputs + `EditorRxItem` shape L54), approval section (L838-931), issued attribution UI (L791-796, static today) (~1.2K tokens)
5. `lib/care/api.ts` - `RxItemInput` (L43-47) / `RxItemView` (L49-56) no frequency today, `fetchApprovedPrescription` (L335-344), working-read + revision types (~600 tokens)
6. `prototype/phase-7-8/rx-approval.html` - binding visual spec: Frequency columns (L249-287), edit-tracker (L236 + JS L475-524), "Issuing doctor name + reg no is attributed" spec note (L418) (~500 tokens)
7. Doctor reg-no source: partner credential/profile read for the `attributed_doctor` partner - find the existing doctor-facing reg-no read (grep `medical_registration`) and reuse it; no new schema (~400 tokens)
8. `lib/i18n/dictionaries.ts` `caseWorkspace` block + parity; `tests/unit/test_care_routes.py` + care lifecycle test + case-page test patterns (~700 tokens)

## Do NOT read

- Patient pick/intake, consent internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run migration-check`
- Known pre-existing (unrelated): `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - frequency round-trip, edited-count, attribution payload
- `npm run test:unit:frontend` - editor frequency input, approval tracker, issued reg-no render, parity
- `npm run migration-check`
- `npm run typecheck`

## Handoff notes

- `edited_yn` semantics are unchanged - the UI only displays what the audit already derives.
- Frequency is nullable: manual authoring and AI drafts may leave it blank; only persisted, never required.
- The reg number comes from the doctor/partner profile attribution already on the prescribed record (`attributed_doctor`) - surface it via the existing partner credential/profile read; no new schema per the ticket.
