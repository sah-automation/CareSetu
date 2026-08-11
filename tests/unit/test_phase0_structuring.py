"""Phase 0 harness - structuring metric + AMB-006 calibration tests (issue #5).

Covers the structuring leg of the acceptance bar: field-level precision /
recall / F1 against the ground-truth pre-summaries, the well-formed-subset
definition, the ``low_confidence`` flag at the 0.70 threshold, the
silent-error calibration (<= 2% on unflagged pre-summaries, with flag
precision/recall), and the structuring bar (F1 >= 90%). Deterministic by
construction - hand-computed expectations, no providers, no network.
"""

import pytest

from phase0.harness.metrics import (
    CLINICALLY_SIGNIFICANT_FIELDS,
    TRANSCRIPTION_FLOOR_WER,
    aggregate_structuring,
    calibrate,
    evaluate_structuring_bar,
    f1_scored_fields,
    field_tokens,
    has_clinically_significant_error,
    is_well_formed,
    low_confidence,
    pre_summary_to_plain,
    score_field,
    score_structuring,
)
from phase0.harness.models import (
    MedicationData,
    PerClipStructuring,
    PreSummaryData,
    StructuringSummary,
    VitalsData,
)
from phase0.loader import Corpus, PreSummary

# --- canonicalization --------------------------------------------------------


def test_field_tokens_normalizes_scalar() -> None:
    assert field_tokens("chief_complaint", "Chest X-ray pain") == frozenset({"chest x ray pain"})


def test_field_tokens_null_is_empty() -> None:
    assert field_tokens("onset", None) == frozenset()


def test_field_tokens_list_has_one_token_per_item() -> None:
    tokens = field_tokens("labs_ordered", ["CBC lab test", "chest X-ray"])
    assert tokens == frozenset({"cbc lab test", "chest x ray"})


def test_field_tokens_empty_list_is_empty() -> None:
    assert field_tokens("allergies", []) == frozenset()


def test_field_tokens_medication_flattens_subfields() -> None:
    medication: list[MedicationData] = [
        {"name": "Calpol", "strength": None, "frequency": "1-0-1", "route": "oral"}
    ]
    tokens = field_tokens("known_medications", medication)
    assert tokens == frozenset({"calpol|1 0 1|oral"})


def test_field_tokens_vitals_keeps_measured_keys_only() -> None:
    vitals: VitalsData = {
        "temperature": "98.6 F",
        "blood_pressure": None,
        "pulse": "72",
        "other": [],
    }
    tokens = field_tokens("vitals", vitals)
    assert tokens == frozenset({"temperature=98 6 f", "pulse=72"})


def test_field_tokens_vitals_other_is_order_independent() -> None:
    a: VitalsData = {"other": ["spo2 95", "weight 60 kg"]}
    b: VitalsData = {"other": ["weight 60 kg", "spo2 95"]}
    assert field_tokens("vitals", a) == field_tokens("vitals", b)
    assert field_tokens("vitals", a) == frozenset({"other=spo2 95", "other=weight 60 kg"})


# --- per-field scoring --------------------------------------------------------


def test_score_field_perfect_scalar_match() -> None:
    score = score_field("chief_complaint", "chest pain", "chest pain")
    assert score.correct == 1
    assert score.reference == 1
    assert score.hypothesis == 1
    assert score.precision == pytest.approx(1.0)
    assert score.recall == pytest.approx(1.0)
    assert score.f1 == pytest.approx(1.0)


def test_score_field_wrong_scalar_is_zero() -> None:
    score = score_field("chief_complaint", "chest pain", "headache")
    assert score.f1 == pytest.approx(0.0)


def test_score_field_both_null_is_perfect() -> None:
    score = score_field("onset", None, None)
    assert score.f1 == pytest.approx(1.0)


def test_score_field_hallucinated_value_is_zero() -> None:
    score = score_field("allergies", [], ["penicillin"])
    assert score.correct == 0
    assert score.f1 == pytest.approx(0.0)


def test_score_field_partial_list_match() -> None:
    score = score_field("associated_symptoms", ["a", "b"], ["a", "c"])
    assert score.correct == 1
    assert score.reference == 2
    assert score.hypothesis == 2
    assert score.precision == pytest.approx(0.5)
    assert score.recall == pytest.approx(0.5)
    assert score.f1 == pytest.approx(0.5)


