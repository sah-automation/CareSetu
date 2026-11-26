# Brief - T07 Intake capture facade

**Ticket:** #351 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A patient can submit a symptom intake (voice media ref or typed text) and retrieve it: submit_intake validates one-mode-per-intake and both caps (2000-char text; 3 voice attempts), commits the intake row plus the intake.captured outbox event in one local transaction, and saves before any AI runs. get_intake returns intake + transcript + media refs + status and get_pre_summary returns the draft, confidence, honesty fields and patient edits. request_rx_draft is declared on the facade as a contract stub only (verified in Phase 8). Tested at the facade-with-fakes seam.

Acceptance criteria:

- [ ] submit_intake commits the intake row and intake.captured outbox row in the same transaction (asserted via write_outbox on the same connection)
- [ ] One-mode-per-intake and both caps (2000 chars / 3 attempts) are enforced server-side with typed errors
- [ ] get_intake and get_pre_summary return the agreed DTO shapes (status from the machine, honesty fields present)
- [ ] request_rx_draft exists as a contract stub facade method
- [ ] Intake capture is never rolled back on later AI failure (separate save path tested at the pipeline seam, durable here)

## Read-list (in order)

1. Issue #344 Facade API surface + Implementation Decisions - the ratified capture contract and DTOs (~2K)
2. `apps/backend/modules/partner/facade.py` - thin coordinator pattern (~1K)
3. `apps/backend/modules/partner/registration_facade.py` - transaction + outbox in one commit pattern (~1.5K)
4. `apps/backend/bus/outbox_writer.py` - write_outbox contract for the same-connection assertion (~1K)
5. `apps/backend/modules/intake/domain/state_machine.py` (T02) + event builders from T04 - status from the machine, intake.captured envelope (~1K)
6. `apps/backend/modules/intake/schema/models.py` (T01) - intakes/pre_summaries columns (~1K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- worker internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Capture durability is structural: the row + outbox event commit in one local transaction, so a later AI failure never rolls back the intake.
- request_rx_draft is a declared contract stub only - no behavior, Phase 8 makes it live.
