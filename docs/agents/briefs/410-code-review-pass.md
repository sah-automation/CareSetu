# Brief - 410 T13 Code-review pass over combined T01-T12 + fix + commit

**Ticket:** #410 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

With all remediation slices merged, the combined T01-T12 implementation is reviewed as one diff through the two-axis `/code-review` skill (Standards: does it follow the repo's coding/api/security/AI standards; Spec: does it match what #397 and the problem statements asked for). Every finding is fixed, the full repo harness is re-run on the reviewed tree, and the fixes are committed when the review found bugs. Acceptances: `/code-review` runs over the combined T01-T12 diff and its findings are recorded (both axes); every finding is fixed or accepted with a written rationale; the full repo harness passes on the reviewed tree; fixes are committed once green.

## Read-list (in order)

1. The `/code-review` skill instructions (two-axis process: Standards + Spec, run in parallel sub-agents)
2. The combined T01-T12 diff (since the last review base) - the surface under review
3. The spec axis: issue #397 and `docs/plans/phase7-review-problem-statements.md`
4. The standards axis, each skimmed to the clauses this pass touches: `docs/standards/coding-standards.md` (esp. §8 no-op bodies, §9.2 cross-language value duplication), `api-standards.md` (rate limits, error envelope), `third-party-integration-standards.md` (cost metering), `error-handling-observability.md`, `security-phii-standards.md` (consent-gated/PHI-minimized egress), `ai-engineering-standards.md` (cost-aware routing)

## Do NOT read

- Anything the reviewed tickets explicitly deferred as out of scope (Phase 14 dashboard, paid tier config, ASR tuning)
- `docs/archive/`, unrelated modules

## Baseline verify (must pass before the first edit)

- Full repo harness on the merged T01-T12 tree before any review edit: `npm run test:unit:backend` (1732 at last baseline), `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan`; integration when local PostgreSQL is reachable

## Done-verify (acceptance criteria -> commands)

- `/code-review` completes with findings recorded for both axes
- Full repo harness passes on the post-fix tree; fixes committed (`git commit`) once green

## Handoff notes

- Blocked by #398-#409 (all of T01-T12)
- This is the gate that guarantees the consolidated pre-shipping pass lands coherent and green - same promise the spec's "Verify with the repo harness before declaring done" list makes
- Only commit when the user's workflow expects it (the ticket's acceptance explicitly calls for committing the review fixes); do not touch the parent issue #397
