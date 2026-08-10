# ADR-0001: AMB-006 resolution - confidence split, 0.70 threshold, and the forced-doctor-review gate

**Status:** accepted
**Date:** 2026-08-10
**Decides:** `AMB-006` (PRD §7.1) and `RISK-EVAL-006` - the structured-extraction accuracy threshold and the low-confidence fallback.
**Traceability:** `FEAT-007`, `FEAT-009`, `MOD-005`, `NFR-PERF-003`, `NFR-SEC-006`, `REQ-023`, `CFL-002`.
**Evidence:** Phase 0 spike report `phase0/SPIKE_REPORT.md` (generated 2026-08-10 from recorded run JSONs, never eyeballed).

## Context

`AMB-006` was left open at baseline: "flag below-confidence results; never present as verified" (PRD §7.1, `FEAT-007` Rule 2). `RISK-EVAL-006` required a Phase 0 spike to decide whether a freemium `EXT-002` tier can transcribe and structure Hindi voice intake well enough for doctor-reviewed pre-summaries within the `NFR-001` budget. The spike's measured verdict is **NO-GO: text-first intake fallback** (see §Evidence), which the decision below feeds into `PHASE-7`/`PHASE-8` as the closed semantics for the threshold and the usage gate.

## Decision

1. **Confidence is split into two independent measures.** The pipeline is `transcribe → structure → pre-summary`; the two legs are never merged into one confidence number.
   - **Transcription confidence** is a _measured_ audio→transcript quality, scored as WER/CER per cohort and overall. A clip is scoreable for structuring only when its WER ≤ `TRANSCRIPTION_FLOOR_WER` (0.20); this defines the _well-formed subset_ so extraction is not punished for ASR garbage-in.
   - **Structuring confidence** is the provider _self-reported_ `structuring_confidence` on the transcript→structured-fields leg, recorded alongside the field-set object. It is deliberately independent of the measured field-level F1 so the calibration is not circular.
2. **Threshold is a pinned constant: 0.70.** Structuring confidence strictly below `AMB_006_THRESHOLD` (0.70) sets the `low_confidence` flag; a missing/unknown confidence is treated as flagged ("never present unverified output as final").
3. **`low_confidence` is a quality gate, not a fourth lifecycle state.** The pre-summary machine stays three states - `[Draft] → [Reviewed] → [Final]` - with low confidence forcing `[Review required]`, never adding a state.
4. **Forced doctor review is a hard usage gate.** A `low_confidence` pre-summary is unusable as `rx_draft`/`consult` input until `mark_reviewed` records a timestamped, attributed doctor review. The harness proves the state machine with a synthetic reviewer; production records the actual doctor. This is the `CFL-002` baseline - a compliance decision, not a code shortcut.
5. **Silent-error certification bound.** Over the well-formed subset, a silent error is a clinically-significant field error (chief complaint, severity, medications, allergies, vitals, labs, diagnosis, advice, follow-up) on an _unflagged_ pre-summary. The bound is ≤ 2% silent-error rate on unflagged items, certified with flag precision/recall vs. measured accuracy. With no unflagged pre-summaries the bound has no evidence, so the verdict is FAIL as _unproven_ - never a vacuous pass.

## Consequences

- `PHASE-7` implements `pre_summary.low_confidence` exactly as a gate, not a state; `PHASE-8` blocks `rx_draft`/`consult` on `low_confidence` until an attributed review clears it.
- The 0.70 threshold and 0.20 floor are pinned constants in the `MOD-005` design; changing them is a new decision, not a config tweak.
- Because the spike returned NO-GO for voice-first transcription, the text-first intake path with voice as an upload-for-doctor artifact is the launch baseline; the gate semantics above are the fallback when voice is re-attempted.
- Spike numbers are recorded, not re-measured: transcription bar FAIL (median/p90 WER 0.181/0.429 vs. the 0.20/0.35 bar on 12/43 clips; bar targets per `phase0/README.md` §Evaluation harness), per-intake INR 0.0243 for gemini (gemini-2.5-flash), AMB-006 calibration **unverified** in the recorded run (no calibration section - never a vacuous pass).
