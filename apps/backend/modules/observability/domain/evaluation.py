"""MOD-013: Deterministic code evaluators over PHI-free metadata and the golden dataset (#751).

Spec #717 decision 40: evaluation is code, never a model call - running it
spends no inference money, it is reproducible, and its only content input is
the synthetic golden dataset in
:mod:`modules.observability.domain.golden_dataset`. Production content never
enters this pipeline. The one production row an evaluator reads is passed
through :func:`observability.langfuse_span.build_span_metadata` first, the
same PHI-free allow-list that gates what adapters may attach to a vendor
span, so the "no PHI in evaluation" rule has one owner, not two: a column
that ever grew a transcript or a patient name would fail loudly here instead
of quietly becoming an evaluator input.

Decision 40 supersedes A7 of ``docs/standards/ai-engineering-standards.md``
for this pipeline: A7 sketches the vendor eval framework with LLM-as-judge,
while decision 40 requires code-only, money-free evaluation over synthetic
content - this module is that implementation, and the #752 annotation queue
is the human-signal counterpart A7 also anticipates.

Recording shape (the contract #752's annotation queue will join against):

* one :class:`EvaluationScore` per ``(observation, evaluator)`` - numeric
  (six-decimal) or boolean (0/1) only, so scores aggregate;
* the cross-tool ``trace_id`` travels on every score, so a human's annotation
  and a technical score can be found for the same call by one key;
* ``source`` distinguishes ``code`` (this module) from ``human`` (the queue
  #752 owns), so the human signal lands in the same rows without a new
  shape;
* score ids are derived, never random (see :func:`vendor_score_id`), so a
  re-run of the same date replaces its rows instead of stacking duplicates.

Observation-level, not trace-level: the vendor's trace-level evaluation path
is deprecated with the November 2026 cloud cutover, so every score this
module produces that reaches Langfuse carries an ``observation_id`` beside
the trace id - the golden run mints those ids here (deterministic per date
and example) and :mod:`observability.langfuse_evaluation` creates the
matching observations under the same deterministic trace.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

from modules.observability.domain.consumer import AI_JOB_SPEND_STATUS_COMPLETED
from modules.observability.domain.golden_dataset import (
    GOLDEN_DATASET_VERSION,
    GOLDEN_STRUCTURINGS,
    GOLDEN_TRANSCRIPTIONS,
)
from observability.langfuse_span import build_span_metadata

# ------------------------------------------------------------- score vocabulary

#: ``data_type`` values: a score is NUMERIC or BOOLEAN, never free text -
#: the aggregation rule decision 40 turns on.
DATA_TYPE_NUMERIC = "NUMERIC"
DATA_TYPE_BOOLEAN = "BOOLEAN"

#: ``source`` values. ``human`` is #752's annotation queue: the doctor review
#: outcomes recorded through :mod:`modules.observability.domain.annotation`.
#: ``judge`` is the synthetic LLM-as-judge run (#789), which carries a run
#: reference and non-PHI metadata. This module produces ``code`` only.
SOURCE_CODE = "code"
SOURCE_HUMAN = "human"
SOURCE_JUDGE = "judge"

#: ``observation_kind`` values: a real AI job's telemetry, a golden dataset
#: example, and - since #752 - a prescription a doctor reviewed.
OBSERVATION_KIND_AI_JOB = "ai_job"
OBSERVATION_KIND_GOLDEN = "golden"
OBSERVATION_KIND_PRESCRIPTION = "prescription"

EVAL_JOB_SUCCEEDED = "job_succeeded"
EVAL_TRANSCRIPTION_WER = "transcription_wer"
EVAL_TRANSCRIPTION_WELL_FORMED = "transcription_well_formed"
EVAL_STRUCTURING_FIELD_ACCURACY = "structuring_field_accuracy"
EVAL_STRUCTURING_CONFIDENCE_MET = "structuring_confidence_met"

#: The evaluator vocabulary this module produces (the golden dataset's
#: declared expectations are asserted against it in the unit suite). The
#: annotation queue's human evaluators (#752) are deliberately absent: they
#: are declared in ``domain.annotation``, because these are the CODE
#: evaluators and the two vocabularies are asserted separately.
EVALUATOR_NAMES: frozenset[str] = frozenset(
    {
        EVAL_JOB_SUCCEEDED,
        EVAL_TRANSCRIPTION_WER,
        EVAL_TRANSCRIPTION_WELL_FORMED,
        EVAL_STRUCTURING_FIELD_ACCURACY,
        EVAL_STRUCTURING_CONFIDENCE_MET,
    }
)

OBSERVATION_KINDS: frozenset[str] = frozenset(
    {OBSERVATION_KIND_AI_JOB, OBSERVATION_KIND_GOLDEN, OBSERVATION_KIND_PRESCRIPTION}
)
DATA_TYPES: frozenset[str] = frozenset({DATA_TYPE_NUMERIC, DATA_TYPE_BOOLEAN})
SOURCES: frozenset[str] = frozenset({SOURCE_CODE, SOURCE_HUMAN, SOURCE_JUDGE})

#: ADR-0001 / AMB-006: self-reported confidence at or above the floor passes,
#: strictly below it - or absent - is flagged as low confidence.
CONFIDENCE_FLOOR = 0.70

#: ADR-0001: a transcription counts as well-formed at WER <= 0.20 (the same
#: floor the phase0 harness reports).
WELL_FORMED_WER_CEILING = 0.20

#: Six decimals - the precision :class:`EvaluationScore` quantizes to, which
#: is also the storage precision of the local score table's ``value``.
_VALUE_QUANTUM = Decimal("0.000001")

#: Domain separator for every id hash below, so a golden observation id can
#: never collide with a score id even if the input strings were equal.
_ID_DOMAIN = "caresetu-evaluation"


# ------------------------------------------------------------------- score shape


@dataclass(frozen=True, slots=True)
class EvaluationScore:
    """One evaluator's verdict about one observation (the #752 join shape).

    ``observation_ref`` is the local identity of the observation being scored
    (an ``ai_job_ref`` for production rows, a golden ``example_id`` for the
    dataset) and ``observation_id`` is the vendor's id when - and only when -
    one exists: production rows have no vendor observation we may name (their
    trace-level score path is the deprecated one), golden examples carry the
    deterministic id :func:`golden_observation_id` mints and the vendor half
    creates.
    """

    score_date: date
    observation_kind: str
    observation_ref: str
    evaluator: str
    data_type: str
    value: float
    source: str = SOURCE_CODE
    trace_id: str | None = None
    observation_id: str | None = None
    #: The judge run a ``judge`` row belongs to. ``None`` on code and human
    #: rows: their identity is a batch date, not a run (#766).
    judge_run_ref: str | None = None
    #: Non-PHI operational metadata for a judged score (model, prompt version,
    #: parse outcome). Never the content the score was computed from.
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.observation_kind not in OBSERVATION_KINDS:
            raise ValueError(f"unknown observation kind: {self.observation_kind!r}")
        if not self.observation_ref:
            raise ValueError("observation_ref must name the observation scored")
        if not self.evaluator or len(self.evaluator) > 64:
            raise ValueError(f"evaluator name must be 1..64 chars, got {self.evaluator!r}")
        if self.data_type not in DATA_TYPES:
            raise ValueError(f"data_type must be numeric or boolean, got {self.data_type!r}")
        if self.source not in SOURCES:
            raise ValueError(f"unknown score source: {self.source!r}")
        if self.source == SOURCE_JUDGE:
            if not self.judge_run_ref:
                raise ValueError("judge scores must carry the run they belong to")
        elif self.judge_run_ref is not None:
            raise ValueError("only judge scores may carry a run reference")
        if not isfinite(self.value):
            raise ValueError(f"score value must be finite, got {self.value!r}")
        quantized = Decimal(str(self.value)).quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP)
        if self.data_type == DATA_TYPE_BOOLEAN and quantized not in (
            Decimal("0.000000"),
            Decimal("1.000000"),
        ):
            raise ValueError(f"boolean score {self.evaluator!r} must be 0 or 1, got {self.value!r}")
        object.__setattr__(self, "value", float(quantized))


# ---------------------------------------------------------------- evaluator core


def _edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    """Word-level Levenshtein distance, two-row dynamic programming."""
    previous = list(range(len(hypothesis) + 1))
    for row, reference_word in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_word in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (reference_word != hypothesis_word),
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = word edits / reference word count, rounded to six decimals.

    ``0.0`` for an exact match; a reference with no words scores ``0.0`` only
    when the hypothesis is empty too, so a blank reference cannot masquerade
    as a perfect transcript.
    """
    reference_words = reference.split()
    if not reference_words:
        return 0.0 if not hypothesis.split() else 1.0
    distance = _edit_distance(reference_words, hypothesis.split())
    return round(distance / len(reference_words), 6)


