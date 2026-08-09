"""Phase 0 harness — transcription metric tests (issue #4).

Covers the transcription leg of the acceptance bar: WER/CER via jiwer
(the standard metric library), Devanagari-aware text normalization, and
the median / p90 aggregation the bar is judged on. Deterministic by
construction — hand-computed expectations, no providers, no network.
"""

import statistics

import pytest

from phase0.harness.metrics import (
    aggregate_wer,
    compute_cer,
    compute_wer,
    evaluate_transcription_bar,
    normalize_text,
    percentile,
    score_clip,
)
from phase0.harness.models import TranscriptionSummary

# --- normalization --------------------------------------------------------


def test_normalize_removes_devanagari_danda() -> None:
    assert normalize_text("बुखार। और खांसी।") == "बुखार और खांसी"
    assert normalize_text("बुखार॥ खांसी") == "बुखार खांसी"


def test_normalize_lowercases_and_collapses_whitespace() -> None:
    assert normalize_text("  Fever\tऔर\nखांसी  ") == "fever और खांसी"


def test_normalize_removes_ascii_punctuation() -> None:
    assert normalize_text("दो दिन, से; (पेट दर्द)…") == "दो दिन से पेट दर्द"


# --- WER / CER -------------------------------------------------------------


def test_wer_perfect_match_is_zero() -> None:
    assert compute_wer("बुखार और खांसी", "बुखार और खांसी") == pytest.approx(0.0)


def test_wer_one_substitution_out_of_three_words() -> None:
    assert compute_wer("a b c", "a b d") == pytest.approx(1 / 3)


def test_wer_one_deletion_out_of_three_words() -> None:
    assert compute_wer("a b c", "a b") == pytest.approx(1 / 3)


def test_wer_empty_hypothesis_is_total_loss() -> None:
    assert compute_wer("a b c", "") == pytest.approx(1.0)


def test_wer_empty_reference_is_zero_only_when_hypothesis_empty() -> None:
    assert compute_wer("", "") == pytest.approx(0.0)
    assert compute_wer("", "a b") == pytest.approx(1.0)


def test_cer_perfect_match_is_zero() -> None:
    assert compute_cer("बुखार", "बुखार") == pytest.approx(0.0)


def test_cer_counts_character_errors() -> None:
    # "abcde" -> "axcde": one substitution out of five characters
    assert compute_cer("abcde", "axcde") == pytest.approx(1 / 5)


def test_danda_punctuation_does_not_count_as_word_error() -> None:
    # A danda difference is punctuation, not a spoken word.
    assert compute_wer("बुखार। और खांसी", "बुखार और खांसी") == pytest.approx(0.0)


def test_score_clip_records_wer_and_cer() -> None:
    score = score_clip("sample_0002", "a b c", "a b d")
    assert score.clip_id == "sample_0002"
    assert score.wer == pytest.approx(1 / 3)
    assert score.cer == pytest.approx(1 / 5)


# --- aggregation ------------------------------------------------------------


def test_percentile_uses_nearest_rank() -> None:
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    assert percentile(values, 50) == pytest.approx(0.5)
    assert percentile(values, 90) == pytest.approx(0.9)
    assert percentile([0.1], 90) == pytest.approx(0.1)


def test_aggregate_wer_median_and_p90() -> None:
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    aggregate = aggregate_wer(values)
    assert aggregate.median == pytest.approx(statistics.median(values))
    assert aggregate.p90 == pytest.approx(0.9)
    assert aggregate.sample_size == 10


def test_aggregate_wer_empty_returns_none_scores() -> None:
    aggregate = aggregate_wer([])
    assert aggregate.sample_size == 0
    assert aggregate.median is None
    assert aggregate.p90 is None


# --- acceptance bar -----------------------------------------------------------


def _summary(
    median_wer: float | None, p90_wer: float | None, sample_size: int
) -> TranscriptionSummary:
    return TranscriptionSummary(
        median_wer=median_wer,
        p90_wer=p90_wer,
        median_cer=None,
        p90_cer=None,
        sample_size=sample_size,
    )


def _all_cohorts(
    median_wer: float = 0.10, p90_wer: float = 0.20
) -> dict[str, TranscriptionSummary]:
    return {
        "urban_hindi": _summary(median_wer, p90_wer, 5),
        "peri_urban": _summary(median_wer, p90_wer, 5),
        "heavy_local": _summary(median_wer, p90_wer, 5),
    }


def test_bar_passes_when_within_limits() -> None:
    per_cohort = _all_cohorts()
    overall = _summary(0.12, 0.24, 5)
    passes, failures = evaluate_transcription_bar(overall, per_cohort)
    assert passes is True
    assert failures == []


def test_bar_fails_when_overall_p90_exceeds() -> None:
    per_cohort = _all_cohorts()
    passes, failures = evaluate_transcription_bar(_summary(0.12, 0.4, 5), per_cohort)
    assert passes is False
    assert any("overall" in failure for failure in failures)


def test_bar_fails_when_a_cohort_median_exceeds() -> None:
    per_cohort = _all_cohorts(median_wer=0.3, p90_wer=0.3)
    overall = _summary(0.12, 0.24, 5)
    passes, failures = evaluate_transcription_bar(overall, per_cohort)
    assert passes is False
    assert any("urban_hindi" in failure for failure in failures)


def test_bar_boundaries_are_inclusive() -> None:
    # Median exactly 20% and p90 exactly 35% are still a pass.
    per_cohort = _all_cohorts(median_wer=0.20, p90_wer=0.35)
    overall = _summary(0.20, 0.35, 5)
    passes, _failures = evaluate_transcription_bar(overall, per_cohort)
    assert passes is True


def test_bar_requires_all_three_cohorts_scored() -> None:
    overall = _summary(0.1, 0.2, 5)
    passes, failures = evaluate_transcription_bar(overall, {})
    assert passes is False
    assert len(failures) == 3
    assert all("cohort" in failure for failure in failures)
