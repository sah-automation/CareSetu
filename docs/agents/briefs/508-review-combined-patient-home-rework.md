# Brief - 508 Review the combined patient home rework

**Ticket:** #508 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A final review pass over the combined implementation of the nine patient-home rework tickets. Runs the repo's review flow over the whole change since the pre-work baseline, triages the findings, fixes any bugs found in the combined implementation, and leaves the tree green across unit, typecheck, lint, and the Playwright suite where the harness allows.

- [ ] Review of the combined implementation is run and findings are triaged.
- [ ] Any bugs found are fixed on top of the nine tickets.
- [ ] Unit suites, typecheck, and lint pass; Playwright passes where the harness allows.

## Read-list (in order)

1. The review skill runbook (`/code-review`) - how it scopes the changes since the baseline and the two review axes it applies (~1K).
2. The combined diff of the nine rework tickets (#499-#507) against their shared pre-work baseline (the patient home at the state #499 opened from) - read the diff, not the whole repo (~4K).
3. Parent spec #498 as the originating contract the reviews check against (already carried in the ticket briefs; re-read its Implementation/Testing Decisions if needed) (~1K).
4. The nine briefs' acceptance criteria as the done-contract.

## Do NOT read

- Anything outside the change under review - unrelated modules, backend, docs/archive.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`, `npm run typecheck:frontend` (green on 2026-09-21 pre-work baseline; drift since then is what this ticket fixes).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`, `npm run typecheck:frontend`, `npm run lint`, and the Playwright suite (`npm run test:e2e`) where the harness allows - all green after fixes.

## Handoff notes

- The review fixes ride on top of the nine tickets; do not rewrite the tickets' commits.
- Key integration seams to double-check: the shared composed `page.test.tsx` seam, the light AppShell widening confined to the patient density, the dictionaries parity (en/hi + arity), and that the e2e specs no longer pin the old "Welcome, Patient" literal.
- The parent issue #498 must remain OPEN (do not close or modify it beyond this chain driving it).
