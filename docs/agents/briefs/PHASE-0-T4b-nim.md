# Brief - PHASE-0 T4b NVIDIA NIM provider adapter

**Ticket:** #10 · **Parent:** #2 · **Refreshed:** 2026-08-10
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

An NVIDIA NIM adapter (multilingual ASR via `canary-1b-asr`, or a cheap catalog LLM for structuring) implementing the same provider-agnostic Gateway port as Gemini, selectable via `--provider nim`, scored on the same corpus with the same WER/CER + field-F1 + AMB-006 calibration path. Records the prototyping-only caveat (production requires NVIDIA AI Enterprise licensing).

Acceptance criteria:

- [ ] Implements the Gateway port (`name`, async `transcribe`, async `structure`) alongside Gemini
- [ ] Selectable via `--provider nim` in the harness CLI
- [ ] NIM transcription scored with the same WER/CER metric (well-formed floor WER <= 0.20)
- [ ] NIM structuring scored with the same field-F1 path and AMB-006 calibration (threshold 0.70)
- [ ] Production-licensing caveat recorded in the run output

## Read-list (in order)

1. `phase0/harness/gateway.py` (~30 lines) - the port: `Gateway` protocol, `transcribe(audio_path, clip_id) -> TranscribeResult`, `structure(transcript, clip_id) -> StructureResult`.
2. `phase0/harness/models.py` - `TranscribeResult`/`StructureResult`/`Usage` (~73–100); `PreSummaryData` field set (~41–68).
3. `phase0/harness/providers/gemini.py` - the reference adapter: `GeminiProvider` (183+), `_load_api_key` (92), `_model_from_env` (111), pricing + `parse_usage` (147). Follow its shape.
4. `phase0/harness/__main__.py` - CLI: `--provider` choices (96) + `_provider_from_cli` (32); register `"nim"`.
5. `tests/unit/test_phase0_gemini.py` - the deterministic mock-provider test pattern to copy.
6. `docs/roadmap/implementation-roadmap.md` PHASE-0 section (the five-number bar).
7. `docs/standards/third-party-integration-standards.md` - EXT-001..004 call discipline.

## Do NOT read

- `phase0/corpus/audio/` (binary WAVs)
- `docs/archive/`
- `phase0/harness/runner.py` internals beyond `RunReport`/`report_to_json`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria → commands)

- New `tests/unit/test_phase0_nim.py` mocking the provider - passes
- `npm run test:unit:backend` - full suite green
- `npm run typecheck` · `npm run lint` - clean
- Optional live smoke: `python -m phase0.harness --provider nim --limit 2`

## Handoff notes

- The licensing caveat ("prototyping only; production requires NVIDIA AI Enterprise") must be surfaced in the run output - the spec treats a free-tier NIM dependency as an accidental assumption if unrecorded.
- `Usage` requires `cost_inr` + `tier`; NIM is the zero-cost fallback candidate, but record real tokens and a zero/estimated INR honestly.
- Confidence is provider-self-reported in `structure` (`structuring_confidence` key); a missing confidence is treated as flagged - do not invent one.
- Throwaway PHASE-0 code: keep the adapter under `phase0/harness/providers/`, no production wiring.
