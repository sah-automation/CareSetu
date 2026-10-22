# Brief - 699 B1 - Real AI pricing table (fix cost = 0)

**Ticket:** #699 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Fix AI cost being silently zero. Populate the intake `PRICING_TABLE` with real per-model input/output rates (in paise), sourced from Settings/env, so `compute_cost_paise` returns real values for known models. Free models price at 0 naturally; an unknown model prices at 0 and is flagged (logged and/or surfaced) so a missing price is visible rather than hidden. `budget_meter.py` then has a real signal.

### Acceptance criteria

- [ ] `PRICING_TABLE` holds per-model input/output rates and is populated from config, not hardcoded empty.
- [ ] `compute_cost_paise` returns correct paise for a known model and 0 for an unknown one.
- [ ] An unknown model is flagged (not silently zero); a unit test covers both branches.
- [ ] `budget_meter` observes non-zero spend for a known model.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. `modules.intake.pricing` - `PRICING_TABLE`, `ModelPrice` (frozen `Decimal` paise-per-token pair), `compute_cost_paise(model, *, input_tokens, output_tokens)`. Read the module docstring: free and unknown both currently return 0 by absence of an entry, and the table is "deliberately empty at launch ... shipping a real paid model's price is deployment configuration, never hardcoded", pointing at Settings/env. (~0.6K tokens)
2. `app.config.Settings` - the AI block (`ai_provider`, `ai_model`, `ai_asr_model`, `ai_monthly_budget_paise` and its `DEFAULT_*` constant / `_env_int` parsing) plus `__post_init__` validation style. This is the precedent for the new rate source; the model names and their rates are deployment config, so they belong here (or in a sibling parser `get_settings()` can build). (~1K tokens)
3. `modules.intake.budget_meter.BudgetMeter.meter` / `read_spend_paise` - the `COALESCE(SUM(cost_paise), 0)` over `intake_ai_jobs` for the calendar month. This is what turns non-zero once pricing is real; confirm the contract it expects. (~1K tokens)
4. The pipeline's single cost write: `_complete_ai_job` (and `_finalize_pipeline` which calls it) in `modules.intake.adapters.pipeline` - the only caller of `compute_cost_paise`, using the effective serving `provider`/`model`. (~0.5K tokens)
5. The parent plan's §6 "AI cost, quality & pricing" - "Populate pricing from Settings/env (per model input/output rates in paise); free models price at 0 naturally; unknown models price at 0 and are flagged." (~0.4K tokens)

## Do NOT read

- Any module other than `intake` and `app.config`.
- The frontend.
- Migrations (B1 is migration-free).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (current tree)
- `npm run test:unit:backend` - PASS (2925 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- A pure-logic pricing unit test covering known (non-zero, correct paise for input+output), free (0, no flag), and unknown (0, flag raised) branches.
- A budget-meter test proving spend is non-zero for a known model once a priced `intake_ai_jobs` row exists.

## Handoff notes

- The detailed, launch-pricing formula is already fixed in `pricing.py` (`input_tokens*price_in + output_tokens*price_out`, half-up to integer paise); do not change the formula, only the table's source.
- `_complete_ai_job` imports `compute_cost_paise` at module import, so a config-derived table must be resolvable lazily (per call, or rebuilt from `get_settings()`) rather than frozen at import if Settings is env-driven. Keep the pure function unit-testable without a database.
- "Free" and "unknown" are distinguishable only if the config carries an explicit zero rate for free models; absent = unknown = flagged. Make the flag visible (structured log and/or a returned sentinel) without breaking the `int -> int` cost contract the column expects.
- Predecessor A5 (#693) adds the observability Settings gates; if it introduced a pricing/rate setting shape, conform to it rather than inventing a parallel one.
