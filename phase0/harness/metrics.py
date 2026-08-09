"""Phase 0 harness — transcription + structuring metrics (issues #4 / #5).

The transcription leg of the acceptance bar is computed with jiwer (the
standard metric library): WER is the primary metric, CER the fallback where
Devanagari word-splitting is unreliable. Aggregates are median + p90 per
cohort and overall (nearest-rank percentile), matching the Phase 0 spec:
WER median <= 20% and p90 <= 35%.

The structuring leg (issue #5) scores each well-formed clip's structured
pre-summary against the ground truth as field-level precision/recall/F1, and
implements the AMB-006 calibration: a ``low_confidence`` flag derived from
the provider's structuring confidence vs. the 0.70 threshold, with the
silent-error bound (<= 2% on unflagged pre-summaries) and flag
precision/recall reported.

Throwaway research code for PHASE-0 (issue #2 / #4 / #5); not production.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import jiwer

from phase0.harness.models import (
    CalibrationReport,
    FieldF1,
    FieldValue,
    PerClipStructuring,
    PreSummaryData,
    StructuringSummary,
    TranscriptionSummary,
)
from phase0.loader import COHORTS, PreSummary

# Devanagari danda/abbreviation sign plus common punctuation — all speech-neutral.
_PUNCTUATION_RE = re.compile(r"[।॥,;:!?\.…\u2019\u2018\"\u201c\u201d()\[\]{}\u2013\u2014-]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Canonicalize a transcript for scoring.

    Drops Devanagari and ASCII punctuation, lowercases Latin code-mixed words,
    and collapses whitespace so scoring splits cleanly on word boundaries.
    """
    cleaned = _PUNCTUATION_RE.sub(" ", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned.lower()


@dataclass(frozen=True)
class Score:
    clip_id: str
    wer: float
    cer: float


def compute_wer(reference: str, hypothesis: str) -> float:
    """Word error rate (0..1) via jiwer, after Devanagari-aware normalization."""
    reference = normalize_text(reference)
    hypothesis = normalize_text(hypothesis)
    if reference == "":
        return 0.0 if hypothesis == "" else 1.0
    return float(jiwer.wer(reference, hypothesis))


def compute_cer(reference: str, hypothesis: str) -> float:
    """Character error rate (0..1) via jiwer — the WER fallback."""
    reference = normalize_text(reference)
    hypothesis = normalize_text(hypothesis)
    if reference == "":
        return 0.0 if hypothesis == "" else 1.0
    return float(jiwer.cer(reference, hypothesis))


def score_clip(clip_id: str, reference: str, hypothesis: str) -> Score:
    return Score(
        clip_id=clip_id,
        wer=compute_wer(reference, hypothesis),
        cer=compute_cer(reference, hypothesis),
    )


@dataclass(frozen=True)
class AggregateScore:
    median: float | None
    p90: float | None
    sample_size: int


def percentile(values: Sequence[float], percent: int) -> float:
    """Nearest-rank percentile over a non-empty sequence."""
    if not values:
        raise ValueError("cannot compute percentile of an empty sequence")
    ordered = sorted(values)
    rank = min(math.ceil(percent / 100 * len(ordered)), len(ordered))
    return ordered[rank - 1]


def aggregate_wer(values: Sequence[float]) -> AggregateScore:
    if not values:
        return AggregateScore(median=None, p90=None, sample_size=0)
    return AggregateScore(
        median=statistics.median(values),
        p90=percentile(values, 90),
        sample_size=len(values),
    )


def summarize(wer_values: Sequence[float], cer_values: Sequence[float]) -> TranscriptionSummary:
    """Build a TranscriptionSummary for one cohort or the whole run."""
    if not wer_values:
        return TranscriptionSummary(None, None, None, None, 0)
    return TranscriptionSummary(
        median_wer=statistics.median(wer_values),
        p90_wer=percentile(wer_values, 90),
        median_cer=statistics.median(cer_values),
        p90_cer=percentile(cer_values, 90),
        sample_size=len(wer_values),
    )


WER_MEDIAN_CEILING = 0.20
WER_P90_CEILING = 0.35


def evaluate_transcription_bar(
    overall: TranscriptionSummary,
    per_cohort: dict[str, TranscriptionSummary],
) -> tuple[bool, list[str]]:
    """Apply the Phase 0 transcription bar: median <= 20%, p90 <= 35%.

    Every one of the three dialect cohorts AND the overall figures must pass;
    a missing (unscored) cohort is itself a failure.
    """
    failures: list[str] = []
    for cohort in sorted(COHORTS):
        summary = per_cohort.get(cohort)
        if summary is None or summary.sample_size == 0:
            failures.append(f"cohort {cohort}: not scored")
            continue
        if summary.median_wer is None or summary.median_wer > WER_MEDIAN_CEILING:
            failures.append(
                f"cohort {cohort}: median WER {summary.median_wer} > {WER_MEDIAN_CEILING}"
            )
        if summary.p90_wer is None or summary.p90_wer > WER_P90_CEILING:
            failures.append(f"cohort {cohort}: p90 WER {summary.p90_wer} > {WER_P90_CEILING}")

    if overall.sample_size == 0:
        failures.append("overall: not scored")
    else:
        if overall.median_wer is None or overall.median_wer > WER_MEDIAN_CEILING:
            failures.append(f"overall: median WER {overall.median_wer} > {WER_MEDIAN_CEILING}")
        if overall.p90_wer is None or overall.p90_wer > WER_P90_CEILING:
            failures.append(f"overall: p90 WER {overall.p90_wer} > {WER_P90_CEILING}")

    return (not failures, failures)


# --- structuring leg (issue #5) ----------------------------------------------

# Per-clip transcription floor: a clip is "well-formed" (usable for structuring
# scoring) when its WER clears this threshold. The Phase 0 bar states WER
# median <= 20% / p90 <= 35%; the per-clip floor uses the median ceiling so the
# well-formed subset is exactly the clips the ASR step got right.
TRANSCRIPTION_FLOOR_WER = 0.20

# AMB-006 constant: one global structuring-confidence threshold. A
# pre-summary whose provider confidence is strictly below this is flagged
# "low confidence — verify" and gated on doctor review.
AMB_006_THRESHOLD = 0.70

STRUCTURING_F1_TARGET = 0.90
SILENT_ERROR_RATE_CEILING = 0.02

# Fields excluded from F1 scoring: metadata and free-text notes are not
# extractions, so they neither help nor hurt the extraction bar.
_NON_EXTRACTIVE_FIELDS = frozenset(
    {"clip_id", "cohort", "field_set_version", "clinical_notes", "extraction_notes"}
)

# The subset of the field set whose wrong value could change clinical action.
# These fields drive the AMB-006 silent-error calibration; a pre-summary has a
# "clinically-significant error" when any of them is not an exact match.
CLINICALLY_SIGNIFICANT_FIELDS = frozenset(
    {
        "chief_complaint",
        "severity",
        "known_medications",
        "allergies",
        "vitals",
        "labs_ordered",
        "diagnosis_impression",
        "advice",
        "follow_up",
    }
)

_MED_SUBFIELDS = ("name", "strength", "frequency", "route", "duration", "note")
_VITALS_SUBFIELDS = (
    "temperature",
    "blood_pressure",
    "pulse",
    "spo2",
    "height_cm",
    "weight_kg",
    "bmi",
    "other",
)


def f1_scored_fields(field_names: Sequence[str]) -> tuple[str, ...]:
    """The extractive fields of the field set (metadata + notes excluded)."""
    return tuple(name for name in field_names if name not in _NON_EXTRACTIVE_FIELDS)


def is_well_formed(wer: float | None) -> bool:
    """A clip cleared the transcription floor (scoreable for structuring)."""
    return wer is not None and wer <= TRANSCRIPTION_FLOOR_WER


def low_confidence(confidence: float | None) -> bool:
    """The AMB-006 flag: fires when structuring confidence is below threshold.

    Unknown confidence (``None``) is treated as low — "never present
    unverified output as final" (FEAT-007 / AMB-006).
    """
    return confidence is None or confidence < AMB_006_THRESHOLD


def field_tokens(field_name: str, value: FieldValue) -> frozenset[str]:
    """Canonical token set for one field value, so both sides score the same.

    Scalars normalize to one token, lists to one token per item,
    ``known_medications`` to one token per medication (sub-fields joined), and
    ``vitals`` to one ``key=value`` token per non-null measurement — the
    ``other`` list contributes one ``other=...`` token per item, so ordering
    does not affect the score. Null / empty values canonicalize to the empty
    set.
    """
    if value is None:
        return frozenset()
    if field_name == "known_medications":
        if not isinstance(value, list):
            return frozenset()
        tokens: set[str] = set()
        for medication in value:
            if not isinstance(medication, dict):
                continue
            parts = [
                normalize_text(str(item_value))
                for sub_key, item_value in medication.items()
                if sub_key in _MED_SUBFIELDS and item_value is not None
            ]
            parts = [part for part in parts if part]
            if parts:
                tokens.add("|".join(parts))
        return frozenset(tokens)
    if field_name == "vitals":
        if not isinstance(value, dict):
            return frozenset()
        tokens = set()
        for key, item_value in value.items():
            if key not in _VITALS_SUBFIELDS or item_value is None:
                continue
            if key == "other":
                if isinstance(item_value, list):
                    tokens.update(
                        f"other={normalize_text(str(item))}"
                        for item in item_value
                        if normalize_text(str(item))
                    )
                continue
            normalized = normalize_text(str(item_value))
            if normalized:
                tokens.add(f"{key}={normalized}")
        return frozenset(tokens)
    if isinstance(value, list):
        return frozenset(normalize_text(str(item)) for item in value if normalize_text(str(item)))
    normalized = normalize_text(str(value))
    return frozenset({normalized}) if normalized else frozenset()


def _f1_from_counts(correct: int, reference: int, hypothesis: int) -> tuple[float, float, float]:
    """Precision/recall/F1 from aggregate token counts.

    Both empty is a perfect match; any spurious output when the reference is
    empty scores zero; any missing output when the reference is non-empty
    scores zero.
    """
    if reference == 0 and hypothesis == 0:
        return 1.0, 1.0, 1.0
    precision = correct / hypothesis if hypothesis else 0.0
    recall = correct / reference if reference else 0.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def score_field(field_name: str, reference: FieldValue, hypothesis: FieldValue) -> FieldF1:
    """Score one field of one clip against its ground truth."""
    ref_tokens = field_tokens(field_name, reference)
    hyp_tokens = field_tokens(field_name, hypothesis)
    correct = len(ref_tokens & hyp_tokens)
    precision, recall, f1 = _f1_from_counts(correct, len(ref_tokens), len(hyp_tokens))
    return FieldF1(
        field=field_name,
        correct=correct,
        reference=len(ref_tokens),
        hypothesis=len(hyp_tokens),
        precision=precision,
        recall=recall,
        f1=f1,
    )


def pre_summary_to_plain(summary: PreSummary) -> PreSummaryData:
    """Flatten a ground-truth PreSummary to the JSON layout the provider emits."""
    return {
        "chief_complaint": summary.chief_complaint,
        "onset": summary.onset,
        "duration": summary.duration,
        "location": summary.location,
        "severity": summary.severity,
        "nature": summary.nature,
        "associated_symptoms": list(summary.associated_symptoms),
        "aggravating_factors": list(summary.aggravating_factors),
        "relieving_factors": list(summary.relieving_factors),
        "known_medications": [
            {
                "name": medication.name,
                "strength": medication.strength,
                "frequency": medication.frequency,
                "route": medication.route,
                "duration": medication.duration,
                "note": medication.note,
            }
            for medication in summary.known_medications
        ],
        "allergies": list(summary.allergies),
        "past_history": list(summary.past_history),
        "family_history": list(summary.family_history),
        "vitals": {
            "temperature": summary.vitals.temperature,
            "blood_pressure": summary.vitals.blood_pressure,
            "pulse": summary.vitals.pulse,
            "spo2": summary.vitals.spo2,
            "height_cm": summary.vitals.height_cm,
            "weight_kg": summary.vitals.weight_kg,
            "bmi": summary.vitals.bmi,
            "other": list(summary.vitals.other),
        },
        "labs_ordered": list(summary.labs_ordered),
        "diagnosis_impression": summary.diagnosis_impression,
        "advice": list(summary.advice),
        "follow_up": summary.follow_up,
    }


def score_structuring(
    reference: PreSummaryData,
    hypothesis: PreSummaryData,
    fields: Sequence[str],
) -> dict[str, FieldF1]:
    """Field-level F1 for one pre-summary hypothesis vs. ground truth."""
    return {
        field: score_field(
            field,
            cast(FieldValue, reference.get(field)),
            cast(FieldValue, hypothesis.get(field)),
        )
        for field in fields
    }


def has_clinically_significant_error(scores: dict[str, FieldF1]) -> bool:
    """True when any clinically-significant field is not an exact match."""
    return any(scores[field].f1 < 1.0 for field in CLINICALLY_SIGNIFICANT_FIELDS if field in scores)


@dataclass(frozen=True)
class _TokenCounts:
    """Running correct/reference/hypothesis totals for micro-aggregation."""

    correct: int = 0
    reference: int = 0
    hypothesis: int = 0

    def __add__(self, other: _TokenCounts) -> _TokenCounts:
        return _TokenCounts(
            correct=self.correct + other.correct,
            reference=self.reference + other.reference,
            hypothesis=self.hypothesis + other.hypothesis,
        )


def aggregate_structuring(
    per_clip_scores: Sequence[dict[str, FieldF1]],
) -> StructuringSummary:
    """Micro-aggregate field-level F1 over the well-formed subset.

    Token counts are summed per field across clips; the overall row folds
    every field into one precision/recall/F1. Fields with no evidence on
    either side contribute nothing to the micro totals.
    """
    totals: dict[str, _TokenCounts] = {}
    for clip_scores in per_clip_scores:
        for field, score in clip_scores.items():
            counts = _TokenCounts(score.correct, score.reference, score.hypothesis)
            totals[field] = totals.get(field, _TokenCounts()) + counts

    per_field: dict[str, FieldF1] = {}
    for field in sorted(totals):
        counts = totals[field]
        precision, recall, f1 = _f1_from_counts(counts.correct, counts.reference, counts.hypothesis)
        per_field[field] = FieldF1(
            field=field,
            correct=counts.correct,
            reference=counts.reference,
            hypothesis=counts.hypothesis,
            precision=precision,
            recall=recall,
            f1=f1,
        )

    overall_counts = _TokenCounts()
    for counts in totals.values():
        overall_counts = overall_counts + counts
    precision, recall, f1 = _f1_from_counts(
        overall_counts.correct, overall_counts.reference, overall_counts.hypothesis
    )
    overall = FieldF1(
        field="overall",
        correct=overall_counts.correct,
        reference=overall_counts.reference,
        hypothesis=overall_counts.hypothesis,
        precision=precision,
        recall=recall,
        f1=f1,
    )
    return StructuringSummary(
        per_field=per_field, overall=overall, sample_size=len(per_clip_scores)
    )


def evaluate_structuring_bar(summary: StructuringSummary | None) -> tuple[bool, list[str]]:
    """Apply the structuring leg of the bar: field-level F1 >= 90%."""
    if summary is None or summary.sample_size == 0:
        return False, ["structuring: no well-formed clips scored"]
    failures: list[str] = []
    if summary.overall.f1 < STRUCTURING_F1_TARGET:
        failures.append(
            f"structuring: overall field F1 {summary.overall.f1} < {STRUCTURING_F1_TARGET}"
        )
    return (not failures, failures)


def calibrate(rows: Sequence[PerClipStructuring]) -> CalibrationReport:
    """AMB-006 calibration over the structured (well-formed) clips.

    Silent error = a clinically-significant field error on an unflagged
    pre-summary. Reports the silent-error rate on unflagged items, the
    acceptance verdict (<= 2%), and flag precision/recall vs. measured field
    accuracy so the 0.70 threshold can be tuned at PHASE-7.

    With no unflagged pre-summaries the silent-error bound has no evidence to
    certify — the verdict is FAIL as *unproven*, never a vacuous pass. Rows
    carrying an ``error`` (provider failures) are excluded by the caller
    before calibration.
    """
    flagged = [row for row in rows if row.low_confidence]
    unflagged = [row for row in rows if not row.low_confidence]
    significant = [row for row in rows if row.significant_error]
    flagged_significant = [row for row in flagged if row.significant_error]
    silent = [row for row in unflagged if row.significant_error]

    silent_error_rate = len(silent) / len(unflagged) if unflagged else None
    flag_precision = len(flagged_significant) / len(flagged) if flagged else None
    flag_recall = len(flagged_significant) / len(significant) if significant else None
    passes = silent_error_rate is not None and silent_error_rate <= SILENT_ERROR_RATE_CEILING

    return CalibrationReport(
        threshold=AMB_006_THRESHOLD,
        clips=len(rows),
        flagged=len(flagged),
        unflagged=len(unflagged),
        significant_errors=len(significant),
        flagged_significant=len(flagged_significant),
        silent_errors=len(silent),
        silent_error_rate=silent_error_rate,
        flag_precision=flag_precision,
        flag_recall=flag_recall,
        passes_silent_error_bar=passes,
    )