# --- whole pre-summary scoring ------------------------------------------------


def test_score_structuring_scores_each_field(corpus: Corpus) -> None:
    reference = pre_summary_to_plain(corpus.pre_summaries[0])
    fields = f1_scored_fields(corpus.field_set.fields)
    scores = score_structuring(reference, reference, fields)
    assert set(scores) == set(fields)
    assert all(score.f1 == pytest.approx(1.0) for score in scores.values())


def test_f1_scored_fields_excludes_notes_and_metadata(corpus: Corpus) -> None:
    fields = f1_scored_fields(corpus.field_set.fields)
    assert "clinical_notes" not in fields
    assert "extraction_notes" not in fields
    assert "clip_id" not in fields
    assert "cohort" not in fields
    assert "chief_complaint" in fields


def test_pre_summary_to_plain_matches_loader_shape(corpus: Corpus) -> None:
    summary: PreSummary = corpus.pre_summaries[0]
    plain = pre_summary_to_plain(summary)
    assert plain["chief_complaint"] == summary.chief_complaint
    assert plain["associated_symptoms"] == list(summary.associated_symptoms)
    assert plain["labs_ordered"] == list(summary.labs_ordered)
    assert plain["vitals"]["temperature"] == summary.vitals.temperature


def test_has_clinically_significant_error_flags_bad_medications() -> None:
    reference: PreSummaryData = {
        "chief_complaint": "fever",
        "known_medications": [{"name": "Calpol", "route": "oral"}],
    }
    hypothesis: PreSummaryData = {"chief_complaint": "fever"}
    fields = ("chief_complaint", "known_medications")
    scores = score_structuring(reference, hypothesis, fields)
    assert has_clinically_significant_error(scores) is True


def test_has_clinically_significant_error_ignores_non_clinical_fields() -> None:
    scores = score_structuring(
        {"onset": "4 days ago"},
        {"onset": "last month"},
        ("onset",),
    )
    assert has_clinically_significant_error(scores) is False


# --- aggregation ----------------------------------------------------------------


def test_aggregate_structuring_micro_averages_over_clips() -> None:
    clip_a = {
        "chief_complaint": score_field("chief_complaint", "chest pain", "chest pain"),
        "labs_ordered": score_field("labs_ordered", ["CBC"], ["CBC"]),
    }
    clip_b = {
        "chief_complaint": score_field("chief_complaint", "chest pain", "headache"),
        "labs_ordered": score_field("labs_ordered", ["CBC"], ["CBC", "x-ray"]),
    }
    summary = aggregate_structuring([clip_a, clip_b])
    assert summary.sample_size == 2
    assert summary.per_field["chief_complaint"].f1 == pytest.approx(0.5)
    labs = summary.per_field["labs_ordered"]
    assert labs.correct == 2
    assert labs.reference == 2
    assert labs.hypothesis == 3
    # overall: correct=3, reference=4, hypothesis=5 -> F1 = 2*(3/4)*(3/5)/((3/4)+(3/5))
    expected = 2 * (3 / 4) * (3 / 5) / ((3 / 4) + (3 / 5))
    assert summary.overall.f1 == pytest.approx(expected)


def test_aggregate_structuring_empty_set() -> None:
    summary = aggregate_structuring([])
    assert summary.sample_size == 0
    assert summary.overall.f1 == pytest.approx(1.0)
    assert summary.per_field == {}


# --- well-formed subset ----------------------------------------------------------


def test_is_well_formed_boundary_is_inclusive() -> None:
    assert is_well_formed(TRANSCRIPTION_FLOOR_WER) is True
    assert is_well_formed(TRANSCRIPTION_FLOOR_WER + 0.001) is False
    assert is_well_formed(None) is False


# --- AMB-006 flag -------------------------------------------------------------


def test_low_confidence_threshold_semantics() -> None:
    assert low_confidence(0.70) is False
    assert low_confidence(0.69) is True
    assert low_confidence(0.95) is False


def test_low_confidence_unknown_confidence_flags() -> None:
    assert low_confidence(None) is True


