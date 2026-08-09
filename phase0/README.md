# Phase 0 — Hindi Voice Reference Corpus & Ground Truth

Reference corpus for the Phase 0 Hindi Voice Feasibility Spike (issues #2 / #3): committed, reproducible fixtures used to measure ASR transcription quality and Hindi structuring accuracy before any production LLM spend.

## Contents

```
phase0/
├── README.md                        # this file — format, schema, provenance
├── REVIEW_LEDGER.md                 # John (author) / Sonu (reviewer) double-author record
├── PHI_SCAN.md                      # PHI scan method, results, exclusions
├── field_set/
│   ├── field_set.json               # provisional Phase 7 pre-summary field set, v1.0.0
│   └── field_set.md                 # human-readable field reference
├── loader.py                        # load_corpus() — one-call fixture loader (stdlib only)
└── corpus/
    ├── manifest.json                # clip manifest (cohort, paths, duration, word count)
    ├── audio/                       # 43 .wav clips (16 kHz mono)
    ├── transcripts/                 # 43 verbatim transcripts (UTF-8 Devanagari)
    └── pre_summaries/               # 43 reference structured pre-summaries (.json)
```

## Corpus summary

| Metric       | Value                                                                |
| ------------ | -------------------------------------------------------------------- |
| Total clips  | 43                                                                   |
| Cohorts      | `urban_hindi` (15), `peri_urban` (11), `heavy_local` (17)            |
| Total audio  | ~756 s (~12.6 min; ~4.2 min per cohort)                              |
| Audio format | WAV, 16 kHz, 16-bit, mono                                            |
| Transcripts  | Verbatim, UTF-8 Devanagari (roman/English words kept as spoken)      |
| Field set    | `1.0.0` (provisional)                                                |
| Ground truth | John (author) + Sonu (independent reviewer) — see `REVIEW_LEDGER.md` |

## Cohort definitions

Cohort tags are assigned by a **deterministic transcript heuristic**, documented here for reproducibility:

- **`urban_hindi`** — transcripts with heavy English code-mixing (≥ 20% Latin-script tokens). Typically educated city speech.
- **`peri_urban`** — light code-mixing (5–19% Latin-script tokens). Town / semi-urban register.
- **`heavy_local`** — near-pure Hindi (≤ 4% Latin-script tokens). Most colloquial register in the corpus.

A Latin-script token is any space-separated word that is fully ASCII (e.g. `fever`, `Okay`, `OFC`). The ratio is `ASCII words / total words` per transcript. The tag for each clip is stored in `manifest.json`.

> **Caveat (see also "Provenance"):** these tags are speech-register proxies derived from transcript code-mixing, **not** verified Daltonganj dialect groupings. They let the spike measure quality across a realistic register spectrum, but should be re-validated when locally recorded Daltonganj cohorts are available.

## Load in one call

The whole corpus + ground truth loads in a single call (Python 3.11+, stdlib only):

```python
from phase0.loader import load_corpus, scan_phi

corpus = load_corpus()          # field set + manifest + all pre-summaries
print(corpus.field_set.version) # "1.0.0"
print(len(corpus.clips))        # 43

for clip, summary in zip(corpus.clips, corpus.pre_summaries):
    assert clip.clip_id == summary.clip_id
    assert clip.cohort == summary.cohort

findings = scan_phi(corpus)     # heuristic PHI guard; 0 expected
```

The unit test `tests/unit/test_corpus_fixtures.py` asserts exactly this contract and runs via `npm run test:unit:backend`.

## Schema

### `manifest.json`

```json
{
  "manifest_version": "1.0.0",
  "field_set_version": "1.0.0",
  "total_clips": 43,
  "cohort_counts": { "urban_hindi": 15, "peri_urban": 11, "heavy_local": 17 },
  "total_duration_seconds": 756.1,
  "clips": [
    {
      "clip_id": "sample_0002",
      "cohort": "urban_hindi",
      "audio_path": "corpus/audio/sample_0002.wav",
      "transcript_path": "corpus/transcripts/sample_0002.txt",
      "pre_summary_path": "corpus/pre_summaries/sample_0002.json",
      "duration_s": 20.7,
      "word_count": 59
    }
  ]
}
```

### Transcripts (`corpus/transcripts/<clip_id>.txt`)

Verbatim Devanagari text with English words preserved as spoken (code-mixed). One file per clip.

### Pre-summaries (`corpus/pre_summaries/<clip_id>.json`)

Reference structured pre-summary against the field set. **Only what is spoken in the clip** is recorded: unstated string fields are `null`, unstated list fields are `[]`. Never filled from outside knowledge. See `field_set/field_set.md` for the full field reference and an example.

## Provenance & caveats

- **Source:** the raw audio dump in the repo's (gitignored) `audio/` directory is the **EKA Medical Dataset** — an external public corpus of Hindi doctor–patient medical dialogue (including drug-information readings). It is **not** audio recorded locally in/around Daltonganj.
- **Selection:** 43 of ~310 clips were selected as genuine, PHI-free **consultations** (drug-description readings, demo outtakes, truncated clips, and clips containing personal names were excluded — see `PHI_SCAN.md`).
- **Ticket status:** Issue #3's corpus/ground-truth work is complete on this subset, but the "recorded in/around Daltonganj across three dialect cohorts" requirement is **only approximated** by transcript-based cohort proxies. A locally recorded Daltonganj cohort set should supplement/replace this proxy corpus before Phase 7 (per issue #2: vendor sample sets may supplement but must not substitute).
- **PHI:** selected subset is PHI-free per automated + human review (`PHI_SCAN.md`). No identifier fields exist in the field set.

## Ground-truth quality process

- Every transcript and pre-summary was authored by **John** and independently reviewed by **Sonu**; the per-clip record is in `REVIEW_LEDGER.md`. This satisfies the double-authoring criterion for this research corpus.
