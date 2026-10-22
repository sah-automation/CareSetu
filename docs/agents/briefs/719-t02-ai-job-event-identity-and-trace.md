# Brief - #719 AI job events carry the patient, a nullable doctor and the trace id

**Ticket:** #719 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

AI job events today carry an intake reference and a job reference and nothing else, which makes per-patient attribution arithmetically impossible. Carry the patient, a nullable doctor and the trace id on the completed and failed AI job payloads, resolved producer-locally from state already in scope at the publish sites. No module reads another module's tables.

- [ ] The AI-job-completed and AI-job-failed payloads carry a patient reference, a nullable doctor reference and the trace identifier.
- [ ] Both intake publish sites populate them from state already in scope; no new query and no cross-module read is introduced.
- [ ] The doctor reference stays null on the transcription and structuring legs, which have no doctor.
- [ ] The observability consumer mirrors accept the widened payloads and the existing round trips stay green.
- [ ] Only identity references travel - no clinical content, per the observability no-PHI rule.
- [ ] The event registry's payload footnotes for both events are updated.

## Read-list (in order)

1. Spec #717 - Problem Statement holes 2 and 3; Implementation Decisions 2, 3, 7 and 41. (~1.5K)
2. The intake domain's AI job event models and envelope builders - `AiJobCompletedPayload`, `AiJobFailedPayload`, and the two envelope builders. (~0.8K)
3. The intake pipeline adapter's two publish sites - the job-complete helper and the job-fail helper - and the state each already holds (the intake reference, the job row it just wrote). (~1.5K)
4. `get_trace_id` in the observability logging module - the accessor the outbox writer already uses to stamp a traceparent. Confirm it is readable from a worker context, not only from a request context. (~0.5K)
5. The observability consumer's AI job payload mirrors and its two explicit handlers. (~0.8K)
6. `docs/architecture/internal-modules.md` §4.2 event registry - the `ai_job.completed` / `ai_job.failed` rows and their payload footnotes. (~0.7K)
7. `tests/unit/test_intake_events.py` - the existing payload-shape assertions you will extend. (~0.6K)

## Do NOT read

- The AI gateway implementations, the provider adapters, the pricing table internals.
- Frontend sources, `docs/archive/`.
- The observability read queries - no read changes in this ticket.
- The care and partner modules beyond confirming no reader of the widened payload exists yet.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Producer-local only.** If you find yourself wanting a query to resolve the patient, you are about to break module isolation - the intake row is already in hand at both publish sites.
- The doctor field is deliberately nullable and stays null on these two legs. It exists because the drafting leg is the one that has a doctor; do not go looking for a doctor on the transcription path.
- #722 (meter the drafting leg) reuses these widened payloads. Do not widen them further here - a second widening in a sibling ticket is how a wire shape forks.
- Blocker #718 lands the shared integration fixture this ticket's round trips may use.
