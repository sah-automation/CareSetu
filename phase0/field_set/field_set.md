# Provisional Phase 7 Pre-Summary Field Set — v1.0.0

> Status: **provisional**. Versioned at `phase0/field_set/field_set.json` (machine-readable) and this file (human-readable). This set is seeded from what the Phase 0 corpus actually contains and the PRD `FEAT-007` pre-summary concept. The schema is finalized at PHASE-7.

## Version

| Field               | Value                           |
| ------------------- | ------------------------------- |
| `field_set_version` | `1.0.0`                         |
| Created             | Phase 0 spike (Issue #3)        |
| Authors             | John (author) / Sonu (reviewer) |
| Status              | provisional                     |

## Scope & rules

- One pre-summary JSON file per clip, placed at `phase0/corpus/pre_summaries/<clip_id>.json`.
- The pre-summary records **only what is said in the clip's recording/transcript**. Unstated fields are `null` (string fields) or `[]` (array fields). Never fill a field from outside knowledge.
- The corpus is **PHI-free**: no name, address, phone, or other identifier fields exist. Do not add any.
- `clinical_notes` and `extraction_notes` are always populated — they capture context and structuring confidence and are the seed for the Phase 7 `low_confidence` semantics (`AMB-006`).

## Field reference

| Field                  | Type           | Notes                                                                          |
| ---------------------- | -------------- | ------------------------------------------------------------------------------ |
| `clip_id`              | string         | Must match `manifest.json`                                                     |
| `cohort`               | enum           | `urban_hindi` / `peri_urban` / `heavy_local`                                   |
| `field_set_version`    | string         | The version used to author this file                                           |
| `chief_complaint`      | string \| null | Primary presenting complaint                                                   |
| `onset`                | string \| null | When it started                                                                |
| `duration`             | string \| null | How long it has lasted                                                         |
| `location`             | string \| null | Body region                                                                    |
| `severity`             | string \| null | Intensity as stated/inferred                                                   |
| `nature`               | string \| null | Character (burning, dull, intermittent…)                                       |
| `associated_symptoms`  | string[]       | Other symptoms                                                                 |
| `aggravating_factors`  | string[]       | Worsening factors                                                              |
| `relieving_factors`    | string[]       | Relieving factors                                                              |
| `known_medications`    | object[]       | `{name, strength, frequency, route, duration, note}`                           |
| `allergies`            | string[]       | Known allergies                                                                |
| `past_history`         | string[]       | Patient's own chronic conditions/treatments                                    |
| `family_history`       | string[]       | Family medical history                                                         |
| `vitals`               | object         | `{temperature, blood_pressure, pulse, spo2, height_cm, weight_kg, bmi, other}` |
| `labs_ordered`         | string[]       | Investigations ordered                                                         |
| `diagnosis_impression` | string \| null | Doctor's stated diagnosis/impression                                           |
| `advice`               | string[]       | Instructions given                                                             |
| `follow_up`            | string \| null | Follow-up plan                                                                 |
| `clinical_notes`       | string         | Free-text clinical context                                                     |
| `extraction_notes`     | string         | Structuring confidence + gaps                                                  |

## Example

```json
{
  "clip_id": "sample_0023",
  "cohort": "urban_hindi",
  "field_set_version": "1.0.0",
  "chief_complaint": "fever with cold and whole body pain",
  "onset": "recurred after Calpol relief",
  "duration": null,
  "location": "whole body",
  "severity": "significant body pain",
  "nature": "recurrent fever",
  "associated_symptoms": ["cold", "whole body pain"],
  "aggravating_factors": [],
  "relieving_factors": ["Calpol (partial, transient)"],
  "known_medications": [
    {
      "name": "Calpol",
      "strength": null,
      "frequency": null,
      "route": "oral",
      "duration": null,
      "note": "took earlier, partial relief"
    }
  ],
  "allergies": [],
  "past_history": [],
  "family_history": ["brother had viral fever one week ago"],
  "vitals": {
    "temperature": null,
    "blood_pressure": null,
    "pulse": null,
    "spo2": null,
    "height_cm": null,
    "weight_kg": null,
    "bmi": null,
    "other": []
  },
  "labs_ordered": [],
  "diagnosis_impression": null,
  "advice": [],
  "follow_up": null,
  "clinical_notes": "Dialogue: patient reports fever; doctor asks about onset/exposure.",
  "extraction_notes": "Chief complaint and exposure clearly stated; onset partially captured."
}
```