def is_well_formed(wer: float) -> bool:
    """ADR-0001's transcription bar: WER at or under the ceiling passes."""
    return wer <= WELL_FORMED_WER_CEILING


def meets_confidence_floor(confidence: float | None) -> bool:
    """ADR-0001's confidence floor: at or above 0.70 passes, missing fails.

    A run that reported no confidence is not trusted by omission - absence is
    low confidence, not a pass.
    """
    return confidence is not None and confidence >= CONFIDENCE_FLOOR


def _normalize_field(value: str | None) -> str:
    """Case-folded, trimmed field text so formatting is not scored as error."""
    return "" if value is None else value.strip().casefold()


def field_accuracy(expected_fields: Mapping[str, str], produced_fields: Mapping[str, str]) -> float:
    """Share of expected fields the produced fields match, rounded to six decimals.

    A produced field that is absent, or differs only in case/whitespace from
    its expectation, is counted by the same rule: the evaluator scores
    content, not formatting.
    """
    if not expected_fields:
        raise ValueError("field accuracy needs at least one expected field")
    matched = sum(
        1
        for name, expected_value in expected_fields.items()
        if _normalize_field(produced_fields.get(name)) == _normalize_field(expected_value)
    )
    return round(matched / len(expected_fields), 6)


def observation_metadata(candidate: Mapping[str, object]) -> dict[str, object]:
    """Gate a candidate observation's metadata through the shared allow-list.

    The PHI-free read seam: every evaluator in this module looks at metadata
    only after this returns, so ``transcript``, ``patient_name`` or any other
    non-allow-listed column raises :class:`SpanMetadataError` at the point of
    read rather than influencing a score.
    """
    return build_span_metadata(candidate)


