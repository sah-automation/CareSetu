"""#751: the deterministic code evaluators and their synthetic golden dataset.

Covers the ticket's money-free, content-free acceptance criteria:

- Evaluators are code: the same inputs always produce the same scores, and
  the golden run reproduces every expectation the dataset declares (the
  regression that keeps an evaluator from silently going soft).
- Synthetic content only: the golden dataset shares no text with the phase0
  corpus (the real clinical fixtures), and the evaluation modules never
  import it.
- Numeric or boolean only: every score aggregates; a free-text or non-finite
  verdict is refused at construction.
- PHI-free reads: a production row is forced through the same span-metadata
  allow-list the adapters use, so a non-allow-listed column fails the read
  instead of becoming an evaluator input.
- The observation-level shape #752 joins against: production scores stay
  vendor-id-free, golden scores carry deterministic trace/observation ids.

Thresholds are checked at their exact boundaries against the phase0 harness's
own predicates (ADR-0001: WER <= 0.20 well-formed, confidence floor 0.70), so
two definitions of the same product rule cannot drift apart unnoticed.

The vendor half and the facade seam live in
``test_observability_langfuse_evaluation.py``; the round-trip against real
PostgreSQL lives in ``tests/integration/test_observability_evaluation_round_trip.py``.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict
from datetime import date
from typing import Any

import pytest

from modules.observability.domain.consumer import (
    AI_JOB_SPEND_STATUS_COMPLETED,
    AI_JOB_SPEND_STATUS_FAILED,
)
from modules.observability.domain.evaluation import (
    CONFIDENCE_FLOOR,
    DATA_TYPE_BOOLEAN,
    DATA_TYPE_NUMERIC,
    EVAL_JOB_SUCCEEDED,
    EVAL_STRUCTURING_CONFIDENCE_MET,
    EVAL_STRUCTURING_FIELD_ACCURACY,
    EVAL_TRANSCRIPTION_WELL_FORMED,
    EVAL_TRANSCRIPTION_WER,
    EVALUATOR_NAMES,
    SOURCE_CODE,
    SOURCE_HUMAN,
    SOURCE_JUDGE,
    WELL_FORMED_WER_CEILING,
    EvaluationScore,
    evaluate_day,
    evaluate_golden_dataset,
    evaluate_job_row,
    field_accuracy,
    golden_observation_id,
    golden_trace_id,
    is_well_formed,
    meets_confidence_floor,
    observation_metadata,
    vendor_score_id,
    word_error_rate,
)
from modules.observability.domain.golden_dataset import (
    GOLDEN_STRUCTURINGS,
    GOLDEN_TRANSCRIPTIONS,
)
from observability.langfuse_span import ALLOWED_SPAN_METADATA_KEYS, SpanMetadataError
from phase0.harness.metrics import (
    TRANSCRIPTION_FLOOR_WER,
    compute_wer,
)
from phase0.harness.metrics import (
    is_well_formed as phase0_is_well_formed,
)
from phase0.harness.metrics import (
    low_confidence as phase0_low_confidence,
)
from phase0.loader import Corpus

_TARGET_DATE = date(2026, 10, 12)
_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


def _job_row(**overrides: Any) -> dict[str, Any]:
    """A production AI-job row with only allow-listed telemetry columns."""
    row: dict[str, Any] = {
        "ai_job_ref": 42,
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "task_type": "structuring",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_paise": 120,
        "status": AI_JOB_SPEND_STATUS_COMPLETED,
        "trace_id": _TRACE_ID,
    }
    row.update(overrides)
    return row


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for nested in value.values() for leaf in _string_leaves(nested)]
    if isinstance(value, (list, tuple)):
        return [leaf for nested in value for leaf in _string_leaves(nested)]
    return []


# --- synthetic content only -------------------------------------------------


def test_the_golden_dataset_shares_no_text_with_the_real_corpus(corpus: Corpus) -> None:
    """AC: the evaluation pipeline runs on synthetic data, never the corpus.

    Every string the evaluators score on - golden transcripts and structuring
    fields alike - must be absent from the phase0 corpus, normalized the same
    way on both sides so casing and whitespace cannot hide a copy.
    """
    corpus_parts: list[str] = [
        clip.transcript_path.read_text(encoding="utf-8") for clip in corpus.clips
    ]
    for summary in corpus.pre_summaries:
        corpus_parts.extend(_string_leaves(asdict(summary)))
    corpus_blob = _normalize(" ".join(corpus_parts))

    golden_texts: list[str] = []
    for example in GOLDEN_TRANSCRIPTIONS:
        golden_texts.extend([example.reference, example.hypothesis])
    for example in GOLDEN_STRUCTURINGS:
        golden_texts.extend(example.expected_fields.values())
        golden_texts.extend(example.produced_fields.values())
    # Single-token values ("3" days) carry no content to contaminate and
    # collide with any corpus blob by construction; the check is about text.
    golden_texts = [text for text in golden_texts if len(_normalize(text).split()) >= 2]

    assert golden_texts, "the dataset must have content for the check to mean anything"
    leaked = [text for text in golden_texts if _normalize(text) in corpus_blob]
    assert leaked == [], f"golden dataset text found in the real corpus: {leaked}"


def test_the_evaluation_modules_never_import_the_corpus() -> None:
    """Structural guard: phase0 is test-only, so production cannot load it."""
    from modules.observability.domain import evaluation, golden_dataset

    for module in (evaluation, golden_dataset):
        source = inspect.getsource(module)
        assert "import phase0" not in source
        assert "from phase0" not in source


def test_the_dataset_declares_expectations_for_every_evaluator_it_exercises() -> None:
    declared = {name for example in GOLDEN_TRANSCRIPTIONS for name in example.expected}
    declared |= {name for example in GOLDEN_STRUCTURINGS for name in example.expected}
    assert declared == EVALUATOR_NAMES - {EVAL_JOB_SUCCEEDED}


# --- determinism and the golden regression ----------------------------------


def test_the_same_day_scores_identically_every_time() -> None:
    rows = [_job_row()]
    first = evaluate_day(_TARGET_DATE, rows)
    second = evaluate_day(_TARGET_DATE, rows)
    assert first == second


def test_the_transcription_examples_reproduce_their_expected_scores() -> None:
    scores = evaluate_golden_dataset(_TARGET_DATE)
    by_key = {(score.observation_ref, score.evaluator): score.value for score in scores}
    for example in GOLDEN_TRANSCRIPTIONS:
        wer = word_error_rate(example.reference, example.hypothesis)
        well_formed = 1.0 if is_well_formed(wer) else 0.0
        assert wer == pytest.approx(example.expected[EVAL_TRANSCRIPTION_WER], abs=1e-9)
        assert well_formed == example.expected[EVAL_TRANSCRIPTION_WELL_FORMED]
        assert by_key[(example.example_id, EVAL_TRANSCRIPTION_WER)] == wer
        assert by_key[(example.example_id, EVAL_TRANSCRIPTION_WELL_FORMED)] == well_formed


def test_the_structuring_examples_reproduce_their_expected_scores() -> None:
    scores = evaluate_golden_dataset(_TARGET_DATE)
    by_key = {(score.observation_ref, score.evaluator): score.value for score in scores}
    for example in GOLDEN_STRUCTURINGS:
        accuracy = field_accuracy(example.expected_fields, example.produced_fields)
        met = 1.0 if meets_confidence_floor(example.confidence) else 0.0
        assert accuracy == pytest.approx(example.expected[EVAL_STRUCTURING_FIELD_ACCURACY])
        assert met == example.expected[EVAL_STRUCTURING_CONFIDENCE_MET]
        assert by_key[(example.example_id, EVAL_STRUCTURING_FIELD_ACCURACY)] == accuracy
        assert by_key[(example.example_id, EVAL_STRUCTURING_CONFIDENCE_MET)] == met


def test_the_evaluators_agree_with_the_phase0_harness() -> None:
    """ADR-0001's rules exist twice (harness and evaluators); pin them together."""
    assert WELL_FORMED_WER_CEILING == TRANSCRIPTION_FLOOR_WER
    assert CONFIDENCE_FLOOR == 0.70
    for example in GOLDEN_TRANSCRIPTIONS:
        assert word_error_rate(example.reference, example.hypothesis) == pytest.approx(
            compute_wer(example.reference, example.hypothesis), abs=1e-6
        )
    for wer in (0.0, 0.1, 0.2, 0.200001, 1.0):
        assert is_well_formed(wer) == phase0_is_well_formed(wer)
    for confidence in (None, 0.0, 0.69, 0.70, 0.92, 1.0):
        assert meets_confidence_floor(confidence) == (not phase0_low_confidence(confidence))


