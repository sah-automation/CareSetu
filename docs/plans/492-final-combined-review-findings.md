# #492 - PHASE-8.1 completion: final combined two-axis code-review findings

**Branch:** `feat/phase-8-care-eprescription` · **Ticket:** #492 (parent #479) · **Date:** 2026-09-20
**Status:** Review run; two real bugs fixed in follow-up commits; remaining findings triaged and deferred (recorded below). Repo harness green after fixes.

---

## 1. Fixed point and reviewed diff

**Fixed point:** `2a3a7bd` (the parent of `aec346d` = T1 #478). The reviewed diff is exactly this delivery:

`git diff 2a3a7bd...HEAD` = commits `aec346d`(#478), `9fdd9df`(#480), `eab482f`(#481), `1aed6f2`(#482), `514771a`(#483), `e256937`(#484), `7536b32`(#485), `74bcdfa`(#493), `013f1a4`(#494), `ae0108c`(#495), `361ff3b`(#487), `01965a8`(#488), `80fdf2d`(#489), `a7ff9e5`(#490), `64cc10d`(#491) - 86 files, +8655 rows vs the pre-delivery tree.

## 2. Baseline verify (pre-edit, recorded per brief)

| Gate                         | Result                                                  |
| ---------------------------- | ------------------------------------------------------- |
| `npm run lint`               | Passed (all hooks)                                      |
| `npm run typecheck`          | Passed (backend mypy + frontend tsc)                    |
| `npm run migration-check`    | single head `b9410c5ef278`, no cross-schema FK          |
| `npm run test:unit:frontend` | 85 files / 1108 tests passed                            |
| `npm run test:unit:backend`  | 1 failure - pre-existing drift, not delivery-introduced |

The single backend failure (`test_contract_check.py::test_real_api_ts_passes_against_real_openapi`) asserts `len(endpoints) == 7` while the client traces 9 auth endpoints. The partner surface (`partner/login`, `partner/verify`) was added in F014 (phase 5, pre-fixed-point), so the count drifted before this delivery. `npm run check:contract` already reports "9 auth client endpoint(s) match". Fixed to `== 9` with a corrected comment (see Fix 3).

## 3. Two-axis review (both sub-agents reported)

### Standards axis

1. **Hard - 1,802-line component.** `apps/frontend/src/app/(doctor)/doctor/cases/[caseId]/page.tsx` exceeds the coding-standards module-size guidance by an order of magnitude. **NOT a regression** (born and grown over this delivery's workspace tickets as additive work) → **DEFER**; splitting is a re-cut, not a review-fix.
2. **Hard - backend user-visible copy.** `apps/backend/modules/care/adapters/routes.py` carries four user-facing copy strings (`MESSAGE_CARE_RX_CONSENT_DENIED`, `MESSAGE_CARE_RX_NO_DOCTOR_INPUT`, `MESSAGE_CARE_RX_DRAFT_CAP_REACHED`, `MESSAGE_CARE_CASE_CLOSED`); api-standards assigns copy to the client. These are **dormant** (the client never surfaces the `message` field for these codes; matching copy lives in the frontend STRINGS map) → **DEFER** (recorded).
3. **Minor - duplicated literal.** `MAX_REJECTED_DRAFTS = 2` (care `prescription_machine.py`) is re-printed verbatim in the draft-cap copy string; a bump without a copy update would lie. → **DEFER** (recorded).
4. **Minor - magic length.** `REVIEW_QUEUE_SNIPPET_MAX_CHARS = 120` hardcoded in the review-queue frontend fetch instead of shared with the backend truncation. → **DEFER**.
5. **Judgement - duplicated derivation.** The frontend `countEditedRxItems` re-implements the backend's `_derive_edited_yn` (depth-1 comparison, stable-name keying). Drift risk only; both sides were green in review. → **DEFER**.
6. **Judgement - consent bundling (#480).** The doctor-pick consent prompt bundles DE-IDENTIFIED + SERVICE, which the FEAT-002 one-grant model splits. Delivered per #480's own spec decision. → **DEFER** (recorded).
7. **Judgement - primitive obsession / data clumps.** `gender`/`preferred_language` pass through as bare strings and case/patient fields clump across views. Cosmetics, no behavior risk. → **DEFER**.

### Spec axis (against #479)

1. **Reg-no attribution (US14 / D-C) never delivered.** Verified via `gh issue view 495`: `#495 rx-regno-attribution` explicitly re-scoped reg-no out ("no scalar reg-no exists; `medical_registration` is the encrypted document artifact"). Not a `#479` gap - a re-scope recorded at the ticket level. → **DEFER** (spec-note).
2. **Typed addendum mislabelled as voice (D-B / US15).** The workspace's typed addendum (`rx_input` clip ticket + `addendum.txt` blob) was persisted with `input_type="voice"` because `care_doctor_inputs` only admitted `voice`/`photo`. The audit row and AI-draft gate therefore read a text addendum as a voice input. **REAL BUG** → **FIXED** (Fix 1).
3. **AI-draft gate not hydrated server-side.** `hasDoctorInput` lived in client state only; a hard refresh of a PrescriptionPending case re-showed the capture surface, re-locked the draft button, and required a re-upload despite the server already holding the input. **REAL BUG** → **FIXED** (Fix 2).

## 4. Fixes (follow-up commits, never amends)

### Fix 1 - typed addendum is a real `text` input

- `apps/backend/modules/care/schema/models.py`: `INPUT_TYPE_TEXT`, added to `CANONICAL_INPUT_TYPES`; `ck_care_doctor_inputs_input_type` widened to `('voice', 'photo', 'text')`.
- New migration `apps/backend/alembic/versions/ca8d2419f2b6_v8_10__care_doctor_input_text.py` (single head `ca8d2419f2b6`): DROP/ADD the CHECK.
- `apps/backend/modules/care/adapters/routes.py`: `DoctorInputRequest.input_type: Literal["voice", "photo", "text"]`.
- `apps/backend/modules/care/case_facade.py`: `submit_doctor_input` widened to `Literal["voice", "photo", "text"]`; docstring updated.
- `apps/frontend/src/lib/care/api.ts`: `DoctorInputType = "voice" | "photo" | "text"`.
- `apps/frontend/src/app/(doctor)/doctor/cases/[caseId]/page.tsx`: `handleAddendum` posts `input_type: "text"`.
- Tests: `test_care_facade_consult.py::test_submit_doctor_input_records_text_input`; `[caseId]/page.test.tsx` renamed + asserts `{ input_type: "text" }`.

### Fix 2 - `hasDoctorInput` hydrates from the server

- `apps/backend/modules/care/care_models.py`: `CaseDetailView.has_doctor_input: bool = False`.
- `apps/backend/modules/care/case_facade.py`: `_case_ids_with_doctor_input(connection, case_ids)` (single `SELECT DISTINCT case_id FROM care_doctor_inputs WHERE case_id IN (...)` - one query for any batch, never an N+1); wired into `mark_consult_complete`, `close_case_without_rx`, `get_case`, and `list_doctor_cases`.
- `apps/frontend/src/lib/care/api.ts`: `CaseDetailView.has_doctor_input: boolean` + `isCaseDetailView` guard includes it.
- `apps/frontend/src/app/(doctor)/doctor/cases/[caseId]/page.tsx`: `load()` calls `setHasDoctorInput(c.has_doctor_input)`.
- Tests: `test_get_case_hydrates_server_side_doctor_input`, `test_get_case_returns_typed_view` asserts `False`, list test asserts per-case projection; frontend `[caseId]/page.test.tsx` "hydrates the AI-draft gate from a server-side doctor input on reload".

### Fix 3 - pre-existing drift unblocking the harness AC

- `tests/unit/test_contract_check.py`: `assert len(endpoints) == 7` → `== 9` with comment corrected (7 auth endpoints + `GET /v1/me` + dev OTP reader).

## 5. Done-verify (after fixes)

| Gate                         | Result                                         |
| ---------------------------- | ---------------------------------------------- |
| `npm run test:unit:backend`  | 2328 passed                                    |
| `npm run test:unit:frontend` | 1109 passed (85 files; +1 new hydration test)  |
| `npm run typecheck`          | backend mypy + frontend tsc clean              |
| `npm run lint`               | all pre-commit hooks passed                    |
| `npm run migration-check`    | single head `ca8d2419f2b6`, no cross-schema FK |

No regressions introduced: the only behavioral deltas are the two bug fixes above; all other changed lines are fake-connection result slots (the added doctor-input query) and fixture field defaults.
