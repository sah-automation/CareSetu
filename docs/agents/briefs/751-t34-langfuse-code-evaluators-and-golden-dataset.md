# Brief - #751 Langfuse code evaluators over a synthetic golden dataset

**Ticket:** #751 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Evaluate AI output without spending inference money and without touching clinical content: deterministic code evaluators running over PHI-free metadata plus a synthetic golden dataset. LLM-as-a-judge and the richer dataset workflow stay deferred; what ships is code evaluators whose scores aggregate.

- [ ] Evaluations run as deterministic code evaluators, so evaluation itself costs no inference money.
- [ ] Evaluations run against a synthetic golden dataset; no real clinical content reaches an evaluation pipeline.
- [ ] Evaluation scores are recorded as numeric or boolean, so they aggregate.
- [ ] Scores are recorded through the observation-level evaluator path, because trace-level evaluation at the vendor is deprecated.
- [ ] Evaluations run on the same daily batch as the metrics pull, not behind a live dashboard refresh.
- [ ] The PHI-free span-metadata allow-list continues to gate what the evaluators can read.

## Read-list (in order)

1. Spec #717 - Implementation Decision 40; Out of Scope (the full Langfuse evaluation programme: LLM-as-a-judge, judge-to-human agreement, the richer dataset workflow). (~1K)
2. `docs/adr/0024-*.md` and the AI tracing vendor's deprecation note in the spec - trace-level evaluation is deprecated with a cloud cutover; observation-level evaluators from the outset. (~0.5K)
3. The vendor client #750 extended, and the metrics batch it runs on. (~0.7K)
4. The span-metadata allow-list and the PHI-free constraint it enforces. (~0.4K)
5. The AI quality metrics the existing quality read already surfaces, so the evaluators measure something the console can show rather than a parallel invention. (~0.7K)
6. The product PRD's AI quality expectations - what "good" means for transcription and structuring output, which is what the golden dataset encodes. (~0.8K)
7. The existing test convention for a pure scorer plus the fake-transport pattern. (~0.5K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The annotation queue - #752 owns it.
- The Grafana assets, the collector configuration.
- Real clinical fixtures anywhere in the repository - the golden dataset is synthetic by construction, so the temptation to reuse an existing fixture is the trap.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Synthetic means synthetic.** Do not reuse an existing test fixture that contains realistic clinical content, however convenient. The golden dataset is fabricated, and a test that asserts it contains no real content is worth writing.
- Numeric or boolean scores only. A score that cannot aggregate is a score nobody can chart, and the whole point is that scores roll up.
- Observation-level, not trace-level. Trace-level evaluation at the vendor is deprecated with a cloud cutover in November 2026; anything built on it must not be built at all.
- Deterministic means the same input yields the same score, with no model call. That is what makes it free, and it is the reason LLM-as-a-judge stays out of scope.
- #752 feeds this queue with human judgements from doctor review outcomes; the score shape you choose here should be able to hold that signal.
