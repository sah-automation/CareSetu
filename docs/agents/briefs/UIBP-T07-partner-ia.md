# Brief - T07 Partner channels IA (lab + chemist)

**Ticket:** #185 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Whether lab and chemist share one partner console shell with role-specific widgets or get separate consoles; top-level areas each needs: bookings/sample-pickup queue, report upload/match flow (lab), routed-prescription queue and fulfillment/failure workflows (chemist), settlement view, profile/credentials.

Resolution must produce: shared-vs-separate verdict with rationale, per-role nav maps with key screens at wireframe-description level (queues, upload/match flow, fulfillment + out-of-stock/delivery-failure choices, settlement), and credential/profile surfaces. Uses shell conventions from #182 as fixed input.

## Read-list (in order)

1. #182 closing comment - shell conventions (~0.5K)
2. `docs/prd/project-prd.md` §4.5 both features (`FEAT-010` diagnostics booking/pickup, `FEAT-011` report filing + wrong-upload protection) (~3K)
3. `docs/prd/project-prd.md` §4.6 both features (`FEAT-012` fulfillment routing, `FEAT-013` out-of-stock & delivery-failure handling) (~2.5K)
4. `docs/prd/project-prd.md` §4.8 both features (`FEAT-016` settlement, `FEAT-017` cancellations/refunds) (~2.5K)

## Do NOT read

- Patient/doctor/operator epics beyond their handoff points, backend modules, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #185 with the verdict + IAs; ticket closed
- Map #178 Decisions-so-far gains one line linking #185

## Handoff notes

- Partner personas run small shops on phones - queue-and-action screens, minimal typing.
- Wrong-upload protection (`FEAT-011`) means the lab upload flow has an order-ID + patient confirmation binding step - design that screen deliberately.
- Out-of-stock and delivery failure are patient-choice moments (`FEAT-013`) - partner screens present options; the choice UI lives in the patient IA ticket.
