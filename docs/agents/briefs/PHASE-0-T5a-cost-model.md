# Brief - PHASE-0 T5a Cost model + spike report

**Ticket:** #12 · **Parent:** #2 · **Refreshed:** 2026-08-10
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The cost model and spike report for the Phase 0 decision record: aggregate per-intake INR/token costs from all provider runs, extrapolate to KPI-001 volume (~200 intakes + ~200 rx-drafts/month, ~600 AI calls), and verify the launch-phase constraints - AI slice <= INR 600/month at KPI-001 volume, >= 3x headroom, per-intake <= INR 2.00, rx-draft <= INR 1.00. Emit the spike report (metrics, provider selection, AMB-006 threshold, go/no-go verdict applied mechanically).

Acceptance criteria:

- [ ] Per-intake cost computed per provider from real token usage + prices
- [ ] Extrapolation to KPI-001 volume (~200 intakes + ~200 rx-drafts/month)
- [ ] Launch constraints verified: INR 600/month AI slice, >= 3x headroom, per-intake <= INR 2.00, rx-draft <= INR 1.00 - breaches reported with reasons
- [ ] Spike report emitted with all required metrics, provider selection, and go/no-go verdict
- [ ] Go/no-go rule applied mechanically (all five bar items hold -> GO; transcription floor fails -> NO-GO with text-first fallback; structuring/calibration fails while transcription passes -> threshold-tune)

## Read-list (in order)

1. `phase0/harness/models.py` - `Usage` (73-83), `RunReport` (197+), `totals_usage` (226).
2. `phase0/harness/providers/gemini.py` - `GeminiPricing` (63-76) as the pricing-shape reference.
3. `phase0/runs/` - the recorded run JSONs (per-provider token + INR usage).
4. `docs/roadmap/implementation-roadmap.md` PHASE-0 section - the cost model and go/no-go rule.
5. `docs/prd/project-prd.md` - `NFR-001` and `KPI-001` sections (the extrapolation denominators and ceilings).

## Do NOT read

- `phase0/corpus/audio/` (binary WAVs)
- `docs/archive/`
- Provider adapter internals beyond their pricing

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria → commands)

- A cost-model unit test (synthetic usage totals -> extrapolation -> ceiling verdicts) - passes
- `npm run test:unit:backend` - full suite green
- `npm run typecheck` · `npm run lint` - clean

## Handoff notes

- Costs come from recorded tokens + price, never eyeballed - a breach must be reported with its reason, not papered over.
- Gemini per-intake is 1 call (multimodal finding); Whisper/NIM are 2 - the cost ceilings are per-intake, not per-call.
- The go/no-go rule is mechanical: transcribe floor fail -> NO-GO (text-first intake); structuring/calibration fail while transcription passes -> threshold-tune.
- The spike report feeds #13 (ADR-0001); keep the numbers exact, they are being recorded as decisions.
