# Phase 0 Corpus — PHI Scan

## Goal

The committed corpus must be **PHI-free** (Issue #3 acceptance criterion): recordings are scripted/externally-sourced dialogue with no patient identifiers, and the ground truth adds no identifier fields.

## Method (two layers)

1. **Automated heuristic scan** — `phase0/loader.py::scan_phi()` runs over every selected transcript:
   - Indian mobile phone numbers (`+91` / `0` / 10-digit `[6-9]…`)
   - Email addresses
   - Hindi name cues: `मेरा नाम`, `नाम <word>`
   - Honorific + Latin name: `डॉक्टर <Name>`, `Dr. <Name>`
2. **Human read-through** — John and Sonu read every selected transcript in full during the review pass (see `REVIEW_LEDGER.md`) and looked for proper names, addresses, phone numbers, and other identifiers.

## Result on the committed 43 clips

**Automated scan: 0 findings.** Human review: **0 identifiers found** in the selected corpus.

## Clips excluded from the corpus for PHI / content reasons

These clips were present in the raw `audio/` dump but are **not** part of the committed corpus:

| clip_id                 | Reason                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------- |
| sample_0024             | PHI — contains a doctor's name ("Doctor Santosh")                                     |
| sample_0055             | PHI — contains a staff member's name ("राजेश")                                        |
| sample_0088             | PHI — contains a person's name ("भास्कर सर")                                          |
| sample_0125             | PHI — contains a staff member's name ("राजेश")                                        |
| sample_0111             | Not a consultation — English demo/outtake narration                                   |
| sample_0062             | Not a consultation — roleplay setup narration ("you be the doctor, I am the patient") |
| sample_0039             | Missing audio file                                                                    |
| sample_0079             | Missing audio file                                                                    |
| sample_0103             | Missing audio file                                                                    |
| sample_0299             | Missing audio file                                                                    |
| sample_0000, 0063, 0114 | Too short / truncated (< 20 words) for a usable pre-summary                           |

## Caveats

- The heuristic scan is a best-effort first-pass guard, not a proof. Hindi proper names are hard to detect automatically; the human read-through is the authoritative check.
- The corpus provenance is an external public dataset (see `README.md`); the PHI-free claim applies to the **selected, reviewed subset only** and is based on transcript content (the audio itself was not human-transcribed by the team beyond these transcripts).
