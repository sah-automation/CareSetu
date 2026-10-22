# Brief - 16 Combined review across the whole correction

**Ticket:** #661 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** deliberately exceeds the 10K budget

## Sizing note - read this first

Every other ticket in this correction fits the ~10K budget. This one does not, and it cannot: its work **is** reading all of the implementation diffs side by side, plus every brief's declared boundaries, plus the spec itself. Trimming the read-list to fit the budget would delete the ticket's only content. So this ticket runs as an explicit, recorded exception: budget not applicable, because the budget exists to prevent unbounded context and this task is unbounded context by definition.

What replaces the budget is the **fan-out**: run the two axes as separate reviews (Standards and Spec), each taking the diff range plus one standards area or one spec section, and take back summaries - not diffs. Fix findings in small, separately verified batches. Do not try to hold all fifteen diffs in one pass.

## Scope

A combined review of the whole correction on both axes the repo cares about:

- **Standards** - does the code follow the repo's documented standards for each area it touched?
- **Spec** - does it match what #645 actually asked for, _including everything the spec declared out of scope_?

This runs **after** every implementation ticket has landed, not instead of them. Each ticket stands on its own; this pass catches only the cross-cutting drift that appears when the slices sit side by side: a helper duplicated where it should be shared, a bilingual string that missed one language, a preserved test id quietly dropped, a surface that drifted past a stated boundary.

## Acceptance criteria

- [ ] Both axes run over every implementation diff: repo standards, and #645 spec conformance.
- [ ] Every finding is either fixed here or explicitly recorded as a deliberate, justified decision.
- [ ] The bilingual gate passes: every new string exists in English and Hindi.
- [ ] The preserved-test-id list from #645 is verified intact across all six corrected surfaces.
- [ ] No out-of-scope item slipped in.
- [ ] The architectural position holds: the console facade owns no schema, the projection is derived at read time, no migration was introduced.
- [ ] The full gate set passes at the end.

## The out-of-scope list - check every item, explicitly

Each of these is a plausible "helpful" addition. Each is out. Confirm each one is still out, and say so in your report:

1. Sorting, filtering, or pagination on the doctor cases list.
2. Lab or chemist counterparty name resolution (those partner phases have not landed; null is correct).
3. Prescription data repair, backfill, or any migration.
4. Widening the consented-history read's `consultations` scope.
5. Photos on doctor list cards.
6. The doctor profile photo reference on the wire, or the consent-gated photo route.
7. The doctor console landing page, or the doctor profile surface beyond #659.
8. The care-scoped cases read and its patient-facing consumers.
9. Any change to grant, revocation, or egress semantics.
10. The doctor patients list's server-side pagination (its bounded fetch + client-side filter stays).
11. The four other inline copies of the stage-chip tone map (only the two lists adopt it).
12. Any change to the frontend request budget.

## Read-list (fan out - one reviewer per area, summaries back)

1. The whole of #645 - the spec being reviewed against, especially its Out of Scope section. Read it whole; a partial read of the thing you are auditing against is the failure mode. (~2K)
2. The full implementation diff range for this correction, split per reviewer. Each reviewer takes one ticket's diff plus the shared helpers it touched.
3. `docs/standards/README.md` and the standards for each area touched: `coding-standards.md`, `api-standards.md`, `error-handling-observability.md`, `security-phii-standards.md`, `coding-standards.md`'s isolation rules, and `ai-engineering-standards.md` only if any AI-draft path was touched. (~1K per reviewer)
4. The fifteen briefs in `docs/agents/briefs/` - each one's declared boundaries and handoff notes, to check the implementation against what it promised. (~500 tokens each)
5. The dictionary file, both locales, for the bilingual sweep. (~2K)
6. `docs/design/ui-blueprint.md`'s doctor and patient surface sections, for the consistency check across the six corrected surfaces. (~1.5K)

## Do NOT read

- `docs/archive/`.
- Code outside the corrected surfaces, except where a shared helper or primitive is involved - that is exactly where duplication hides.
- Unrelated modules and any diff not in this correction's range.

## Baseline verify (must pass before the review starts)

- `npm run test:unit:backend`
- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree. Record it as the known baseline so it is not mistaken for a review finding.
- `npm run test:integration`
- `npm run test:e2e`
- `npm run typecheck`
- `npm run lint`
- `npm run migration-check`
- `npm run scan`

Run the baseline **before** any review edit, so any subsequent failure is attributable to your own change.

## Done-verify (acceptance criteria → commands)

The full gate set, re-run after any fix: unit backend, unit frontend, integration, e2e, typecheck, lint, migration-check, scan. Plus `npm run check:pages` if any frontend page grew.

## Handoff notes

- **Report per finding, not per file.** "Five findings: three duplicated badge maps, one untranslated chip, one dropped test id" is actionable. A file-by-file tour is not.
- **"Out of scope, verified still out" is a required part of the report**, item by item, for all twelve. A reviewer who checks only what was built will miss the thing that should not have been.
- **Duplication is the highest-value finding here.** The whole correction traded on shared seams: one card grid, one stage-tone map, one describe/format view-model, one label chain, one resolver seam. Four inline copies of the stage tone survived by design (#651's scope decision) - so "duplicated tone map" is _not_ automatically a finding; check it against #651's declared boundary before flagging it.
- **Watch for helper extraction that over-reached.** Extracting a helper shared across six surfaces is good. Extracting one that imports between modules is a standards violation, and it is easy to introduce while de-duplicating.
- **Every finding gets fixed or explicitly justified** - not "acknowledged". A finding left open with no rationale is a failure of this ticket.
- **Do not batch all fixes into one commit.** Each fix re-runs the relevant gate. A review that fixes fifteen things and runs the suite once is a review that cannot tell which fix broke what.
- **The known frontend failure is not yours.** Note it, exclude it, and do not let it become an excuse to skip the bilingual or test-id sweep.
