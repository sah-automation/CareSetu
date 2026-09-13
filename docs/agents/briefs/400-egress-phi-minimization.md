# Brief - 400 T03 Egress context PHI minimization + guardrail

**Ticket:** #400 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

No patient demographics (real or fake) reach the AI egress. Delete `DEFAULT_EGRESS_AGE_RANGE` / `DEFAULT_EGRESS_SEX`, drop `age_range`/`sex` from `AiEgressContext` (its structured model rejects unknown fields, so it is enforced structurally), update all construction sites, and add a guardrail test asserting the egress context admits exactly language + the content being processed. Acceptances: constants deleted; `AiEgressContext` has only language + content fields; no patient-identity field in any egress payload, prompt, or transcribe request; guardrail test passes.

## Read-list (in order)

1. `modules/intake/adapters/ai_gateway.py` - `AiEgressContext` (:53) definition; removing `age_range`/`sex` (~0.5K)
2. `modules/intake/adapters/__init__.py` - `DEFAULT_EGRESS_AGE_RANGE`/`DEFAULT_EGRESS_SEX` constants (:64-65) to delete; the AI egress constants that STAY (`AI_EGRESS_COUNTERPARTY_*`, `AI_EGRESS_RECORD_SCOPE`) (~1K)
3. `modules/intake/adapters/pipeline.py` - `_egress_context` (:87-98) and every construction site of the context (~1.5K)
4. Prior-art guardrail tests - `tests/unit/test_ai_gateway_*.py` for where a context-shape assertion belongs; `test_intake_pipeline_consumer.py` for prompt/request build assertions (~1K)

## Do NOT read

- `budget_meter.py`, `media_store.py`, `routes.py`
- The result-model/token fields - that is #398's edit in the same file's other classes
- Frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new guardrail test + existing pipeline/consumer tests still green
- `npm run typecheck:backend` clean

## Handoff notes

- `AiEgressContext` is a pydantic model; deleting the fields makes extra-key construction a structural error - that is the enforcement, so keep the model strict
- The decision (parent #397, decision #2): doctors see patient identity only in their own UI; AI egress stays anonymous by construction
- Touch only the context + its constants + construction sites; do not pull egress-disclosure logic into scope (that is #401 on the transcribe leg)
