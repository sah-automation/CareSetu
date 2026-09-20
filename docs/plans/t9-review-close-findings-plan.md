# T9 (#437) - PHASE-8 review-close: combined two-axis review findings + implementation plan

**Branch:** `feat/phase-8-care-eprescription` · **Ticket:** #437 (parent #426) · **Date:** 2026-09-15
**Status:** Plan written in a full session; implementation reserved for a fresh session (context budget exhausted).

---

## 1. Baseline verify (DONE, green)

Run on the pre-review tree (all ten tickets merged, HEAD `8adbeec`):

| Gate                        | Result                                              |
| --------------------------- | --------------------------------------------------- |
| `npm run test:unit:backend` | 2110 passed                                         |
| `npm run lint`              | All pre-commit hooks passed                         |
| `npm run typecheck`         | backend mypy clean (225 files) + frontend tsc clean |
| `npm run migration-check`   | single head `ee3394de5a38` OK, no cross-schema FK   |
| `npm run scan`              | gitleaks/bandit/pip-audit clean (no known vulns)    |

**Fixed point for the review:** `b8c8dea` (the #426 anchor). Combined diff = `git diff b8c8dea...HEAD`
(66 files, +11484/-177, 22 commits). The review-close slice = `1d46cfe..HEAD` (11 commits, T1-T8b #427-#436).

## 2. Two-axis review (DONE, both sub-agents reported)

### Standards axis (4 hard + 2 judgement-call findings)

1. **Hard - sync LLM call in user-critical path.**
   `POST /v1/care/cases/{id}/rx/draft` with `source="ai_draft"` calls
   `gateway.draft_rx()` synchronously in the request:
   `care/adapters/routes.py:317` → `care/rx_facade.py._create_ai_draft` →
   `intake/facade.py:894` (`gateway.draft_rx`, ≤30 s EXT-002 call). The care
   facade holds its DB transaction open across the external call. Violates
   `third-party-integration-standards §1` and `ai-engineering-standards A1`.
   **PRE-EXISTING** (predates review-close: `request_rx_draft` is T05 #421
   intake work; the list route is T06 #422). Not in #426 declared scope.
   → ESCALATE to #426, do not fix in T9 (brief: "no new seams", scope guard).
2. **Hard - list endpoint has no pagination.**
   `GET /v1/care/cases` (`care/adapters/routes.py:224`) returns a bare
   `list[CaseDetailView]`; api-standards §4 requires `{items, next_cursor, total}`.
   **PRE-EXISTING** (route born in T06 #422). Not in #426 scope.
   → ESCALATE to #426, do not fix in T9.
3. **Judgement - duplicated block in `rx_facade`.** The load-prescription +
   `check_case_ownership` + belongs-to-case + build-PrescriptionState shape is
   repeated in ~5 methods (`create_rx_draft`, `save_rx_revision`,
   `approve_prescription`, `reject_prescription`, `get_approved_prescription`).
   The ownership guard itself IS shared (`check_case_ownership`), so per #426
   decision 15 the security check is centralized. This is a Fowler Duplicated
   Code smell only. → Accept as judgement call; refactoring at the final
   review-gate adds risk with no contract benefit. NOTE ONLY.
4. **Judgement - `_check_approval_declaration` (rx_facade:810) speculative.** It is
   the documented CFL-002 replaceable seam (ADR-0014) - spec-pinned, NOT
   speculative. → SKIP (overridden by documented standard).
5. **Judgement - `MAX_REJECTED_DRAFTS = 2` (prescription_machine.py:94) without an
   ADR number.** The drafting cap is pinned in the CONTEXT.md glossary and #426
   decision ("two AI drafts per case"). → SKIP (judgement call).
6. **Judgement - v8.2 migration alters `verification_declaration` TEXT→BOOLEAN.**
   coding-standards says migrations additive; no data exists at migration time,
   so safe in practice. → SKIP (borderline, accepted).

### Spec axis (1 substantive + 1 wording artifact + 1 seam + 1 observation)

- **F1 (SUBSTANTIVE - fix) - case-birth dedupe is code-side only, racy under
  concurrency.** US2 of #426 promises "at-least-once outbox delivery never
  creates duplicate care cases". The `pre_summary.ready` consumer
  (`care/adapters/__init__.py:199-219`) does SELECT-then-INSERT with **no unique
  constraint on `care_cases.pre_summary_id`**. Intake emits `pre_summary.ready`
  for the SAME pre_summary at BOTH Draft creation (`intake/adapters/pipeline.py:789`)
  and Final review (`intake/facade.py:817`) - two DISTINCT event_ids. Under
  concurrent delivery (multi-worker), both passes of the guard can SELECT
  "no row" then both INSERT → two care cases for one pre_summary. Same-event
  replays are safe (ledger dedupe by event_id), but the distinct-event case is
  not DB-enforced. The docstring even claims "exactly one care case per
  finalized pre-summary".
  **Fix = unique index on `care_cases.pre_summary_id` + INSERT ON CONFLICT
  DO NOTHING** (pattern already used by `bus/ledger.py:48`). Directly serves
  US2; stays inside #426 declared scope (T1 was schema-hardening; this is the
  same hardening axis). NO new seam, machine unchanged, cap unchanged.
- **F2 (wording artifact - no code change) - close-reason 400 vs 422.** #426
  testing decision says "close-reason 400"; the route returns FastAPI `422`
  (`test_care_routes.py:425` asserts 422). api-standards §3 mandates `422` for
  validation errors - the platform convention (brief #429 wording: "missing
  reason is a 400/validation failure" = loose). → Keep 422; NOTE ONLY.
- **F3 (seam consequence - consistent, no fix) - PreSummary-stage doctor input
  unreachable.** Born case has `doctor_id` NULL; `check_case_ownership`
  (allow_unclaimed=False) blocks `submit_doctor_input` and `list_doctor_cases`
  filters on doctor_id, so pre-handshake input ("PreSummary or
  PrescriptionPending" per machine/docstring) is dead in the product flow. This
  is the intended #426 T4 posture ("a born case is claimable by the first doctor
  who completes mark_consult_complete; the guard blocks it for every other
  operation") - the handshake claims the case, then input works. Text in
  `case_facade.py:341-343` is slightly over-broad. → Optional cosmetic docstring
  nudge; not a functional bug. NOTE ONLY.
- **F4 (observation) - forced-review history is boolean-only, no timestamp.**
  ADR-0015 explicitly says record-and-surface, so this matches the decision.
  → NOTE ONLY.

## 3. Verdict

Only ONE finding is fixed in T9: **F1 (unique index + ON CONFLICT on
`care_cases.pre_summary_id`)**. It is the sole genuine contract gap that (a)
is inside #426's declared scope and (b) is cheap + low-risk to close.

The two hard standards findings (sync LLM, pagination) are pre-existing, outside
#426's scope, and the brief's scope guard says escalate rather than silently
expand → record in the review report, escalate to #426.

## 4. Implementation plan (fresh session)

### Step 1 - migration v8.3

New revision **down_revision = `ee3394de5a38`** (v8.2 head):

```
apps/backend/alembic/versions/<newrev>_v8_3__care_cases_unique_pre_summary.py
```

Docstring: T9 #437 (parent #426), US2 unconditional dedupe.

```python
def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_care_cases_pre_summary_id "
        "ON care.care_cases (pre_summary_id)"
    )

def downgrade() -> None:
    op.execute("DROP INDEX care.uq_care_cases_pre_summary_id")
```

`op.create_index(..., unique=True)` with explicit name also works; keep raw SQL
for consistency with v8.2 file style. Generate the new rev id with
`alembic revision` (`node scripts/py.cjs -m alembic ...`) or hand-roll a hex id.

### Step 2 - schema model parity

`apps/backend/modules/care/schema/models.py` - `care_cases` (line 100):

```python
Index(
    "uq_care_cases_pre_summary_id",
    "pre_summary_id",
    unique=True,
),
```

Add to the `Table(...)` index list (next to `ix_care_cases_patient` line 128).

### Step 3 - case-birth handler conflict tolerance

`apps/backend/modules/care/adapters/__init__.py:212-219`:

Replace plain `care_cases.insert()` with a PostgreSQL `insert()
.on_conflict_do_nothing(index_elements=["pre_summary_id"])` returning rowcount,
mirroring `bus/ledger.py:39-48`. On `rowcount == 0` log the existing
"case already born" line and `return` (do NOT delete the SELECT guard - it stays
as the fast path and keeps the current log+skip tests green). Import
`from sqlalchemy.dialects.postgresql import insert` at the top of the adapters
module (check existing imports first - ledger.py already uses this idiom).

```python
result = await connection.execute(
    insert(care_cases)
    .values(
        patient_id=payload.patient_id,
        pre_summary_id=payload.pre_summary_id,
        stage=STAGE_PRE_SUMMARY,
        forced_review=False,
    )
    .on_conflict_do_nothing(index_elements=["pre_summary_id"])
)
if result.rowcount == 0:
    logger.info(... "case already born (concurrent); skipping")
    return
```

Update the `_on_pre_summary_ready` docstring: note the DB-level unique index
plus the SELECT fast path means US2 holds even for two distinct concurrent
`pre_summary.ready` event_ids naming one pre_summary.

### Step 4 - tests

- `tests/unit/test_care_events.py` - `test_pre_summary_ready_same_pre_summary_two_event_ids_births_one_case`
  (line 434) already covers the serial distinct-event path; it must stay green
  (SELECT guard unchanged). If the fake connection's `execute` mock needs a
  `rowcount` attr for the conflict-insert path, extend `_FakeResult`/
  `_Recorded` in that file accordingly (check how `run_handler` mock wiring in
  the file handles `insert_case`/`rowcount` today - add both-path coverage:
  first insert returns rowcount 1, concurrent conflict path rowcount 0 + log).
- `tests/unit/test_module_layout.py` - if migration/table assertions live there,
  add the unique index expectation (check whether it already asserts care table
  indexes; mirror existing style).
- `npm run migration-check` validates single head + FK scan on the new revision.

### Step 5 - done-verify (all must be green)

```
npm run test:unit:backend
npm run lint
npm run typecheck
npm run migration-check
npm run scan
```

### Step 6 - commit + report

- One commit for the fix (migration + model + handler + tests). Suggested
  message: `fix(phase-8): DB-backed exactly-one case birth on pre_summary.ready (T9, #437)`.
- Optionally reopen-record: escalate the two standards findings
  (sync `gateway.draft_rx` in user path at `intake/facade.py:894`;
  un-paginated `GET /v1/care/cases` at `care/adapters/routes.py:224`) back to
  #426 as follow-ups.

## 5. Cross-ticket seams re-checked during review (all consistent)

| Seam                                                     | Result                                                                                             |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| T2-born `doctor_id`-unset case claimable in T4 handshake | Consistent (`mark_consult_complete` allow_unclaimed=True, claims + transitions; see F3)            |
| T1 boolean declaration consumed by T5 route + machine    | Consistent (typed Literal + `_check_approval_declaration`)                                         |
| T3 close route wrapped by T5 idempotency                 | Consistent (close appears in the seven gated mutations; replay tests at test_care_routes.py:1108+) |
| T6a/T6b split behaviour-identical under T4 guard         | Consistent (wrapper deleted ffc50e9; shared `check_case_ownership` imported by rx_facade)          |
| T8a FEAT-tagging gate not regressed                      | Untouched in this plan (only migration/model/adapters-**init**/events test touched)                |

## 6. Do NOT touch

- `intake/facade.py:894` sync AI call (escalate, out of scope)
- `care/adapters/routes.py:224` pagination (escalate, out of scope)
- Prescription/case machines, drafting cap, forced-review posture, UI/frontend,
  docs/archive, intake/pipeline semantics.
