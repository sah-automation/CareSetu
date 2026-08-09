"""Phase 0 harness — transcription metrics (issue #4).

The transcription leg of the acceptance bar, computed with jiwer (the
standard metric library): WER is the primary metric, CER the fallback where
Devanagari word-splitting is unreliable. Aggregates are median + p90 per
cohort and overall (nearest-rank percentile), matching the Phase 0 spec:
WER median <= 20% and p90 <= 35%.

Throwaway research code for PHASE-0 (issue #2 / #4); not production.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

import jiwer

from phase0.harness.models import TranscriptionSummary
from phase0.loader import COHORTS

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
