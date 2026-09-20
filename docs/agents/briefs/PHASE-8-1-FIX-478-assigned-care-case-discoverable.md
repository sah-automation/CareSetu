# Brief - 478 PHASE-8.1 fix: make born-assigned care cases discoverable to the assigned doctor

**Ticket:** #478 · **Parent:** #477 · **Refreshed:** 2026-09-19
**Reading surface:** ~10K tokens (budget 10K) - at budget

## Scope

Make a born-but-unclaimed care case (`doctor_id IS NULL`, assignment living on the intake's `assigned_partner_id`) discoverable and readable to the doctor the intake was assigned to, at every care read surface, without changing claim semantics. The claim stays at `mark_consult_complete` (`allow_unclaimed=True`, untouched).

Acceptance criteria (from ticket #478):

- [ ] `IntakeFacade.assigned_partner_for_pre_summaries(pre_summary_ids: Sequence[int]) -> dict[int, int | None]` - one read-only query: `intake_pre_summaries` join `intake_intakes` on `intake_id`, filter `id IN (pre_summary_ids)`, return `{pre_summary_id: assigned_partner_id}` (`None` when not yet picked). Ids only, PHI-free.
- [ ] `list_doctor_cases` returns claimed non-closed cases (`doctor_id == doctor`) PLUS unclaimed non-closed cases (`doctor_id IS NULL`) whose pre_summary resolves via the new seam to this doctor. Merge preserves `created_at` ascending order.
- [ ] `check_case_ownership` extended with an optional async resolver (pre_summary id -> assigned partner id) defaulting to `None` (= today's behavior). When `row.doctor_id IS NULL` and `allow_unclaimed=False`: allow only if the resolver resolves the case's pre_summary to the caller; otherwise keep `CareNotFoundError`. `mark_consult_complete` keeps `allow_unclaimed=True`.
- [ ] Rx reads (`get_working_prescription`, `get_approved_prescription`) resolve through the same resolver via `rx_facade`'s already-injected `intake_facade`; a non-assigned doctor is refused on every path.
- [ ] No schema change, no `create_app` edit, no route change, no frontend change.
- [ ] Tests extend `test_care_facade_consult.py` (list includes assigned unclaimed, get_case opens for assignee, unassigned raises) and confirm `test_care_facade_rx.py` rx-reject tests still reject for the NON-assigned doctor.

## Read-list (in order)

1. Ticket #478 body - the full spec (the contract; decisions and line-level details live here)
2. `docs/plans/phase8-1-case-workspace-unreachable-fix.md` - authoritative step-by-step plan: root-cause chain w/ DB evidence, red-capable repro, design decision (Option A), implement steps 1-5, scope guard (~2K)
3. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" - canonical `care case`, `case stage`, `consult complete milestone`, `finalized pre-summary` (~0.4K)
4. `apps/backend/modules/care/case_facade.py` - `check_case_ownership` (module-level guard imported by `rx_facade` - extend in place with optional async `assigned_doctor_of` resolver, never move it), `CaseConsoleFacade.__init__` (already holds `self._intake_facade`), `get_case`, `list_doctor_cases` (~1.6K)
5. `apps/backend/modules/care/rx_facade.py` - constructor injection of `intake_facade`, the `check_case_ownership` call sites (grep the six call lines), `get_working_prescription` / `get_approved_prescription` (~1.2K slices only - not the full file)
6. `apps/backend/modules/intake/facade.py` - the assigned-partner-scoped read pattern to mirror: review-queue read (`intake_intakes.c.assigned_partner_id == doctor_id` JOIN WHERE) and `get_doctor_pre_summary` (the same seam style + PHI-minimization docstring) (~1.2K slices)
7. `apps/backend/modules/intake/intake_models.py` + `apps/backend/modules/intake/schema/models.py` - `intake_intakes.assigned_partner_id` (nullable BigInteger), `intake_pre_summaries` PK/id shape (~0.4K)
8. `apps/backend/modules/care/care_models.py` - `CaseDetailView` + `_to_case_detail` mapper (~0.3K)
9. `apps/backend/app/main.py` (~304-312) - confirms both care facades already receive `intake_facade` (no `create_app` change) (~0.1K)
10. `tests/unit/test_care_facade_consult.py` - facade-with-fakes helpers (`_FakeResult`, `_connection`, `_engine`, `_intake_facade`, `_care_facade`) + the two list tests + get_case tests to extend (~1.5K slices)
11. `tests/unit/test_care_facade_rx.py` - `test_get_working_prescription_rejects_unclaimed_born_case` / `test_get_approved_prescription_rejects_unclaimed_born_case` (~0.6K slices)
12. `docs/architecture/internal-modules.md` §3.6 (`MOD-006`) - module spec + module isolation rule (facade seam is the legal cross-module sync route) (~0.9K)
13. `docs/standards/security-phii-standards.md` §2 - data-minimization / assigned-scoping posture the new read must mirror (~0.4K)

## Do NOT read

- Frontend entirely - no changes; `listOpenCases`/`fetchCareCase` start working once the reads return the assigned case
- Intake pipeline / intake adapters (`intake/adapters/pipeline.py`, `intake/adapters/routes.py`) - pick write and `pre_summary.ready` flow out of scope
- Care adapters (`care/adapters/routes.py`) and domain state machines (case machine + transition untouched; `mark_consult_complete` handshake path unchanged)
- Consent facade, gateway, audit/notifications modules
- `docs/archive/`, `prototype/`, any migration files (no schema change)

## Baseline verify (must pass before the first edit)

- Target slice (must be green): `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_care_facade_consult.py tests/unit/test_care_facade_rx.py tests/unit/test_care_routes.py -q`
- NOTE: `npm run test:unit:backend` is NOT green on the current tree (verified 2026-09-19). 4 pre-existing failures, all unrelated to this slice:
  - 3 (test_app_shell x2, test_seed_demo) stem from the known uncommitted `DEFAULT_APP_ENVIRONMENT -> "dev"` flip in `apps/backend/app/config.py` (plan §9 open item)
  - 1 (test_contract_check::test_real_api_ts_passes_against_real_openapi: expects 7 auth endpoints, sees 9) from auth-surface drift already on the tree

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (target slice green)
- `npm run typecheck:backend` (only backend touched)
- `npm run lint`
- `npm run migration-check` (no-op gate - confirms single-head + FK-clean)
- Manual browser walkthrough (release gate): pick -> finalize -> console "Open cases" lists the case -> review workspace shows the handshake -> consult-complete claims and enters prescription-pending -> AI draft -> edit -> approve behind the verification declaration -> issued e-prescription renders -> patient side shows the record entry

## Handoff notes

- `check_case_ownership` is imported by `rx_facade` (`from modules.care.case_facade import check_case_ownership`) - extend it with an optional async resolver defaulting to `None`; do not move it into the class and do not flip `allow_unclaimed=False` globally.
- `mark_consult_complete` keeps `allow_unclaimed=True` - the claim path is exactly as designed and must not change.
- The new intake read is ids-only and PHI-free; mirror the existing assigned-partner JOIN WHERE shape. Legal seam: care already receives `IntakeFacade`.
- `list_doctor_cases` merge: two queries (claimed = `doctor_id == doctor`, unclaimed = `doctor_id IS NULL`, both `stage != Closed`), collect the unclaimed rows' `pre_summary_id`s, call the intake seam once, keep only rows resolving to this doctor, merge, order by `created_at` asc. Do NOT add a cross-schema JOIN - the merge happens in the facade (module isolation rule).
- Tests use the facade-with-fakes seam (`_FakeResult`/`_connection`/`_engine`/`_intake_facade`/`_care_facade`) - the intake facade behind `_intake_facade` is a REAL `IntakeFacade` over a mocked engine, so the new seam's SQL is exercised through that mock connection (feed it the prepared result rows).
- Wire one resolver everywhere (get_case, list_doctor_cases, rx reads); a non-assigned doctor is refused on every path.
- Baseline failures above are pre-existing tree state (see plan §9 open items) - do not "fix" them in this ticket.
- Commit: single `fix(phase-8.1): make born-assigned care cases discoverable to the assigned doctor`, referencing `Closes #477`.
