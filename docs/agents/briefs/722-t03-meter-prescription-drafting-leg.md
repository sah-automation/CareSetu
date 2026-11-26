# Brief - #722 Meter the prescription-drafting leg

**Ticket:** #722 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The prescription-drafting leg is the one AI task type that writes no AI job row and publishes no event, so a whole leg of spend is invisible and `draft` is a declared-but-never-produced value. Give the draft request the same treatment the transcription and structuring legs already have.

- [ ] A draft request writes an AI job row with task type `draft`, provider, model, input and output tokens, cost in paise and duration.
- [ ] A successful draft publishes AI-job-completed and a failed draft publishes AI-job-failed, on the same transaction as the job row write.
- [ ] A draft that fails still records the job as failed; no draft consumes provider tokens without a job row.
- [ ] `draft` now appears as a produced task type in the observability usage aggregate, proven end to end.
- [ ] No new task type is invented; `summarize` stays declared-only.
- [ ] The drafting-cap and consent gates on the draft path are untouched.

## Read-list (in order)

1. Spec #717 - Problem Statement hole 1; Implementation Decision 1. (~0.8K)
2. The intake facade's draft-request seam `request_rx_draft` - what it reads, what it calls, and the fact that today it writes no job row and publishes nothing. (~1.2K)
3. The intake pipeline adapter's three job helpers - the insert, the complete and the fail - as the exact pattern to copy, including how the complete helper computes cost. (~2K)
4. `compute_cost_paise` and the pricing table resolver in the intake pricing module. (~0.6K)
5. The intake AI jobs table and its task-type check constraint - confirm `draft` is already permitted. (~0.5K)
6. The care facade's draft entry point that calls into the intake seam, and the drafting-cap exception it raises. (~0.8K)
7. The AI gateway protocol's draft method and the result type it returns, to see whether tokens are reported on success and on failure. (~0.8K)
8. `tests/unit/test_intake_facade_capture.py` (its draft-request seam section) and `tests/unit/test_intake_pipeline_degradation.py` - the existing seams to extend. (~1K)

## Do NOT read

- The provider adapter implementations beyond their result types.
- Frontend sources, `docs/archive/`.
- The observability consumer and rollup - `draft` flows into them through the existing event contract, unchanged.
- The consent implementation beyond the gate this path already passes.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Blocked by #719**: the completed/failed payloads now carry patient, nullable doctor and trace id. Reuse those; do not introduce a second, draft-only event shape.
- The draft request is initiated from the care module but the job row and the event belong to the intake module, which owns both. Keep the write inside the intake seam - care must not write the intake table.
- Failure metering is the subtle part: a provider failure can still have burned tokens. Decide from the gateway's result type whether a failure carries usage, and record what it actually knows. Do not invent a token count.
- Do not touch the third-draft cap or the consent gate. A metering change that alters when a draft is allowed is a different ticket.
- Downstream, #723 asserts `draft` appears in the new per-job spend rows. That proof depends on this ticket landing first.
