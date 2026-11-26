# ADR-0013: Voice-first symptom intake override of Phase 0 NO-GO

**Status:** accepted
**Date:** 2026-09-08
**Decides:** Overrides the Phase 0 Hindi-ASR NO-GO verdict for voice-first intake (`RISK-EVAL-006`, `PHASE-0` spike report).
**Traceability:** `FEAT-006`, `FEAT-007`, `MOD-005`, `NFR-001`, `NFR-SEC-006`.
**Evidence:** Phase 0 spike report `phase0/SPIKE_REPORT.md`; Phase 7 prototype voice/text intake screens (repo).

## Context

The Phase 0 Hindi-ASR spike returned a NO-GO verdict for voice-first intake on the freemium low-cost tier: median WER 0.181 and p90 WER 0.429 against a 0.20/0.35 bar on 12/43 clips. The spike conclusion was text-first intake with voice as an upload-for-doctor artifact (ADR-0001, consequences section).

The Phase 7 spec (issue #344) deliberately overrides this baseline. The user population is primarily a speaking-first demographic where Hindi/English voice intake materially improves accessibility and completion rates. A text-first default on a mobile web connection in Daltonganj introduces unnecessary friction for the majority of patients.

## Decision

**Voice is the default-highlighted primary input; text is equal-first-class.** The override is conditional on three structural safeguards that make the voice failure path non-blocking:

### 1. B3 deterministic fallback ladder

Voice attempts are hard-capped at 3 with deterministic escalation to forced text:

```
Voice attempt 1
  -> poor/short audio -> re-record prompt (attempt 2)
  -> audio still poor -> re-record prompt (attempt 3)
  -> audio still poor -> forced text path (patient types; intake finishes as text)
```

- Total voice attempts: **3** (server-side enforced, never client-side only).
- Audio floor: **3 seconds** below which audio is treated as "too short/unclear".
- Audio ceiling: **180 seconds** (3 minutes).
- Text cap: **2000 characters**.
- The forced-text transition is a legitimate intake path, not an error state; the doctor receives the raw transcript and audio for review.

### 2. Structural safety net

- Intake capture is saved **before any AI runs**; AI failure never rolls back patient input.
- A consent gate (`check_consent`) blocks every LLM egress; no-live-grant degrades to raw review.
- The budget meter observes spend against the `NFR-001` cap and is advisory (PS-10, #408): exhaustion is logged/reportable only and never blocks intake - the pipeline proceeds observe-and-warn, deviating from spec #344's original hard-stop wording.
- The doctor can always review raw transcript + audio regardless of AI pipeline state.

### 3. ASR-improvement plan (near-term)

The override is paired with a deliberate plan to improve ASR quality:

- **Better model:** evaluate a higher-tier ASR model (or fine-tuned variant) against the Phase 0 spike corpus under the same WER/CER harness.
- **Further training:** a future spike scope for targeted Hindi/English code-switching fine-tuning under realistic field conditions (4G, background noise, mixed dialects).
- **Re-evaluation:** re-run the Phase 0 spike harness after each improvement; the 0.20/0.35 WER/CER bar remains the certification metric.
- The spike harness and methodology are preserved in `phase0/` for reproducibility.

## Consequences

- Voice-first is the default UX, but text is never demoted below equal-first-class; both paths are always one tap/click away.
- The 3-attempt cap and forced-text escalation are validated server-side; a future client cannot bypass them.
- ADR-0001's AMB-006 threshold (0.70 structuring confidence, `low_confidence` flag) still applies: low-confidence pre-summaries force doctor review regardless of intake mode.
- The B3 ladder is a documented behavioral contract for the `MOD-005` intake state machine (transitions: `Re-record -> Structuring` on retry, `Re-record -> forced text` on exhaustion).
- The Phase 0 spike numbers are a historical baseline, not a current verdict; the override is a deliberate product decision with explicit structural mitigations, not an aspiration.
