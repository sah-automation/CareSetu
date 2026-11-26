# Brief - T10 AI pipeline consumer: happy path + idempotency

**Ticket:** #354 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A captured intake gets structured in the background with no patient-visible wait: the intake.captured handler (ledger-first, idempotent) creates an ai_jobs row, runs transcribe then structure through the gateway via the mock provider, writes a Draft pre_summary, and publishes pre_summary.ready and ai_job.completed. Replaying the same captured event is a no-op. Budget meter and consent gate are wired but their enforcement paths land in T11.

Acceptance criteria:

- [ ] Ledger-first ordering: replaying an intake.captured event_id produces exactly one pre_summary (idempotent dedupe)
- [ ] Happy path produces a Draft pre_summary with the provider confidence and honesty fields
- [ ] The ai_jobs row records provider, model, input/output tokens, cost, latency, status and attempt count
- [ ] pre_summary.ready and ai_job.completed are published on success
- [ ] The handler path never raises a user-visible error to the patient

## Read-list (in order)

1. `apps/backend/modules/notify/domain/consumer.py` - handler pattern for the intake.captured subscription (~1.5K)
2. `apps/backend/bus/handler_harness.py` + `ledger.py` - ledger-first delivery harness for idempotent dedupe (~1.5K)
3. `apps/backend/modules/notify/adapters/__init__.py` - registration uses the shared harness (~0.5K)
4. The AI gateway port + mock from T05 - transcribe/structure call contract, confidence knob (~1.5K)
5. The intake machine (T02) and event builders (T04) - Captured -> Structuring -> Ready for Review, pre_summary.ready envelope (~1K)
6. `docs/architecture/internal-modules.md` §4.2 - event producer/subscriber contract for MOD-005 (~1K)

## Do NOT read

- `docs/archive`
- frontend sources
- consent facade internals
- budget internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Idempotency is ledger-first: a replayed intake.captured event_id yields exactly one pre_summary.
- Budget meter and consent gate are wired here but their enforcement/egress paths land in T11 - do not implement the hard stops in this ticket.
- Handler failures must never surface as a user-visible error to the patient (degrade, don't error).
