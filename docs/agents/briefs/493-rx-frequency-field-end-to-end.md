# Brief - 493 PHASE-8.1 T10a: rx frequency field end-to-end (MOD-006)

**Ticket:** #493 · **Parent:** #486 · **Refreshed:** 2026-09-19
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

A doctor can enter a frequency (how often to take a medicine) for every medicine in the prescription editor, and the value survives the whole journey: manual authoring, AI drafts, revision save, and the issued e-prescription read. Backend gains the additive nullable `care_rx_items.frequency` column (no cross-schema FK), DTOs carry it, the facade round-trips it, and the AI intake draft shapes emit it (blank allowed).

AC:

- [ ] `care_rx_items` gains a nullable `frequency` column via an additive migration in the care module; no cross-schema references
- [ ] `RxItemInput`/`RxItemView` (care DTOs) and the frontend `RxItemInput`/`RxItemView` types carry `frequency`; a blank value is accepted and persisted as null
- [ ] `_write_rx_items`, the manual `create_rx_draft` branch, and `save_rx_revision` persist frequency; the issued read returns it
- [ ] The editor renders a Frequency input per medicine (alongside Dose/Duration); the editor item shape/handlers carry it and revision-save payloads include it
- [ ] AI drafts flow frequency: the intake `RxItem`/`RxDraftItem` shapes, facade mapping and mock emit `frequency` (optional); the draft snapshot and the `_derive_edited_yn` comparison include it so audit semantics stay symmetric
- [ ] Tests: backend route/facade frequency round-trip through create/manual, revision-save, approve and issued read; frontend editor frequency-input test; bilingual parity for the frequency label

## Read-list (in order)

1. `modules/care/schema/models.py` `care_rx_items` (L168-184; no `frequency` today) - the column to add (~200 tokens)
2. A care additive migration to mirror: `b38d0e62f4a7_v8_5__consultation_fee.py` (additive, same care schema; chain head is `ac4f18be6d92` v8_8) - the migration to author off the head (~300 tokens)
3. `modules/care/care_models.py` `RxItemView` (L77-85) / `RxItemInput` (L88-100) + `DraftSnapshot` contract (L26-28) - the DTOs gaining optional `frequency` (~250 tokens)
4. `modules/care/rx_facade.py` - `_to_rx_item_view` (L77-86), `_derive_edited_yn` (L89-109, add `frequency` to BOTH sides of the comparison), `_write_rx_items` insert (L889-910), the manual `create_rx_draft` branch (L234-290), `save_rx_revision` (L317-406), `approve_prescription` issued write/read (L407-541), `get_approved_prescription` (L634-700), the AI-draft snapshot build (L824-826) - the round-trip surface (~1.8K tokens)
5. Intake AI-draft shapes: `modules/intake/ai_gateway.py` `RxItem` (L245) / `DraftRxResult` (L253), `modules/intake/intake_models.py` `RxDraftItem` (L309) / `RxDraftResult` (L324), the facade mapping (L1357-1374), `modules/intake/adapters/ai_provider_mock.py` `draft_rx` (L108-121) - carry `frequency` as optional so AI drafts flow it (~450 tokens)
6. `lib/care/api.ts` `RxItemInput` (L43-47) / `RxItemView` (L49-56) / `RxRevisionRequest` (L91-93) - add `frequency?` (~150 tokens)
7. The case-page editor: `EditorRxItem` type (L67), `toEditorItems` (L69-74), the item change/add handlers (L586-596), the per-row Dose/Duration inputs (L1150-1200) to mirror for Frequency, and the issued item line (L1278-1291) to render it (~700 tokens)
8. `lib/i18n/dictionaries.ts` `caseWorkspace` block + Hi parity; `prototype/phase-7-8/rx-approval.html` Frequency columns (L249-287) (~350 tokens)
9. Test patterns: `tests/unit/test_care_facade_rx.py` + `test_care_routes.py` (round-trip), `api.test.ts` (type guards), the case-page `page.test.tsx` (editor test) (~500 tokens)

## Do NOT read

- Patient pick/intake consent internals, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 2306 passed, 1 failed (tests/unit/test_contract_check.py, pre-existing)
- `npm run migration-check` - single head `ac4f18be6d92`, no cross-schema FKs
- Known pre-existing (unrelated): `test_contract_check` + `test_app_shell` demo/OTP under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new frequency round-trip + edited comparison tests pass
- `npm run test:unit:frontend` - editor frequency-input + type-guard tests pass (3 pre-existing frontend fails unrelated: Daltonganj parity + 2 choose-role jsdom redirects)
- `npm run migration-check`
- `npm run typecheck`

## Handoff notes

- Frequency is nullable and never required; a blank UI input maps to `null` on submit (follow the existing `dose`/`duration` trim-or-null mapping at page.tsx L494-495).
- `_derive_edited_yn` MUST include `frequency` on both the snapshot baseline construction and the issued-items construction, so an item edited only in frequency still reads as edited (this is the guarantee #494 consumes).
- `RxDraftItem` uses `model_dump(mode="json")` into the snapshot - adding optional `frequency` there flows it into `draft_snapshot` automatically.
- No AI-prompt change is required for the mock; the mock just gains the optional field.
