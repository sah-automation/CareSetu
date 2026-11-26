"""MOD-013: The synthetic golden dataset #751's code evaluators score.

Every reference transcript, hypothesis and structured field below was written
by hand for this file, so nothing a patient or a doctor ever said can reach
the evaluation pipeline (spec #717 decision 40: evaluation sees synthetic
content only - real content stays out of evaluation). The two example kinds
mirror the two AI legs the product PRD scores:

* transcription - a fabricated reference transcript beside the output a model
  might have produced, giving the WER evaluator ground truth (ADR-0001: a
  transcript is well-formed at WER <= 0.20).
* structuring - fabricated expected structured fields beside produced fields
  and a self-reported confidence, giving the field-accuracy and
  confidence-floor evaluators ground truth (ADR-0001: low confidence is
  strictly below 0.70 or missing).

Each example declares the scores it expects from each evaluator, by
evaluator name as a plain string (the dataset deliberately does not import
the evaluator module, so the dependency runs one way only: the evaluators
read this dataset). The unit suite asserts a run reproduces every declared
value, which is what makes the dataset golden, and separately asserts the
declared names are exactly the evaluator vocabulary in
``modules.observability.domain.evaluation``, so a renamed evaluator cannot
leave a silently dead expectation behind.

A deliberately degraded transcription and two deliberately imperfect
structuring cases are included: evaluators that only ever see perfect
examples cannot detect their own regression.

``GOLDEN_DATASET`` is a constant, not a file on disk: the set is small, its
history is reviewable in this module's diffs, and ``version`` travels with it
into vendor observation metadata so an observation always says which revision
of the set it was scored against.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Version tag carried as observation metadata (``model`` key) whenever this
#: dataset reaches a vendor span, so scores from a revised dataset stay
#: distinguishable from scores taken against the revision before it.
GOLDEN_DATASET_VERSION = "golden-v1"


@dataclass(frozen=True)
class TranscriptionExample:
    """One fabricated transcript beside the output a model might have produced.

    ``expected`` maps evaluator name to the numeric value the evaluators must
    produce for this example - the contract a unit test pins.
    """

    example_id: str
    reference: str
    hypothesis: str
    expected: dict[str, float]


@dataclass(frozen=True)
class StructuringExample:
    """One set of fabricated expected fields beside produced fields.

    ``confidence`` is the provider's self-reported confidence for the
    produced fields; ``None`` models a run that reported no confidence at all,
    which ADR-0001 counts as low confidence rather than as trust.
    """

    example_id: str
    expected_fields: dict[str, str]
    produced_fields: dict[str, str]
    confidence: float | None
    expected: dict[str, float]


#: A clean transcript (WER 0), one with a single small substitution
#: (WER = 1/9 = 0.111111, still well-formed), and one deliberately degraded
#: recording that was transcribed as unusable noise (WER 1.0, NOT well-formed).
GOLDEN_TRANSCRIPTIONS: tuple[TranscriptionExample, ...] = (
    TranscriptionExample(
        example_id="tx-clear",
        reference="patient reports mild headache and slight nausea since morning",
        hypothesis="patient reports mild headache and slight nausea since morning",
        expected={"transcription_wer": 0.0, "transcription_well_formed": 1.0},
    ),
    TranscriptionExample(
        example_id="tx-minor-substitution",
        reference="patient reports mild headache and slight nausea since morning",
        hypothesis="patient reports mild headache and slight nausea in morning",
        expected={"transcription_wer": 0.111111, "transcription_well_formed": 1.0},
    ),
    TranscriptionExample(
        example_id="tx-degraded",
        reference="sore throat and mild fever for two days with no breathing difficulty",
        hypothesis="recording unavailable please repeat",
        expected={"transcription_wer": 1.0, "transcription_well_formed": 0.0},
    ),
)

#: An accurate extraction at 0.92 confidence (above the 0.70 floor), a
#: near-miss at 0.69 (below it), and an incomplete extraction whose
#: confidence was never reported at all.
GOLDEN_STRUCTURINGS: tuple[StructuringExample, ...] = (
    StructuringExample(
        example_id="st-accurate",
        expected_fields={
            "chief_complaint": "dry cough",
            "duration_days": "3",
            "associated_symptoms": "mild cough no fever",
            "current_medications": "none reported",
        },
        produced_fields={
            "chief_complaint": "dry cough",
            "duration_days": "3",
            "associated_symptoms": "mild cough no fever",
            "current_medications": "none reported",
        },
        confidence=0.92,
        expected={"structuring_field_accuracy": 1.0, "structuring_confidence_met": 1.0},
    ),
    StructuringExample(
        example_id="st-borderline",
        expected_fields={
            "chief_complaint": "dry cough",
            "duration_days": "3",
            "associated_symptoms": "mild cough no fever",
            "current_medications": "none reported",
        },
        produced_fields={
            "chief_complaint": "dry cough",
            "duration_days": "3",
            "associated_symptoms": "mild cough no fever",
            "current_medications": "not reported",
        },
        confidence=0.69,
        expected={"structuring_field_accuracy": 0.75, "structuring_confidence_met": 0.0},
    ),
    StructuringExample(
        example_id="st-missing-confidence",
        expected_fields={
            "chief_complaint": "dry cough",
            "duration_days": "3",
            "associated_symptoms": "mild cough no fever",
            "current_medications": "none reported",
        },
        produced_fields={
            "chief_complaint": "dry cough",
            "duration_days": "3",
        },
        confidence=None,
        expected={"structuring_field_accuracy": 0.5, "structuring_confidence_met": 0.0},
    ),
)

#: The whole set: one evaluation pass scores every example of both kinds.
GOLDEN_DATASET: tuple[
    TranscriptionExample | StructuringExample,
    ...,
] = GOLDEN_TRANSCRIPTIONS + GOLDEN_STRUCTURINGS
