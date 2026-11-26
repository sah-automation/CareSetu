# PHASE-8.1 case workspace unreachable: born-but-unclaimed care case is undiscoverable

**Branch:** `feat/phase-8-care-eprescription` · **Date:** 2026-09-19
**Status:** Plan written for `/to-spec` in a fresh session. Bug found by the localhost
browser walkthrough of PHASE-8.1 (patient pick-a-doctor -> doctor console -> case
workspace). No fix applied yet.

---

## 1. Problem statement

Browser walkthrough (localhost, mock pipeline) steps 1-6 work: operator login, doctor
register + activate, patient OTP login + text intake, pick-a-doctor, doctor review-queue
finalize. **Step 7 is a dead end**: there is no way to reach the case workspace.

Observed symptoms (any one of):

- Doctor console "Open cases" section is always empty, even after the doctor finalized the
  review (the care case should appear there).
- Direct navigation to `/doctor/cases/[caseId]` shows a load-error banner (the backend read
  returns `CARE_NOT_FOUND`, 404).
- On `/doctor/review/[intakeId]`, after a one-action finalize, no consult-complete handshake
  button ever appears (it is gated on a matched care case which is never found).

## 2. Root-cause chain (confirmed, with DB evidence)

1. The care case is birthed asynchronously on `pre_summary.ready` with **`doctor_id = NULL`**.
   The consumer inserts only `patient_id`, `pre_summary_id`, `stage`, `forced_review`
   (`apps/backend/modules/care/adapters/__init__.py:216-225`). `pre_summary.ready` fires at
   BOTH AI-draft creation (`apps/backend/modules/intake/adapters/pipeline.py:789-798`) and
   final review (`apps/backend/modules/intake/facade.py:983-1000`); the consumer is
   idempotent (unique index `uq_care_cases_pre_summary_id`, v8_3), so exactly one case exists.
2. `GET /v1/care/cases` -> `list_doctor_cases` filters
   `care_cases.doctor_id == doctor_id` (`apps/backend/modules/care/case_facade.py:313-317`).
   `NULL` never equals the doctor id, so **born-but-unclaimed cases never appear in "Open
   cases"**.
3. `GET /v1/care/cases/{id}` -> `get_case` -> `check_case_ownership(allow_unclaimed=False)`
   (`apps/backend/modules/care/case_facade.py:296`, guard at `:97-99`) raises
   `CareNotFoundError` for a `doctor_id IS NULL` case, so **the case workspace URL 404s even
   when guessed**.
4. The review workspace resolves the matched case via the same `listOpenCases`
   (`apps/frontend/src/app/(doctor)/doctor/review/[intakeId]/page.tsx:101-115,222-226`), so
   `careCase` stays `null`; `showHandshake` requires `careCase != null`
   (`:258`), so the **consult-complete handshake (the only claim path,
   `mark_consult_complete` with `allow_unclaimed=True`) never renders** - and downstream
   drafting/approval is unreachable.

A case is claimable ONLY by `mark_consult_complete` (`allow_unclaimed=True`), but every
surface that could open it (`list`, `get_case`, rx reads) hides it. Net: deadlock.

**Live-DB proof (read-only SELECT against local Postgres during the walkthrough):**

```
care.care_cases:   (1, patient_id=48, doctor_id=None, pre_summary_id=1, stage='pre_summary')
intake.intake_intakes: intake 2 -> assigned_partner_id=10   (the case's pre-summary intake)
```

The case exists, is assigned to doctor 10 via the intake, and is both invisible to the list
and un-openable to that doctor.

## 3. Red-capable repro

With the local servers running (backend `uvicorn app.main:app --port 8000` + dispatcher,
frontend `next dev`), drive the walkthrough to post-pick/post-finalize, then from the doctor's
browser devtools:

```js
// GET /v1/care/cases -> returns [] (bug: the born-assigned case is absent)
fetch("http://localhost:8000/v1/care/cases", {
  headers: {
    Authorization: "Bearer " + localStorage.getItem("caresetu.access_jwt"),
  },
})
  .then((r) => r.json())
  .then(console.log);
// GET /v1/care/cases/<birthed id> -> returns 404 CARE_NOT_FOUND (bug: assigned doctor can't open it)
```

Backend log meanwhile shows the case-birth line (`birthed care case for pre_summary_id=...`).

## 4. Design decision

**Adopted: Option A - assigned-doctor discoverability.** Make born-but-unclaimed cases
discoverable to the doctor the intake was assigned to (pick, #443). The claim stays at
`mark_consult_complete` exactly as designed (`check_case_ownership` keep
`allow_unclaimed=True` on the handshake).

Rationale vs the alternative (claim-at-finalize via `pre_summary.ready` carrying `doctor_id`):

- A preserves the pre-finalize review workspace's consented-history section (`#451` AC: doctor
  reads full pre-summary + consented history inside the workspace) and matches the already
  recorded "claimable by the first doctor who completes the handshake" posture
  (`docs/plans/t9-review-close-findings-plan.md` §4 F3 - which NOTE-ONLY'd this exact gap at
  the backend-only review; the Phase 8.1 frontend surfaced it as a real product dead-end).
- B is a smaller diff but leaves the case invisible until finalize and would not render the
  review-history section, regressing `#451`'s AC.

Scoping rule (security, mirrors the review-queue predicate at
`apps/backend/modules/intake/facade.py:791-793`): an unclaimed case is returned/readable ONLY
when `intake_intakes.assigned_partner_id == calling doctor`. A foreign or unassigned doctor
still gets `CARE_NOT_FOUND` (existing behavior preserved).

## 5. Implementation steps

### Step 1 - intake facade seam

