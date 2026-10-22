# Brief - #757 Combined review of Batch 3 with fixes applied

**Ticket:** #757 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Review the whole Batch 3 change set together on both axes the repository cares about - Standards (does it follow the documented coding, API, isolation, security and AI standards) and Spec (does it do what the spec asked) - then fix what the review finds.

- [ ] The code-review skill runs against the whole Batch 3 change set, on both the Standards and Spec axes, with the parent spec as the reference.
- [ ] Every finding is fixed, and any fix that changes a ticket's acceptance criteria is re-verified against that ticket's own done-verify commands.
- [ ] Module isolation holds: no module reads another module's tables, including for the joins that would have made attribution easier.
- [ ] No PHI lands in the observability schema; aggregate keys stay pseudonymous.
- [ ] The full harness is green at the end: lint, typecheck, backend and frontend unit suites, the integration suite against a real PostgreSQL, the migration single-head gate and the cross-schema foreign key scan.

## Read-list (in order)

1. The code-review skill - how it picks the fixed point, how it runs the Standards and Spec axes in parallel, and what its report shape is. (~0.8K)
2. `docs/agents/issue-tracker.md` and the triage-label conventions, since findings may become new tickets rather than edits. (~0.5K)
3. The standards documents for the six areas the review runs against: coding, API, third-party integration, error handling and observability, security and PHI, and AI engineering. (~2K)
4. The Batch 3 ticket list with their done-verify commands - the re-verification map for any fix that changes behaviour. (~0.6K)
5. The cross-schema isolation rule and the migration gates, which the two standing criteria verify mechanically. (~0.6K)
6. The parent spec #717 in full, as the Spec axis's reference. (~4K - read it once, deliberately)

## Do NOT read

- `docs/archive/`.
- The prototype folder and any superseded plan documents.

## Baseline verify (must pass before the first edit)

- `npm run lint`
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria → commands)

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run test:integration`
- `npm run migration-check`
- `npm run scan`
- `npm run test:e2e` if the fixes touch navigation

## Handoff notes

- This is a review ticket; the diff is the input, so scope the review to Batch 3's change set rather than the whole repository.
- Fix in place for anything that is clearly wrong. For anything that is a genuine design ambiguity, raise it on #717 rather than choosing silently - this ticket's job is to find those.
- Two criteria are mechanically verifiable and should be checked explicitly rather than eyeballed: module isolation (the cross-schema FK scan plus a grep for cross-schema SQL in the new modules) and PHI-freedom (no raw identity reference reaches the observability schema; keys are one-way hashes).
- A fix that changes a ticket's acceptance criteria invalidates that ticket's brief. Re-verify against the ticket's own done-verify commands and refresh the affected brief.
- The integration suite skips silently when PostgreSQL is unreachable. A green run that skipped is not evidence - confirm it actually ran.