# --- the evaluator primitives at their boundaries ---------------------------


def test_wer_scores_known_edits() -> None:
    assert word_error_rate("one two three", "one two three") == 0.0
    assert word_error_rate("one two three four five", "one two X four five") == 0.2
    assert (
        word_error_rate("alpha beta gamma delta epsilon", "totally different words here now") == 1.0
    )
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "something") == 1.0


def test_wer_rounds_to_the_storage_precision() -> None:
    value = word_error_rate("a b c d e f g h i", "a b c d e f g h X")
    assert value == 0.111111


def test_well_formed_holds_exactly_at_the_ceiling() -> None:
    assert is_well_formed(0.2) is True
    assert is_well_formed(0.200001) is False
    assert is_well_formed(0.0) is True


def test_the_confidence_floor_holds_exactly_at_seventy() -> None:
    assert meets_confidence_floor(0.70) is True
    assert meets_confidence_floor(0.699999) is False
    assert meets_confidence_floor(None) is False


def test_field_accuracy_ignores_case_and_whitespace() -> None:
    assert field_accuracy({"a": "Dry Cough "}, {"a": "dry cough"}) == 1.0
    assert field_accuracy({"a": "x", "b": "y"}, {"a": "x"}) == 0.5
    assert field_accuracy({"a": "x", "b": "y"}, {}) == 0.0
    with pytest.raises(ValueError, match="at least one expected field"):
        field_accuracy({}, {"a": "x"})


