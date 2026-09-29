# Brief - #519 Cross-ticket review of #512 implementation (code-review + bugfix)

**Ticket:** #519 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

A final review pass over the combined implementation of #512. Run `/code-review` against the merge-base of this work across the two axes (repo standards + spec conformance to #512), then fix any standards or spec bugs found and re-verify with the repo harness. This is the safety gate that guarantees the slices compose into one coherent feature.

Acceptance criteria (from the ticket):

- [ ] `/code-review` run over all `#512` implementation tickets since their common base; findings reported per ticket.
- [ ] Any standards/spec bugs found are fixed in the same shape as the offending slice.
- [ ] Full harness green at the end: unit suites (backend + frontend), integration (where PostgreSQL reachable), typecheck, lint, and `check:boundaries`.

## Read-list (in order)

1. The `/code-review` skill - its two-axis (Standards + Spec) parallel-review workflow and reporting shape (~0.5K).
2. Parent spec #512 - the exact contract to check the implementation against (event payload, card anatomy, honesty rule REQ-033, tone/tag decisions) (~1K).
3. The repo standards docs relevant to the touched areas (`coding-standards`, `api-standards`, `error-handling-observability` §2 for the resolver's degrade-to-None logging, `security-phii-standards`) (~0.5K).

## Do NOT read

- `docs/archive/`, unrelated modules' internals beyond what the review diffs touch.

## Baseline verify (must pass before the first edit)

- `npm run test:unit` (backend green 2026-09-23: 2336 passed; frontend full-suite can flake on worker spawn under load - treat the #513-#517 targeted files as the green core, see those briefs), `npm run typecheck`, `npm run lint` (all hooks green 2026-09-23), `npm run check:boundaries` (module-boundary hook green via lint).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit`, `npm run typecheck`, `npm run lint`, `npm run check:boundaries`.
- `npm run test:integration` where PostgreSQL is reachable (the consumers file scope passes: 8/8 on 2026-09-23).

## Handoff notes

- Review against a fixed base: the merge-base of the feature branch(es) against `main`, so the diff is exactly the #513-#518 work. Findings are reported per ticket, then fixes land in the same shape as the offending slice (state which ticket each fix back-fits).
- Known starting-truth flakes on this machine (2026-09-23): the full frontend suite can throw 2 test timeouts + 4 fork-pool spawn errors under load, and the full integration suite shows one unrelated early failure - these predate this work; judge "green" on the targeted files per the per-ticket briefs, and re-run any flake once before treating it as a real regression.
- The ADR-0017 naming, event-registry payload note, and PROTO-3.1 finalize (from #518) are reviewable prose, not code - still check them for consistency with the contracts the implementation actually shipped.
