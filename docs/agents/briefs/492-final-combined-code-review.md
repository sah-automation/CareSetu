# Brief - 492 Final combined code-review pass

**Ticket:** #492 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

A final combined review pass over every ticket in this breakdown (T1-T12) as they land, using the code-review skill, and fixing any bugs found. Runs the two axes - repo coding standards and spec conformance to #479 - across the whole delivery, then fixes issues in follow-up commits so the PHASE-8.1-completion state is clean.

AC:

- [ ] Code-review skill run over the combined diff of all delivered tickets (or the delivery branch) - both axes reported
- [ ] Every Standards or Spec finding is triaged; real bugs fixed, defers recorded
- [ ] Repo harness green after fixes: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run migration-check`
- [ ] No regressions introduced by the review fixes

## Read-list (in order)

1. The `code-review` skill instructions (see `code-review` skill in this workspace) - the two-axis workflow to run (~1K tokens)
2. `docs/standards/*` (coding, api, third-party-integration, error-handling-observability, security-phii, ai-engineering) - the Standards axis; read the relevant sections per deliverable (~1.5K tokens)
3. The parent PRD #479 (Problem/Solution, Implementation Decisions D-A..D-E, "Out of Scope", Further Notes) - the Spec axis (~900 tokens)
4. The delivered ticket list #478-#492 and their briefs (`docs/agents/briefs/`) - what each ticket promised, the acceptance criteria to check against (~600 tokens)

## Do NOT read

- Anything outside the reviewed changes, the standards, and the spec - the review is scoped to the PHASE-8.1-completion state only.

## Baseline verify (must pass before the first edit)

- Full repo harness on the merged state: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run migration-check`
- Known pre-existing (unrelated, recorded at briefing): backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string. `typecheck` + `migration-check` green.

## Done-verify (acceptance criteria → commands)

- The harness commands above pass after review/fixes
- Both code-review axes reported (Standards + Spec) with findings triaged

## Handoff notes

- Optional but requested: the final "does it all work together" gate for #479.
- Run the review against a fixed point (the merge-base before T1 or the delivery branch), not against main, so the diff is exactly this delivery.
- Apply the repo's review conventions: fixes land as follow-up commits, never amends; defers recorded in the review report.