# --- the PHI-free read gate --------------------------------------------------


def test_reading_metadata_refuses_anything_off_the_allow_list() -> None:
    with pytest.raises(SpanMetadataError, match="transcript"):
        observation_metadata({"task_type": "structuring", "transcript": "patient said ..."})
    gated = observation_metadata({"task_type": "structuring", "confidence": None})
    assert gated == {"task_type": "structuring"}


def test_a_job_row_must_pass_every_column_through_the_allow_list() -> None:
    scores = evaluate_job_row(_job_row(), _TARGET_DATE)
    assert len(scores) == 1

    poisoned = _job_row(patient_name="someone", transcript="free text")
    with pytest.raises(SpanMetadataError) as excinfo:
        evaluate_job_row(poisoned, _TARGET_DATE)
    message = str(excinfo.value)
    assert "patient_name" in message
    assert "transcript" in message
    assert "someone" not in message and "free text" not in message


def test_the_job_evaluator_reads_only_allow_listed_status_and_trace() -> None:
    succeeded = evaluate_job_row(_job_row(), _TARGET_DATE)
    failed = evaluate_job_row(_job_row(status=AI_JOB_SPEND_STATUS_FAILED), _TARGET_DATE)
    assert succeeded[0].value == 1.0
    assert failed[0].value == 0.0
    assert succeeded[0].data_type == DATA_TYPE_BOOLEAN
    assert succeeded[0].trace_id == _TRACE_ID


def test_a_job_row_without_a_trace_id_keeps_a_local_score() -> None:
    scores = evaluate_job_row(_job_row(trace_id=None), _TARGET_DATE)
    assert scores[0].value == 1.0
    assert scores[0].trace_id is None


def test_production_scores_carry_no_vendor_observation_id() -> None:
    """The vendor half refuses these on purpose - the trace-level path is deprecated."""
    for score in evaluate_job_row(_job_row(), _TARGET_DATE):
        assert score.observation_id is None
        assert score.observation_kind == "ai_job"


# --- the score shape ---------------------------------------------------------


def test_a_boolean_score_must_be_zero_or_one() -> None:
    with pytest.raises(ValueError, match="must be 0 or 1"):
        EvaluationScore(
            score_date=_TARGET_DATE,
            observation_kind="ai_job",
            observation_ref="7",
            evaluator="job_succeeded",
            data_type=DATA_TYPE_BOOLEAN,
            value=0.5,
        )


def test_a_numeric_score_quantizes_to_the_storage_precision() -> None:
    score = EvaluationScore(
        score_date=_TARGET_DATE,
        observation_kind="golden",
        observation_ref="tx",
        evaluator=EVAL_TRANSCRIPTION_WER,
        data_type=DATA_TYPE_NUMERIC,
        value=1 / 3,
    )
    assert score.value == 0.333333


