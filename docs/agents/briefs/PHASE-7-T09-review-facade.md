# Brief - T09 Patient edits + doctor review facade

**Ticket:** #353 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Pre-summaries become trustworthy and attributable: save_patient_pre_summary_edits records patient-spotted mistakes as informational corrections available to the doctor; mark_pre_summary_reviewed performs the doctor review-and-edit, edits win over the AI extraction, records which fields changed plus attribution and timestamp, and for a low_confidence pre-summary is the hard gate into Reviewed - an unreviewed or low-confidence pre-summary is structurally unusable as final input.

Acceptance criteria:

- [ ] Patient edits are saved and returned through get_pre_summary as informational corrections
- [ ] mark_pre_summary_reviewed transitions Draft -> Reviewed with attribution, timestamp, and a changed-fields record
- [ ] Edits win over extracted values in the resulting reviewed copy
- [ ] A low_confidence pre-summary cannot reach Reviewed without the attributed review (hard gate), and never reaches Final unreviewed
- [ ] A high-confidence pre-summary can be finalized with a single attributed review action

## Read-list (in order)

1. Issue #344 review/edits decisions + pre-summary machine - the review gate and edit-wins semantics (~2K)
2. `apps/backend/modules/partner/operator_gate_facade.py` - attributed-decision pattern (attribution + timestamp) (~1.5K)
3. `apps/backend/modules/partner/domain/state_machine.py` + pre-summary machine (T02) - Draft -> Reviewed -> Final transitions, low_confidence derivation (~1K)
4. `apps/backend/modules/intake/schema/models.py` (T01) - pre_summaries columns (patient edits, doctor corrections, review attribution) (~1K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- pipeline/worker internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Doctor edits win over AI-extracted values in the reviewed copy; the confirming change-list + attribution + timestamp must be persisted.
- low_confidence (structuring_confidence < 0.70 or missing) is the structural hard gate into Reviewed - no attributed review action, no Reviewed, and never Final unreviewed.
