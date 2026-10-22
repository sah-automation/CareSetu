# Brief - 10 Combined review of the 662 implementation

**Ticket:** #672 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** spec + standards + the combined diff of #663-#671 - the reading IS the deliverable here, so the SIZING-GATE write-budget does not apply in the usual way; keep fixes scoped to findings.

## Scope

A final two-axis review of the whole #662 implementation: run the code-review skill over the combined changes of tickets #663-#671 against both the standards (docs/standards) and the spec (#662 problem statement, solution, user stories, testing decisions, out-of-scope), then fix any bugs or gaps the review finds. The full harness must be green at the end.

Acceptance criteria:

- [ ] A `/code-review` pass covers the combined diff of tickets #663-#671 on both axes (Standards and Spec)
- [ ] All findings are fixed or explicitly dispositioned
- [ ] Full harness green: `npm run test:unit`, `npm run lint`, `npm run typecheck`, `npm run test:integration`, `npm run migration-check`
- [ ] No out-of-scope change crept in (per spec #662 "Out of Scope")

## Blocked by

#663, #664, #665, #666, #667, #668, #669, #670, #671 - the full implementation must exist before the combined review.

## Read-list (in order)

1. Spec #662 in full - problem statement, solution, user stories, implementation/testing decisions, out of scope (the Spec axis) (~5K)
2. The relevant standards in `docs/standards/` - coding-standards, api-standards, error-handling-observability, security-phii-standards (the Standards axis; skip third-party/AI unless a finding implicates them) (~6K)
3. The combined diff of #663-#671 (the code under review)
4. The per-ticket briefs in `docs/agents/briefs/662-t0*.md` - each ticket's done-verify and handoff notes as the checklists the diff must satisfy

## Do NOT read

- `docs/archive/`; PRD/roadmap beyond what the spec quotes; module docs except where a finding requires them
- Pre-existing code outside the diff hunks, except to verify a suspected bug's blast radius

## Baseline verify (must pass before the review starts)

- Full harness with #663-#671 merged: `npm run test:unit`, `npm run lint`, `npm run typecheck`, `npm run test:integration`, `npm run migration-check`

## Done-verify (acceptance criteria → commands)

- The same full harness, green after fixes
- A review report exists with every finding fixed or explicitly dispositioned
- Spot-check the spec's "Out of Scope" list against the diff (no consent UI, no full_record grants, no egress/state-machine changes)

## Handoff notes

- The code-review skill runs Standards and Spec reviews in parallel sub-agents and reports side by side - use it as-is.
- Known baseline facts from briefing: backend unit 2919 passed, frontend unit 2148 passed, lint/typecheck/migration-check green (head `3e7c5a1d8f24`), integration 263 passed with 1 pre-existing failure (`tests/integration/test_consent_check_gate.py::test_p95_latency_under_50ms` - p95 latency budget, environment-sensitive). That failure is NOT a regression of this work; re-run it before dispositioning any latency finding.
- Spec out-of-scope traps most likely to creep: revocation semantics, consent cache rules (ADR-0004), egress log, browse/find pick extension, e2e widening.
