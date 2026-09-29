# Brief - #518 Docs closeout: ADR-0017, event-registry note, PROTO-3.1 finalize

**Ticket:** #518 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The implementation's decisions are recorded in a new ADR (next number after 0016, i.e. 0017) covering D1-D6 from the spec, the async event registry gains a payload note on the `prescription.issued` row (same pattern as the existing `intake.captured` note, with `items` + `attributed_doctor_name` and the Phase 10 reserved `chemist_name`), and PROTO-3.1 is finalized in `prototype/PLAN.md` with its open review questions resolved against the live implementation.

Acceptance criteria (from the ticket):

- [ ] ADR-0017 exists recording D1-D6 (data path, tags, card anatomy, frontend seam, detail block, docs) referencing the event contract.
- [ ] Async event registry gains the `prescription.issued` payload-note blockquote documenting `items`/`attributed_doctor_name` and the reserved `chemist_name` render-if-present key.
- [ ] PROTO-3.1 marked finalized in `prototype/PLAN.md` with its three open review questions resolved.
- [ ] No code, schema, or migration changes in this ticket; `migration-check` regresses clean.

## Read-list (in order)

1. An existing ADR for tone/format (e.g. 0014 issued-prescription-approval-contract, 0016 partner-login) - decide the wording, reference the record-contract style (~1K).
2. The async event registry - the `prescription.issued` row and the `intake.captured` payload-note blockquote pattern (and sibling notes) to imitate; add the new note alongside them (~1K).
3. `prototype/PLAN.md` PROTO-3.1 entry - status, the three open review questions, and the phase-3 screen table; update status to `finalized` and record the resolutions (~0.5K).
4. Parent spec #512 D1-D6 + the "Record entry payload contract" + "Tags (D2)" sections - the decisions to record, verbatim where helpful (~0.5K).

## Do NOT read

- `docs/archive/` (superseded), backend/frontend code internals (the contract is in the spec + the implementation tickets' briefs #513-#517).

## Baseline verify (must pass before the first edit)

- `npm run migration-check` - verified green 2026-09-23 (single head, no cross-schema FKs).
- `npm run lint` - verified all pre-commit hooks green.

## Done-verify (acceptance criteria → commands)

- `npm run migration-check` (must stay green - this ticket changes no schema).
- `npm run lint`.
- Manual: the registry note is present, ADR-0017 exists, `prototype/PLAN.md` shows PROTO-3.1 `finalized`.

## Handoff notes

- ADR numbering: the next number is 0017 (files 0001-0016 exist; note the historical duplicate 0004 - do not renumber, just skip to 0017).
- The `prescription.issued` registry note belongs with the other payload-note blockquotes directly under the event table; document `items` (array of `{name, dose, frequency, duration}`, nullable except `name`), `attributed_doctor_name` (`str | None`), and note `chemist_name` is reserved for Phase 10 `order.delivered` (MOD-008), render-if-present.
- PROTO-3.1's three open review questions are to be resolved **against the live implementation** (that is what the spec's D6 calls for): two-zone desktop vs single column, the snapshot tile set/counts (must be payload-derived), and lab flag phrasing / settlement label. Record the resolutions the shipped implementation embodies; where the code is decisive, cite it; do not leave the questions unaddressed in the finalize.
- This ticket must contain zero code, schema, or migration edits - the ADR and registry note are prose; `prototype/PLAN.md` is a gitignored disposable artifact (never committed) yet still updated per AGENTS.md prototype rules.
