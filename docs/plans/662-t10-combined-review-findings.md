# #662 - combined two-axis review findings (ticket #672)

**Branch:** `main` · **Ticket:** #672 (parent #662) · **Date:** 2026-10-09
**Status:** Review run over the combined #663-#671 diff. One real spec regression fixed (denied cross-patient row disclosed the raw id); two Standards findings fixed; four findings explicitly dispositioned. Unit suites, lint, typecheck, and migration-check green after fixes. Integration/e2e run manually by the operator.

---

## 1. Fixed point and reviewed diff

**Fixed point:** `6c5ab11` (parent of the first #662 delivery commit). The reviewed diff is exactly (`git diff 6c5ab11 fd725aa`):

- `df5d19a` (#663) consent-at-pick mints all three record scopes atomically
- `d624171` (#664) consent sheet discloses all three record scopes in both languages
- `8b626c5` (#665) access history stops recording owner reads
- `2504ba7` (#666) extract rail "At a glance" summary into shared component
- `19c38df` (#667) month dividers gain spacing above every timeline group
- `66e14d4` (#668) access-history API resolves and exposes actor display names
- `ed3cb1c` (#669) extract "Who accessed my record" accordion into shared component
- `74ef431` (#670) access-history rows render shared counterparty labels
- `fd725aa` (#671) patient home rail reaches record-page parity

30 files, +1984 / -510.

## 2. Baseline verify (pre-edit)

| Gate                         | Result                                                                                                                                                              |
| :--------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `npm run test:unit:backend`  | 2925 passed                                                                                                                                                         |
| `npm run test:unit:frontend` | 2154 passed (2 load-induced 5s timeouts when run beside 3 other heavy gates; both pass in isolation)                                                                |
| `npm run lint`               | green                                                                                                                                                               |
| `npm run typecheck`          | green (backend mypy + frontend tsc)                                                                                                                                 |
| `npm run migration-check`    | single head `5a6fc4715675`, no cross-schema FK                                                                                                                      |
| `npm run test:integration`   | 271 passed, 1 pre-existing environment failure `test_consent_check_gate.py::test_p95_latency_under_50ms` (p95 252ms vs 50ms budget) - NOT a regression of this work |

## 3. Two-axis review

### Standards axis

1. **Judgement - silent error swallow.** `apps/frontend/src/lib/record/useOwnRecord.ts` caught the own-record fetch with `catch(() => setState({status:"error"}))`, discarding the error and leaving no log/trace; `coding-standards.md` §8 ("No silent swallowing of errors; a failure must be reproducible from `trace_id` + structured logs"). Siblings do better (`HealthSnapshotCard` `console.warn`s; `AccessHistoryAccordion` captures `traceId`). → **FIXED**.
2. **Judgement - traceability header.** `AtAGlanceCard.tsx` had no `MOD-xxxx`/`FEAT-xxx` header; `useOwnRecord.ts` cited only a ticket number; `coding-standards.md` §8 "Traceability by construction". → **FIXED**.
3. **Judgement - duplicated resolver alias.** `CounterpartyDisplayNameResolver = Callable[[str, str], Awaitable[str | None]]` is declared in both `modules/consent/facade.py` and `modules/health/facade.py`. → **DISPOSITIONED (no change)**: the health module is deliberately name-agnostic and imports no consent code (module-isolation rule, `coding-standards.md` §5); the alias is a structural type at the composition-root seam, and importing consent's alias into health would breach that boundary. The duplication is the isolation-preserving choice, not drift.
4. **Judgement - duplicated external-store boilerplate.** The `subscribe`/`getSnapshot`/`setState`/`queueMicrotask`-drop pattern is copied between `AccessHistoryAccordion.tsx` (`AccessHistoryStore`) and `useOwnRecord.ts` (`OwnRecordStore`). → **DISPOSITIONED (no change)**: baseline smell (judgement call, not a documented standard). The two stores differ materially (per-patient `Map` vs singleton; different state shape and derived view; different drop condition). Extracting a generic base was not in spec scope, and the 2-use duplication is a well-understood pattern; a refactor would add indirection for no behavioural gain.

No hard documented-standard breaches remained after fixes. Module isolation, PHI-in-logs, REST/error envelope, and migration discipline were checked and compliant (`_display_name` warns on `actor_type` only; the new resolver binding is a composition-root seam).

### Spec axis (against #662)

1. **REAL BUG - denied cross-patient row disclosed the intruder's raw identity id.** After #670 routed access-history rows through the shared `counterpartyLabel` three-step fallback, a denied cross-patient row (`actor_type="patient"`, `actor_display_name=null`) found no type word at step two, so it fell to step three and rendered the raw `actor_id` (e.g. `"9"`). Spec Solution 2 / US-22 require the refused identity never be disclosed. The pre-#670 surface showed the generic role word. → **FIXED**.
2. **Not a bug - NULL `actor_type` read filter.** The read predicate is `NOT (actor_type = 'patient' AND accessor = owner)`. A sub-agent flagged this as over-excluding legacy (pre-v3.1) rows whose `actor_type` is `NULL`. It does not: for a legacy counterparty row `accessor <> owner` so `NULL AND FALSE = FALSE` and `NOT FALSE = TRUE` (kept); for a legacy owner row `accessor = owner` so `NULL AND TRUE = NULL` and `NOT NULL = NULL` (hidden, as intended). Rewriting to `IS DISTINCT FROM` would leak legacy self rows. → **DISPOSITIONED (no change)**; behaviour pinned by a new integration test.
3. **Harmless - purge migration leaves legacy NULL-actor self rows.** The v8.18 `DELETE` keys on `actor_type = 'patient'`, so a pre-v3.1 owner row (`actor_type IS NULL`) is not deleted - but the read filter hides it (finding 2), exactly as the migration docstring's belt-and-suspenders claim intends. Purging on accessor alone would risk deleting a legacy counterparty row whose partner id collides with the owner's patient id. → **DISPOSITIONED (no change)**.

No scope creep found: no consent-granting/widening UI, no `full_record` grant, no `lab_results`/`metrics` activation, no revocation/state-machine/egress/ADR-0004 change, no browse/find pick extension, no e2e widening (out-of-scope list verified item by item against the diff).

## 4. Fixes (follow-up, not amends)

### Fix 1 - patient role word in the shared counterparty fallback (#672, spec US-22)

- `apps/frontend/src/lib/consent/consentView.ts`: added `patient` to `TYPE_LABEL_KEYS`, so a patient-type actor lands on the role word at step two instead of the raw id at step three.
- `apps/frontend/src/lib/i18n/dictionaries.ts`: added `patient` to `consentLog.counterparty` in both English ("Patient") and Hindi ("मरीज़").
- `apps/frontend/src/lib/consent/consentView.test.ts`: new test asserting `counterpartyLabel("patient", "9")` is the role word and never `"9"`, in both languages.
- `apps/frontend/src/app/(patient)/patient/record/page.test.tsx`: strengthened the cross-patient denied test to assert the label `<strong>` is exactly the patient role word (no resolved name, no raw id).

### Fix 2 - own-record fetch logs instead of swallowing (#672, coding-standards §8)

- `apps/frontend/src/lib/record/useOwnRecord.ts`: `catch` now `console.warn`s the failure before setting the error state, matching `HealthSnapshotCard`'s posture.

### Fix 3 - traceability headers (#672, coding-standards §8)

- `apps/frontend/src/lib/record/useOwnRecord.ts` and `apps/frontend/src/components/patient/AtAGlanceCard.tsx`: added `MOD-003`/`FEAT-003` (and `FEAT-006`) header ids.

### Test - pins the NULL `actor_type` disposition

- `tests/integration/test_patient_access_history_api.py`: new test `test_legacy_null_actor_type_keeps_counterparty_rows_and_hides_self_rows` (and `_insert_history_row` widened to `str | None`).

## 5. Done-verify

| Gate                         | Result                                                              |
| :--------------------------- | :------------------------------------------------------------------ |
| `npm run test:unit:backend`  | 2925 passed                                                         |
| `npm run test:unit:frontend` | 134 files / 2157 passed                                             |
| `npm run lint`               | green (all hooks)                                                   |
| `npm run typecheck`          | green (backend mypy + frontend tsc)                                 |
| `npm run migration-check`    | single head `5a6fc4715675`, no cross-schema FK                      |
| `npm run test:integration`   | operator-run (baseline: 271 passed, 1 pre-existing latency failure) |
| `npm run test:e2e`           | operator-run                                                        |

`docs/plans/662-t10-combined-review-findings.md` is the report satisfying the "all findings fixed or explicitly dispositioned" acceptance criterion.