# --- structuring bar -----------------------------------------------------------


def _summary_with_overall_f1(f1: float, sample_size: int = 3) -> StructuringSummary:
    from phase0.harness.models import FieldF1

    # Build counts that are consistent with the reported precision/recall/F1:
    # reference == hypothesis == denominator, correct == f1 * denominator.
    denominator = 100
    correct = round(f1 * denominator)
    precision = correct / denominator
    overall = FieldF1(
        field="overall",
        correct=correct,
        reference=denominator,
        hypothesis=denominator,
        precision=precision,
        recall=precision,
        f1=precision,
    )
    return StructuringSummary(per_field={}, overall=overall, sample_size=sample_size)


def test_structuring_bar_passes_at_90_percent() -> None:
    passes, failures = evaluate_structuring_bar(_summary_with_overall_f1(0.90))
    assert passes is True
    assert failures == []


def test_structuring_bar_fails_below_90_percent() -> None:
    passes, failures = evaluate_structuring_bar(_summary_with_overall_f1(0.89))
    assert passes is False
    assert any("F1" in failure for failure in failures)


def test_structuring_bar_fails_when_no_well_formed_clips() -> None:
    passes, failures = evaluate_structuring_bar(None)
    assert passes is False
    assert failures == ["structuring: no well-formed clips scored"]


# --- AMB-006 calibration -------------------------------------------------------


def _row(clip_id: str, confidence: float | None, significant: bool) -> PerClipStructuring:
    return PerClipStructuring(
        clip_id=clip_id,
        cohort="urban_hindi",
        structured={},
        confidence=confidence,
        low_confidence=low_confidence(confidence),
        significant_error=significant,
        field_f1={},
        usage=None,
    )


def test_calibration_reports_rates_and_verdict() -> None:
    rows = [
        _row("a", 0.90, False),
        _row("b", 0.95, True),  # silent error: unflagged but significant
        _row("c", 0.50, True),  # caught by the flag
        _row("d", 0.30, True),  # caught by the flag
        _row("e", 0.80, False),
    ]
    report = calibrate(rows)
    assert report.threshold == 0.70
    assert report.clips == 5
    assert report.flagged == 2
    assert report.unflagged == 3
    assert report.significant_errors == 3
    assert report.flagged_significant == 2
    assert report.silent_errors == 1
    assert report.silent_error_rate == pytest.approx(1 / 3)
    assert report.flag_precision == pytest.approx(1.0)
    assert report.flag_recall == pytest.approx(2 / 3)
    assert report.passes_silent_error_bar is False


def test_calibration_passes_with_zero_silent_errors() -> None:
    rows = [
        _row("a", 0.90, False),
        _row("b", 0.95, False),
        _row("c", 0.40, True),  # caught by the flag
    ]
    report = calibrate(rows)
    assert report.silent_error_rate == 0.0
    assert report.flag_precision == pytest.approx(1.0)
    assert report.flag_recall == pytest.approx(1.0)
    assert report.passes_silent_error_bar is True


def test_calibration_with_no_flagged_clips_has_no_precision() -> None:
    rows = [_row("a", 0.90, False)]
    report = calibrate(rows)
    assert report.flagged == 0
    assert report.flag_precision is None
    assert report.silent_error_rate == 0.0
    assert report.passes_silent_error_bar is True


def test_calibration_with_no_significant_errors_has_no_recall() -> None:
    rows = [_row("a", 0.50, False)]
    report = calibrate(rows)
    assert report.significant_errors == 0
    assert report.flag_recall is None


def test_calibration_all_flagged_is_unproven_and_fails_the_bar() -> None:
    rows = [_row("a", 0.40, True), _row("b", 0.30, False)]
    report = calibrate(rows)
    assert report.flagged == 2
    assert report.unflagged == 0
    assert report.silent_error_rate is None
    assert report.passes_silent_error_bar is False


def test_clinically_significant_fields_are_the_clinical_action_set() -> None:
    assert {
        "chief_complaint",
        "known_medications",
        "allergies",
        "diagnosis_impression",
        "advice",
        "vitals",
    } <= CLINICALLY_SIGNIFICANT_FIELDS
