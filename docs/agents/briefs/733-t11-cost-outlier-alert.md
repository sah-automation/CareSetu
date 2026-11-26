# Brief - #733 Cost-outlier alert from the actor's own trailing baseline

**Ticket:** #733 · **Parent:** #717 · **Refreshed:** 2026-10-22
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Raise a cost-outlier alert when one actor's most recent day of spend deviates sharply from that same actor's own trailing seven-day baseline, and name the actor with both figures so an operator can judge genuine abuse from a one-off. Relative deviation is deliberate: a legitimately heavy patient and a genuinely abusive one are indistinguishable by an absolute cap.

- [ ] The rollup compares an actor's most recent day of spend against that actor's own trailing seven-day baseline and raises a cost-outlier alert when the deviation crosses a configured multiple.
- [ ] The alert names the actor and carries both figures - the recent day and the baseline - so it can be judged.
- [ ] No absolute spend cap is used for outlier detection; the deviation is relative to the actor's own history.
- [ ] The alert uses the existing alert vocabulary, dedupe marker and auto-resolve machinery.
- [ ] The threshold is configurable alongside the existing rollup thresholds.

## Read-list (in order)

1. Spec #717 - Implementation Decision 10; the cost-outlier user stories. (~0.8K)
2. The rollup domain's threshold dataclass and its module-level defaults, and how the budget figure was the only threshold driven from environment. **Refreshed 2026-10-22 (#757):** the thresholds now come from the settings object as a family, with the ADR-pinned ones left as constants - see the handoff notes.
3. The alert builders, evaluators and the dedupe marker, plus the auto-resolve kind set. Copy the shape; do not add a parallel alert path. (~1.2K)
4. The daily per-actor aggregate from #725 - the columns this compares, and the date grain. (~0.5K)
5. The rollup round-trip integration test - extend it for the raised alert, its payload and the below-threshold case. (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The business read facets - #731, #732 consume the alert, they do not create it.
- The other alert kinds - #734 owns the reliability kinds.
- The intake and care modules, the vendor exporters.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- The actor key in the alert payload is **pseudonymous**. An alert that names a patient by raw identity breaks the no-PHI rule; it names the actor by its aggregate key.
- "Baseline" is the actor's own trailing seven days. An actor with no history has no baseline and must not alert - write that case explicitly, it is the one that will fire first on a fresh database.
- The alert must be resolvable: when the deviation clears, it resolves. Use the existing auto-resolve machinery and decide whether this kind belongs in the resolvable set - say which, in the code.
- Threshold configuration follows the existing threshold dataclass. Only the budget threshold is environment-driven today; do not invent a second configuration mechanism for one number. **Refreshed 2026-10-22 (#757):** the whole rollup threshold family is now environment-driven through ONE mechanism - the settings object (`app/config.py`) owns the default literals and the worker passes them into the threshold dataclass, so the outlier multiple is `OBSERVABILITY_COST_OUTLIER_MULTIPLE` and its baseline window is `OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS`. The four thresholds a decision record pins (the seven-day cost baseline, the `< 1%` error-rate objective, its 100-request floor, the AI call's `p95 <= 30 s` objective) stay constants on purpose: an objective is a promise, and coding-standards §9.2 allows a threshold to remain a constant only when an ADR pins it.
- No absolute cap. If you find yourself comparing spend to a rupee number, you have implemented the wrong rule.
