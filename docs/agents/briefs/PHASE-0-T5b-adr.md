# Brief - PHASE-0 T5b ADR-0001 + glossary capture

**Ticket:** #13 · **Parent:** #2 · **Refreshed:** 2026-08-10
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

The Phase 0 decision record: write ADR-0001 capturing the AMB-006 resolution - transcription vs structuring confidence split, threshold 0.70, the `low_confidence` flag on the 3-state pre-summary lifecycle, the forced-doctor-review usage gate - and flag the new domain vocabulary for the repo glossary.

Acceptance criteria:

- [ ] ADR-0001 written in `docs/adr/` recording the AMB-006 resolution
- [ ] New glossary terms flagged/captured per `docs/agents/domain.md`
- [ ] ADR consistent with the spike's measured numbers (no invented constants)

## Read-list (in order)

1. The spike report from #12 (T5a) - the numbers and verdict the ADR records.
2. `docs/agents/domain.md` - the ADR + glossary conventions for this repo.
3. `docs/adr/` - existing ADRs, if any, to match format and numbering.
4. `docs/roadmap/implementation-roadmap.md` PHASE-0 section - the AMB-006 decisions already pinned there.

## Do NOT read

- `phase0/corpus/audio/` (binary WAVs)
- `docs/archive/`
- Harness internals (the ADR records decisions, not code)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria → commands)

- `docs/adr/0001-*.md` present, matching the repo's ADR format
- Numbers in the ADR match the spike report from #12 exactly
- Glossary terms flagged per `docs/agents/domain.md`

## Handoff notes

- The spec pins these already; the ADR records them as decided: confidence split (transcription vs structuring), threshold 0.70, `low_confidence` = quality gate not a 4th lifecycle state, forced-review = hard usage gate on `rx_draft`/`consult`, cleared only by timestamped attributed doctor review.
- Vocabulary to flag: pre-summary, transcription confidence, structuring confidence, low_confidence flag, forced doctor review, dialect cohort, well-formed subset, silent-error bound.
- This is a doc-only change - the tree must stay green (baseline + done-verify prove it).
