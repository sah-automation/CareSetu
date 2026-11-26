# Brief - 551 Combined code-review pass + fixes

**Ticket:** #551 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

A final combined review of the batch's combined implementation - a /code-review pass over the whole batch (standards + spec axes) against the parent spec's requirements and the ticket briefs - shipping fixes for any bugs, standard violations, or spec gaps as their own commits (repo precedent: the combined review tickets of prior batches).

AC:

- [ ] /code-review run over all batch tickets' combined implementation against the parent spec #529 and the ticket acceptance criteria
- [ ] Any found bugs/standard violations/spec gaps are fixed as their own commits; review report recorded on this ticket
- [ ] Repo harness green post-fix: `npm run test:unit`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan`

## Read-list (in order)

1. Parent spec #529 (the contract) - the solution points, implementation decisions, and testing decisions the whole batch must satisfy (~3K).
2. The batch's delivered briefs (docs/agents/briefs/530-_ through 549-_) - the acceptance criteria each slice shipped against, used as the spec axis of the review (~2K total across the relevant ones).
3. The delivered seams named in those briefs (record scope, profile-media port, doctor patients facade, /v1/me photo, partner private projection) - standards-axis checkpoints (per `docs/standards/coding-standards.md`, `api-standards.md`, `security-phii-standards.md` as violated).

## Do NOT read

- Anything outside the batch's surface and its standards - unrelated modules, `docs/archive/`, other batches' briefs.

## Baseline verify (must pass before the first edit)

- Full harness on the merged batch tree: `npm run test:unit`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan` - all must be green before the review starts (the batch's delivery gates).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan` - green post-fix.
- Review report recorded as a comment on this ticket, with each fix in its own commit.

## Handoff notes

- Runs on the combined batch result; blocked by every other batch ticket (#530 through #550 effectively).
- Follow the repo's `/code-review` skill: parallel Standards and Spec axes; fixes land as their own commits, not squashed into the reviewed changes.
- The review report is part of the acceptance criteria - record findings + the commit ids that fixed them on this ticket.
- No em-dashes anywhere (lint-gated); use simple dashes.