# ------------------------------------------------------------------ deterministic ids


def _digest(*parts: str, length: int) -> str:
    """First ``length`` hex chars of SHA-256 over the domain-separated parts."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:length]


def golden_trace_id(target_date: date) -> str:
    """The one trace the golden run of ``target_date`` lives under.

    32 hex characters (W3C trace-id shape) and stable per date: re-running a
    date rewrites the same trace instead of forking a second history.
    """
    return _digest(_ID_DOMAIN, "golden-trace", target_date.isoformat(), length=32)


def golden_observation_id(target_date: date, example_id: str) -> str:
    """One golden example's vendor observation id: 16 hex characters.

    The format Langfuse accepts for observation ids, stable per
    ``(date, example)`` so score posts and observation creates converge on the
    same ids every re-run.
    """
    return _digest(_ID_DOMAIN, "golden-observation", target_date.isoformat(), example_id, length=16)


def vendor_score_id(observation_id: str, evaluator: str) -> str:
    """The score id posted to the vendor: 16 hex characters.

    Derived from the observation and the evaluator, so posting the same date
    twice upserts the same rows (the scores endpoint upserts on ``id``)
    instead of duplicating them.
    """
    return _digest(_ID_DOMAIN, "vendor-score", observation_id, evaluator, length=16)


# --------------------------------------------------------------------- evaluators


def evaluate_job_row(row: Mapping[str, object], score_date: date) -> list[EvaluationScore]:
    """The production-path evaluator: did that AI job succeed?

    The only evaluator that ever looks at production data, and it looks at
    nothing but the allow-listed telemetry columns of one row: the candidate
    metadata is every column except the identity reference, forced through
    :func:`observation_metadata`, so a future column outside the allow-list
    fails the whole read instead of slipping an evaluator input past the PHI
    gate. The verdict travels with the row's own ``trace_id`` - the key the
    #752 annotation queue joins human judgement to.
    """
    observation_ref = str(row["ai_job_ref"])
    candidate = {key: value for key, value in row.items() if key != "ai_job_ref"}
    candidate["ai_job_id"] = row["ai_job_ref"]
    metadata = observation_metadata(candidate)
    trace_value = metadata.get("trace_id")
    succeeded = metadata.get("status") == AI_JOB_SPEND_STATUS_COMPLETED
    return [
        EvaluationScore(
            score_date=score_date,
            observation_kind=OBSERVATION_KIND_AI_JOB,
            observation_ref=observation_ref,
            evaluator=EVAL_JOB_SUCCEEDED,
            data_type=DATA_TYPE_BOOLEAN,
            value=1.0 if succeeded else 0.0,
            trace_id=str(trace_value) if trace_value is not None else None,
        )
    ]


def golden_observation_metadata(task_type: str) -> dict[str, object]:
    """Allow-listed observation metadata for one golden example.

    Synthetic by construction: ``provider`` and ``model`` name the dataset,
    never a real integration, and no transcript or field text is included -
    the content stays in Postgres; the vendor only learns what kind of example
    it is scoring.
    """
    return observation_metadata(
        {
            "task_type": task_type,
            "provider": "golden",
            "model": GOLDEN_DATASET_VERSION,
            "status": AI_JOB_SPEND_STATUS_COMPLETED,
        }
    )


def _golden_score(
    target_date: date,
    example_id: str,
    evaluator: str,
    data_type: str,
    value: float,
) -> EvaluationScore:
    return EvaluationScore(
        score_date=target_date,
        observation_kind=OBSERVATION_KIND_GOLDEN,
        observation_ref=example_id,
        evaluator=evaluator,
        data_type=data_type,
        value=value,
        trace_id=golden_trace_id(target_date),
        observation_id=golden_observation_id(target_date, example_id),
    )


def evaluate_golden_dataset(target_date: date) -> list[EvaluationScore]:
    """Score every golden example of ``target_date`` - the money-free run.

    Values are computed from the dataset's content (never read from its
    declared ``expected`` - the expectations are there for the regression
    test to check the evaluators against, not for the evaluators to trust).
    """
    scores: list[EvaluationScore] = []
    for example in GOLDEN_TRANSCRIPTIONS:
        wer = word_error_rate(example.reference, example.hypothesis)
        well_formed = 1.0 if is_well_formed(wer) else 0.0
        scores.append(
            _golden_score(
                target_date, example.example_id, EVAL_TRANSCRIPTION_WER, DATA_TYPE_NUMERIC, wer
            )
        )
        scores.append(
            _golden_score(
                target_date,
                example.example_id,
                EVAL_TRANSCRIPTION_WELL_FORMED,
                DATA_TYPE_BOOLEAN,
                well_formed,
            )
        )
    for structuring in GOLDEN_STRUCTURINGS:
        accuracy = field_accuracy(structuring.expected_fields, structuring.produced_fields)
        confidence_met = 1.0 if meets_confidence_floor(structuring.confidence) else 0.0
        scores.append(
            _golden_score(
                target_date,
                structuring.example_id,
                EVAL_STRUCTURING_FIELD_ACCURACY,
                DATA_TYPE_NUMERIC,
                accuracy,
            )
        )
        scores.append(
            _golden_score(
                target_date,
                structuring.example_id,
                EVAL_STRUCTURING_CONFIDENCE_MET,
                DATA_TYPE_BOOLEAN,
                confidence_met,
            )
        )
    return scores


def evaluate_day(
    target_date: date, job_rows: Sequence[Mapping[str, object]]
) -> list[EvaluationScore]:
    """Every score for one batch date: production rows plus the golden run.

    Sorted by ``(kind, ref, evaluator)`` so the insert the facade builds from
    it is byte-identical across runs of the same inputs.
    """
    scores = [score for row in job_rows for score in evaluate_job_row(row, target_date)]
    scores.extend(evaluate_golden_dataset(target_date))
    scores.sort(key=lambda score: (score.observation_kind, score.observation_ref, score.evaluator))
    return scores


#: Evaluator names a human label on a golden example may carry: the union of the
#: code evaluators and the judge evaluators, so agreement is measurable.
HUMAN_LABEL_EVALUATORS = frozenset(
    {
        EVAL_JOB_SUCCEEDED,
        EVAL_TRANSCRIPTION_WER,
        EVAL_TRANSCRIPTION_WELL_FORMED,
        EVAL_STRUCTURING_FIELD_ACCURACY,
        EVAL_STRUCTURING_CONFIDENCE_MET,
        "completeness",
        "confidence_calibration",
        "prescription_draft_accuracy",
    }
)

#: Alias spelling retained for compatibility with existing read models.
HUMAN_LABEL_EVALUATOR_NAMES = HUMAN_LABEL_EVALUATORS

__all__ = [
    "CONFIDENCE_FLOOR",
    "DATA_TYPES",
    "DATA_TYPE_BOOLEAN",
    "DATA_TYPE_NUMERIC",
    "EVALUATOR_NAMES",
    "EVAL_JOB_SUCCEEDED",
    "EVAL_STRUCTURING_CONFIDENCE_MET",
    "EVAL_STRUCTURING_FIELD_ACCURACY",
    "EVAL_TRANSCRIPTION_WELL_FORMED",
    "EVAL_TRANSCRIPTION_WER",
    "HUMAN_LABEL_EVALUATORS",
    "HUMAN_LABEL_EVALUATOR_NAMES",
    "OBSERVATION_KINDS",
    "OBSERVATION_KIND_AI_JOB",
    "OBSERVATION_KIND_GOLDEN",
    "OBSERVATION_KIND_PRESCRIPTION",
    "SOURCES",
    "SOURCE_CODE",
    "SOURCE_HUMAN",
    "SOURCE_JUDGE",
    "WELL_FORMED_WER_CEILING",
    "EvaluationScore",
    "evaluate_day",
    "evaluate_golden_dataset",
    "evaluate_job_row",
    "field_accuracy",
    "golden_observation_id",
    "golden_observation_metadata",
    "golden_trace_id",
    "is_well_formed",
    "meets_confidence_floor",
    "observation_metadata",
    "vendor_score_id",
    "word_error_rate",
]
