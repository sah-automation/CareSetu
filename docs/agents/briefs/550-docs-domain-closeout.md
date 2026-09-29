# Brief - 550 Docs/domain closeout for the batch

**Ticket:** #550 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The docs are closed out to reflect the delivered truth of the batch: the glossary/ADR/registry groundwork from the domain vocabulary ticket is reconciled with what actually shipped, the roadmap batch status and module matrices are updated, and the PRD feature sections touched by this batch are annotated. No code; docs reflect reality (prior art: the phase docs-closeout tickets).

AC:

- [ ] Glossary entries + ADRs reconciled with delivered naming and behavior (any drift in-scope terms updated)
- [ ] `internal-modules.md` sync matrix + event registry reflect the shipped seams/events; `implementation-roadmap.md` batch status updated
- [ ] PRD sections touched by the batch annotated (FEAT rows, delivery notes)
- [ ] `npm run lint` green

## Read-list (in order)

1. The delivered tickets' closing state (#530..#549) - the interfaces, scopes, seams, and events that actually shipped (grep their briefs + the closing comments for the final shapes) (~2K).
2. The groundwork artifacts from #530: the CONTEXT.md glossary entries + the three batch ADRs - the terms and decisions to reconcile against delivery (~1.5K).
3. `docs/architecture/internal-modules.md` §4.1 sync matrix + §4.2 event registry and `docs/roadmap/implementation-roadmap.md` §2.8a + §3.x - the rows/status to update to shipped truth (~1.5K).
4. The PRD feature sections touched (FEAT rows for profile, doctor console, consent, egress) in `docs/prd/project-prd.md` - annotate delivered state (~1K).
5. `docs/agents/domain.md` - the glossary conventions to honor when reconciling (~0.3K).

## Do NOT read

- Code internals beyond the named seams/events, `docs/archive/`, prototype assets.

## Baseline verify (must pass before the first edit)

- `npm run lint` - confirmed green 2026-09-24; re-run on the finished batch tree before closing this out.
- `npm run migration-check` + the unit suites green on the delivered tree (so docs reflect a working batch).

## Done-verify (acceptance criteria -> commands)

- `npm run lint` - prettier / whitespace / no-em-dash gate on edited markdown.
- Read-through of the reconciled glossary/ADR/registry/roadmap/PRD annotations against the shipped behavior.

## Handoff notes

- Terminates the batch (effectively #530 through #549 must be delivered); the reconciliation starts from #530's registered vocabulary and updates only what drifted.
- Re-register any seam/event that shipped differently than the groundwork ticket registered - the source of truth is the delivery, not the decision doc.
- PRD annotation is additive (FEAT rows + delivery notes); do not rewrite requirements.
- No em-dashes anywhere (lint-gated); use simple dashes.
