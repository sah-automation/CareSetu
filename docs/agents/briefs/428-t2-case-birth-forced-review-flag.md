# Brief - T2 PHASE-8 review-close: case birth on pre_summary.ready + forced-review record-and-surface flag

**Ticket:** #428 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~9.6K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T2. A care case now actually comes into existence the moment a pre-summary is finalized, so the consult handshake and prescription flow have real data to operate on instead of test fixtures. The `pre_summary.ready` inbound consumer performs the case-birth write (patient, pre_summary, PreSummary stage, forced_review false) in the same transaction as the consumed-event mark, with the module's subscriber-side dedupe so at-least-once replays never create duplicate cases. A `pre_summary.low_confidence` delivery sets `forced_review` true on the matching care case, idempotently and deduped; the flag is record-and-surface only (no handshake gate change). The flag is exposed on the case views. The producer payload for `pre_summary.ready` is enriched to carry the patient identity (intake producer plus care's tolerant consumer mirror), and the care module's process-local delivery counters move into a small dedicated telemetry helper.

Acceptance criteria (verbatim from ticket):

- [ ] `pre_summary.ready` finalize produces exactly one care case (patient, pre_summary_id, PreSummary stage, forced_review false); none existed before
- [ ] Replay of the same event_id is a no-op - no duplicate care case
- [ ] `pre_summary.low_confidence` sets `forced_review` true on the matching case; replay is idempotent and does not error, and the delay case (low_confidence before the birth event) does not crash
- [ ] `forced_review` is visible on get_case, list_doctor_cases, and the case detail in route responses
- [ ] `pre_summary.ready` producer payload carries the patient identity; care's tolerant consumer mirror is updated; intake producer tests reflect the new field
- [ ] The telemetry counters keep working from the new dedicated helper module (no behaviour change)
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green (facade and routes untouched by this ticket)

**Blocked by:** #427 (T1) - schema must provide `forced_review` and non-null `pre_summary_id` first.

## Read-list (in order)

1. `care/adapters/__init__.py` - the inbound-consumer seam this ticket rewrites: `register_handlers`, the consumer-side payload mirrors (`CarePreSummaryReadyPayload`, `CarePreSummaryLowConfidencePayload`), the `_make_telemetry_handler` factory and its `_COUNTERS`/`pre_summary_*_count()` accessors. Case-birth handler + telemetry-helper extraction both land here. (~2.1K)
2. `bus/handler_harness.py` + `bus/ledger.py` - `run_handler` signature and the `record_consumed_event` dedupe (False on replay = skip), the subscriber-side contract the birth write must join in one transaction. (~1.3K)
3. `intake/domain/events.py`: `PreSummaryReadyPayload` / `PreSummaryLowConfidencePayload` (~L88-109) and the `pre_summary_ready_envelope` builder (~L199-220) - the producer payload that must gain the patient identity field. (~0.9K)
4. Intake `pre_summary.ready` emission sites - where `patient_id` is available at emission time: `intake/facade.py` `mark_pre_summary_reviewed` finalize block (~L780-830) and `intake/adapters/pipeline.py` `_finalize_pipeline` (~L750-810). Publish the enriched payload at both sites. (~1.6K)
5. Care case shape + views: `care/schema/models.py` `care_cases` table (patient_id, pre_summary_id NOT NULL, forced_review) and `CaseDetailView` in `care/care_models.py` (surface `forced_review`). The birth insert and the view both need T1's columns. (~1.0K)
6. Prior-art tests (faked connection, dedupe, replay-skip): `tests/unit/test_intake_pipeline_consumer.py` `_FakeConnection` + replay no-op tests, `test_intake_pipeline_degradation.py` low-confidence event test, `test_intake_review_facade.py` finalize-publishes-ready test, and `test_care_events.py` telemetry/counter/dedupe tests - the harnesses your new birth/handler tests mirror. (~2.2K)
7. `worker/main.py` register-handlers composition root (~L49-112) - confirm the care register path stays unchanged while adding the telemetry helper. (~0.5K)

## Do NOT read

- Dispatcher/bus polling internals (`bus/dispatcher.py` or the worker loop body), intake pipeline internals beyond the finalize emission block, partner/iam internals, the frontend, `docs/archive/`.
- `care/adapters/routes.py` and `care/facade.py` - explicitly untouched by this ticket; the facade/machine handshake stays as-is.

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new birth/forced-review/replay/telemetry tests + enriched intake producer tests
- `npm run lint`
- `npm run typecheck`
- `npm run migration-check` - confirms T1's head is intact (should still pass)

## Handoff notes

- Today `pre_summary.ready` and `pre_summary.low_confidence` are **ledgered telemetry seams only** in `care/adapters/__init__.py` - no care-case row is ever written; `get_finalized_pre_summary` and the handshake operate on fixtures. Case birth is the core new behaviour.
- The producer payload is the blocking gap documented in `internal-modules.md` §3.6: it carries only `intake_id` + `pre_summary_id`, but `care_cases.patient_id` is NOT NULL. Enrich `PreSummaryReadyPayload` with the patient identity (find where `patient_id` is in scope at both emission sites), and keep care's consumer mirror **tolerant** of the old shape while the events are in flight.
- The case-birth insert and the `record_consumed_event` mark must share one transaction (subscriber ledger discipline) so at-least-once replay can never double-insert; dedupe (event_id already consumed) makes replay a no-op.
- `pre_summary.low_confidence` may arrive before `pre_summary.ready` (intake emits both, in that order, same transaction - but delivery order across outboxes is not guaranteed); the forced-review handler must not crash on a missing case.
- The telemetry counters (`pre_summary_ready_count()`, `pre_summary_low_confidence_count()`, `report_filed_count()`) are asserted in `test_care_events.py`; moving them to a dedicated helper must not change their behaviour or the test expectations.
- The consultations/drafting facade is NOT in scope - the forced-review flag is record-and-surface only (ADR-0015 posture); the handshake's single gate is untouched (that changes in T4 via `mark_consult_complete`).
- Review the closing comments of #427 (T1) if landed before you start - the `forced_review` column name/default and `pre_summary_id` NOT NULL must match your insert exactly.
