# Brief — PHASE-0 T4c Three-provider comparison table

**Ticket:** #11 · **Parent:** #2 · **Refreshed:** 2026-08-10
**Reading surface:** ~3.5K tokens (budget 10K) — within budget

## Scope

The apples-to-apples comparison: run Gemini, Whisper, and NIM through the same harness on the same corpus and the same five-number bar, and emit a comparison table — transcription quality, structuring accuracy, flag calibration, per-intake cost per provider — generated from the recorded run JSONs, never eyeballed.

Acceptance criteria:

- [ ] Comparison table emitted covering all three providers: transcription quality, structuring accuracy, flag calibration, per-intake cost
- [ ] All three providers scored on the same corpus with the same metrics
- [ ] Table generated from recorded run JSONs under `phase0/runs/`
- [ ] NIM production-licensing caveat surfaced in the comparison output

## Read-list (in order)

1. `phase0/harness/models.py` — `RunReport` (197+), `TranscriptionSummary`, `StructuringSummary`, `CalibrationReport`, `totals_usage` (226).
2. `phase0/harness/runner.py` — `report_to_json` (325) and `_structuring_to_json`/`_calibration_to_json` (366/396) — the exact run-JSON shape.
3. `phase0/runs/` — the run outputs already recorded (gemini runs; whisper/nim runs once #9/#10 land).
4. `phase0/field_set/field_set.md` — the provisional field set the metrics read against.
5. `docs/roadmap/implementation-roadmap.md` PHASE-0 section (the five-number bar).
6. `docs/architecture/internal-modules.md` MOD-005 — the AI gateway seam this harness mirrors.

## Do NOT read

- `phase0/corpus/audio/` (binary WAVs)
- `docs/archive/`
- Provider adapter internals beyond the run JSONs they emit

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria → commands)

- A comparison-table unit test feeding synthetic `RunReport` JSONs — passes
- `npm run test:unit:backend` — full suite green
- `npm run typecheck` · `npm run lint` — clean

## Handoff notes

- Do not re-score from raw transcripts; the table aggregates `phase0/runs/*.json`. If a provider has no run yet, that cell is explicit "no data", not a guess.
- Per-intake cost restates the per-call ceilings: Gemini may be 1 call/intake (multimodal finding), Whisper/NIM 2 calls — keep the table's cost column per-intake per the spec.
- Throwaway PHASE-0 code: emit the table as part of the harness tooling, no production wiring.