`apps/backend/modules/intake/facade.py` - add one read-only method on `IntakeFacade`:

```python
async def assigned_partner_for_pre_summaries(
    self,
    pre_summary_ids: Sequence[int],
) -> dict[int, int | None]:
```

- One query: `intake_pre_summaries` join `intake_intakes` on `intake_id`, filter
  `intake_pre_summaries.id IN (pre_summary_ids)`, return `{pre_summary_id: assigned_partner_id}`
  (None when not yet picked).
- Ids only, PHI-free, same shape as existing facade reads. Purpose-built for the care
  discoverability seam (legal cross-module seam: care already receives `IntakeFacade`).

### Step 2 - care whole-case discoverability

`apps/backend/modules/care/case_facade.py`:

- `list_doctor_cases`: return claimed non-closed cases (`doctor_id == doctor`) PLUS
  unclaimed non-closed cases (`doctor_id IS NULL`) whose pre_summary resolves via the seam to
  this doctor. Merge, order by `created_at` ascending (keep the current declared order).
- `check_case_ownership`: add an optional async resolver argument, e.g.
  `assigned_doctor_of: Callable[[int], Awaitable[int | None]] | None = None`
  (pre_summary_id -> assigned partner id). When `row.doctor_id IS NULL` and
  `allow_unclaimed=False`:
  - if `assigned_doctor_of` resolves the case's pre_summary to the caller -> allow (read path);
  - else -> keep the existing `CareNotFoundError`.
  - `mark_consult_complete` keeps `allow_unclaimed=True` (claim path unchanged).
- Wire the intake resolver at the call sites in `CaseConsoleFacade` (it already holds
  `self._intake_facade`, `case_facade.py:115-117`). Keep `rx_facade` reads resolving through
  the same resolver (it already receives `intake_facade`, per
  `apps/backend/app/main.py:304-312`) so the working-rx read of an assigned unclaimed case
  behaves consistently; a non-assigned doctor is still refused.

Design note: `check_case_ownership` is a shared module-level guard imported by `rx_facade`.
Prefer extending it with an optional resolver (default `None` = today's behavior) so existing
tests and any future caller keep working; do not move it to a method without checking the
imports in `rx_facade` and its tests.

### Step 3 - no app-shell / route / frontend changes

- `create_app` needs no edit (both care facades already get `intake_facade`).
- Routes unchanged (they forward `doctor_id`; RBAC posture `_require_doctor` untouched).
- Frontend unchanged: `listOpenCases`/`fetchCareCase` start returning the assigned case, so
  the console list, the review-workspace match, and the handshake all appear with no client
  edit.

### Step 4 - tests

`tests/unit/test_care_facade_consult.py`:

- Extend `test_list_doctor_cases_returns_only_open_cases` (line ~394) and
  `test_list_doctor_cases_uses_doctor_filter_and_ascending_order` (line ~416): expected rows
  now include the ASSIGNED unclaimed case; still exclude a closed case, a foreign/unassigned
  unclaimed case, and another doctor's claimed case.
- Add `get_case` coverage: assigned doctor reads an unclaimed case; unassigned doctor gets
  `CareNotFoundError`.

`tests/unit/test_care_facade_rx.py`:

- Confirm `test_get_working_prescription_rejects_unclaimed_born_case` and
  `test_get_approved_prescription_rejects_unclaimed_born_case` still reject for the
  NON-assigned doctor (they should; the resolver allowance only applies to the assignee).
  Adjust fixtures only if a born case's intake already carries an assignment in those tests.

Re-run the full unit suite (see §6). Optionally re-check `tests/unit/test_care_routes.py`
(list/get adapters) - no behavioral change expected since routes only forward the doctor id.

### Step 5 - manual browser re-verify

Redo the walkthrough: pick -> finalize -> console "Open cases" lists the case -> the review
workspace shows the handshake -> consult-complete claims and enters prescription-pending ->
request AI draft -> edit -> approve behind the verification declaration -> issued prescription
renders -> patient side shows the record entry.

## 6. Done-verify (all must be green)

```
npm run test:unit:backend
npm run test:unit:frontend
npm run lint
npm run typecheck
npm run migration-check
```

`migration-check` is a no-op gate here (no schema change planned); run it anyway to confirm the
tree stays single-head + FK-clean. `npm run test:integration` optional (needs local Postgres,
skips if absent).

## 7. Commit + tracking

- One commit, e.g. `fix(phase-8.1): make born-assigned care cases discoverable to the assigned doctor`.
- Recommended: file a `gh` issue (bug, label `PHASE-8.1`) describing the walkthrough dead-end
  so the fix links to a tracked id before `/to-spec` creates the spec/ticket.

## 8. Do NOT touch (scope guard)

- Do not change the claim semantics of `mark_consult_complete` or flip
  `allow_unclaimed=False` reads globally.
- Do not alter `GET /v1/care/cases` pagination (pre-existing standards finding, escalated to
  #426 per `t9-review-close-findings-plan.md` §2) or the sync `gateway.draft_rx` AI call.
- Do not change intake pipeline, pick-a-doctor write, prescription machines, drafting cap,
  i18n, or any frontend code.
- Do not touch `docs/archive/`.

## 9. Open items carried from the parent session

- `apps/backend/app/config.py` has an UNCOMMITTED local-only flip
  (`DEFAULT_APP_ENVIRONMENT` -> `"dev"`). Decide before push: revert to keep the production
  default, or set `APP_ENVIRONMENT=dev` in the launch shell instead.
- Untracked `docs/agents/briefs/*` from PHASE-8/8.1 and a stray `var/` - confirm what is
  intentional before push.
