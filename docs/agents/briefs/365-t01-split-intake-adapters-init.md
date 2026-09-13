# Brief - 365 T01 Split adapters/**init**.py into composition root + pipeline module

**Ticket:** #365 Â· **Parent:** #364 Â· **Refreshed:** 2026-09-09
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Pure extraction refactor: the 617-line `modules/intake/adapters/__init__.py` is split into a thin handler-registration file and a focused pipeline module. Zero behavioral change - all existing tests pass unchanged. This creates the `pipeline.py` file where T03/T05/T06 later make their changes.

Acceptance criteria (from ticket):

- [ ] `adapters/__init__.py` contains only handler registration (`register_handlers`, `_on_intake_captured`, `_on_intake_retry_requested`, constants) and is â‰¤ 120 lines
- [ ] `adapters/pipeline.py` contains: `_run_structuring_pipeline`, `_finalize_pipeline`, `_degrade_to_raw_review`, `_fail_job`, `_insert_ai_job`, `_failure_reason`, `_egress_context`, `_build_egress_gate`
- [ ] `npm run test:unit:backend` passes with no changes to test files
- [ ] `npm run typecheck:backend` passes (mypy strict)

## Read-list (in order)

1. `apps/backend/modules/intake/adapters/__init__.py` (full file, ~617 lines) - the whole surface being split (~6K tokens)
2. `apps/backend/modules/intake/adapters/ai_gateway.py` - the `AiGateway` protocol and DTOs the pipeline calls (`TranscribeRequest`, `StructureResult`, `AiEgressContext`) to know which imports move with the pipeline (~1.5K tokens)
3. `apps/backend/modules/intake/domain/events.py` - the payload types/envelope builders the pipeline emits (`intake_retry_requested_envelope`, `pre_summary_ready_envelope`, `ai_job_completed_envelope`, etc.) so the moved functions keep their imports (~1.5K tokens)
4. Prior art seam: `apps/backend/modules/partner/adapters/__init__.py` - how another module keeps its composition root thin while handlers live elsewhere (~0.5K tokens)

## Do NOT read

- `facade.py`, `routes.py`, `media_store.py`, `budget_meter.py`
- Frontend sources, `docs/archive/`
- Test internals beyond running the suite

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- `npm run lint`
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` passes unchanged
- `npm run typecheck` clean
- `npm run lint` clean
- `adapters/__init__.py` is â‰¤ 120 lines

## Handoff notes

- Pure extraction - do not fix behavioral bugs or refactor logic while moving it; that belongs to their own tickets.
- T03 (#367), T05 (#369), T06 (#370) all block on this ticket and will edit the extracted `pipeline.py` / thin `__init__.py`, so keep the split names and placement predictable: pipeline functions in `pipeline.py`, handler registration + constants in `__init__.py`.
- Keep `register_handlers`, `_on_intake_captured`, `_on_intake_retry_requested` and the pipeline constants (`MOCK_AI_MODEL`, `DEFAULT_EGRESS_*`, `AI_EGRESS_*`) where the pipeline imports don't create a cycle.
