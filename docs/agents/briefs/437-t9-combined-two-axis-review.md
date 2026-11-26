# Brief - T9 PHASE-8 review-close: combined two-axis review of the whole fix + bug fixes

**Ticket:** #437 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~6.0K tokens (budget 10K) - within budget (builds on the ten prior briefs' loaded context)

## Scope

Phase-8 review-close T9 (final combined review). Once every review-close ticket lands, run a two-axis review of the whole implementation (standards + spec against #426) using the code-review skill, fix any bugs or contract gaps found, and confirm the full repo harness is green. This is the ticket that makes the review-close genuinely done: each slice is verifiable on its own, but only this ticket checks the combined system end-to-end.

Acceptance criteria (verbatim from ticket):

- [ ] Code review run on the review-close branch/diff (standards axis + spec axis against #426)
- [ ] Any found bug or unserved contract is fixed with its own committed work
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan` all green on the combined result

**Blocked by:** All of #427 (T1), #428 (T2), #429 (T3), #430 (T4), #431 (T5), #432 (T6a), #433 (T7), #434 (T6b), #435 (T8a), #436 (T8b).

## Read-list (in order)

1. The `code-review` skill workflow (STD-001 repo available at `D:\Dev\tools\opencode\config\opencode\skills\code-review\SKILL.md`) - the two-axis (standards vs spec) parallel-review procedure to run against the review-close diff. (~0.8K)
2. The full parent spec #426 - the spec axis reference: problem statement, the 8 child-ticket scope, implementation decisions, testing decisions, and every acceptance surface the review-close must jointly satisfy. (~3.2K)
3. The ten briefs #427-436 (this folder) - the per-slice contracts whose combined result this ticket verifies; the implementer already holds these from the serial chain. (~2.0K)
4. The combined diff surface of the ten tickets (branch diff from origin/HEAD, or merge-base `b8c8dea`...the review-close tip) - reviewed through the code-review skill, not re-read from scratch. (~0K of fresh token, the diff walks its own surface)

## Do NOT read

- Anything outside the review-close surface: intake/partner/iam module internals not named by #426, the frontend, `docs/archive/`. The machines/facades are already loaded from the ten briefs.

## Baseline verify (must pass before the first edit)

Full harness on the pre-review tree (all ten tickets merged): `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan` - all must be green before the review starts (each ticket's own briefs confirm their gates on the shared base).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run lint`
- `npm run typecheck`
- `npm run migration-check`
- `npm run scan`
- Code-review skill run recorded against the review-close diff (standards + spec axes, both reported)

## Handoff notes

- This ticket is the closest analog to the repo's own REVIEW-FIX precedent (e.g. `REVIEW-FIX-T340*` briefs): run the review, then land fixes as their own commits.
- The original two-axis review that produced #426 was run on `b8c8dea...a472db1`; this ticket re-runs the same two axes on the review-close diff (which continues past `a472db1`), so the baseline diff anchor is the same `b8c8dea`...new-tip.
- Pay special attention to cross-ticket seams where a single slice passes alone but the combined behaviour must hold: the T2-born `doctor_id`-unset case claimable in T4's handshake, the T1 boolean declaration consumed by T5's route + the machine, T3's close route wrapped by T5's idempotency, and the T6a/T6b split staying behaviour-identical under the T4 ownership guard.
- Docstring-only changes from T8a may touch files that T9's review also reads - coordinate so T9's own fix commits do not regress the T8a FEAT-tagging gate (or re-tag as needed).
- Any fix landed here must itself stay within the #426 spec's declared scope (no new seams, cap stays two AI drafts, forced-review stays record-only). If a true contract gap needs a spec change, escalate back to #426 rather than silently expanding scope.