def test_a_free_text_or_unknown_verdict_is_refused() -> None:
    with pytest.raises(ValueError, match="numeric or boolean"):
        EvaluationScore(
            score_date=_TARGET_DATE,
            observation_kind="golden",
            observation_ref="tx",
            evaluator="transcription_note",
            data_type="TEXT",
            value=1.0,
        )
    with pytest.raises(ValueError, match="finite"):
        EvaluationScore(
            score_date=_TARGET_DATE,
            observation_kind="golden",
            observation_ref="tx",
            evaluator=EVAL_TRANSCRIPTION_WER,
            data_type=DATA_TYPE_NUMERIC,
            value=float("nan"),
        )


def test_a_judge_score_needs_a_run_and_carries_non_phi_metadata() -> None:
    score = EvaluationScore(
        score_date=_TARGET_DATE,
        observation_kind="golden",
        observation_ref="tx-clear",
        evaluator="completeness",
        data_type=DATA_TYPE_NUMERIC,
        value=0.9,
        source=SOURCE_JUDGE,
        judge_run_ref="run-1",
        metadata={"judge_model": "fake-judge", "prompt_version": "v1"},
    )
    assert score.source == SOURCE_JUDGE
    assert score.judge_run_ref == "run-1"
    assert score.metadata == {"judge_model": "fake-judge", "prompt_version": "v1"}

    with pytest.raises(ValueError, match="run they belong to"):
        EvaluationScore(
            score_date=_TARGET_DATE,
            observation_kind="golden",
            observation_ref="tx-clear",
            evaluator="completeness",
            data_type=DATA_TYPE_NUMERIC,
            value=0.9,
            source=SOURCE_JUDGE,
        )


def test_only_a_judge_score_carries_a_run_reference() -> None:
    for source in (SOURCE_CODE, SOURCE_HUMAN):
        with pytest.raises(ValueError, match="only judge scores"):
            EvaluationScore(
                score_date=_TARGET_DATE,
                observation_kind="golden",
                observation_ref="tx-clear",
                evaluator="transcription_wer",
                data_type=DATA_TYPE_NUMERIC,
                value=0.0,
                source=source,
                judge_run_ref="run-1",
            )


def test_the_golden_run_always_produces_numeric_or_boolean_scores_only() -> None:
    for score in evaluate_golden_dataset(_TARGET_DATE):
        assert score.data_type in {DATA_TYPE_NUMERIC, DATA_TYPE_BOOLEAN}
        if score.data_type == DATA_TYPE_BOOLEAN:
            assert score.value in {0.0, 1.0}


# --- deterministic ids for the observation-level vendor path ----------------


def test_ids_are_stable_hex_in_the_vendor_formats() -> None:
    trace_id = golden_trace_id(_TARGET_DATE)
    observation_id = golden_observation_id(_TARGET_DATE, "tx-clear")
    score_id = vendor_score_id(observation_id, EVAL_TRANSCRIPTION_WER)

    assert len(trace_id) == 32 and set(trace_id) <= set("0123456789abcdef")
    assert len(observation_id) == 16 and set(observation_id) <= set("0123456789abcdef")
    assert len(score_id) == 16 and set(score_id) <= set("0123456789abcdef")

    assert trace_id == golden_trace_id(_TARGET_DATE)
    assert observation_id == golden_observation_id(_TARGET_DATE, "tx-clear")
    assert score_id == vendor_score_id(observation_id, EVAL_TRANSCRIPTION_WER)

    # Different date, example or evaluator - different id: re-runs converge,
    # new work never collides with old.
    assert golden_trace_id(date(2026, 10, 13)) != trace_id
    assert golden_observation_id(_TARGET_DATE, "tx-degraded") != observation_id
    assert vendor_score_id(observation_id, EVAL_TRANSCRIPTION_WELL_FORMED) != score_id


def test_every_golden_score_names_its_observation_and_trace() -> None:
    for score in evaluate_golden_dataset(_TARGET_DATE):
        assert score.observation_id is not None
        assert score.trace_id == golden_trace_id(_TARGET_DATE)
        assert score.observation_kind == "golden"


def test_golden_observation_metadata_stays_on_the_allow_list() -> None:
    from modules.observability.domain.evaluation import golden_observation_metadata

    for task_type in ("transcription", "structuring"):
        metadata = golden_observation_metadata(task_type)
        assert set(metadata) <= ALLOWED_SPAN_METADATA_KEYS
        assert metadata["task_type"] == task_type
        assert metadata["provider"] == "golden"
        assert not any(key in metadata for key in ("input", "output", "transcript"))
