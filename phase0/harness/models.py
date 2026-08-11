"""Phase 0 harness - typed DTOs.

Throwaway research code for the PHASE-0 Hindi voice feasibility spike
(issues #2 / #4 / #5). The dataclasses here are the request/response envelope
for the provider-agnostic gateway port that mirrors the future MOD-005 AI
gateway (transcribe → structure, typed, async), plus the structuring-leg
DTOs (field F1, calibration) added for issue #5. Nothing here is production
code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


class MedicationData(TypedDict, total=False):
    """One known-medication entry in the field set's JSON shape."""

    name: str | None
    strength: str | None
    frequency: str | None
    route: str | None
    duration: str | None
    note: str | None


class VitalsData(TypedDict, total=False):
    """The ``vitals`` block of the field set's JSON shape."""

    temperature: str | None
    blood_pressure: str | None
    pulse: str | None
    spo2: str | None
    height_cm: str | None
    weight_kg: str | None
    bmi: str | None
    other: list[str]


class PreSummaryData(TypedDict, total=False):
    """The provisional field set as the provider emits it (one JSON shape).

    Keys are optional (``total=False``) because a provider may omit fields it
    found nothing for; scoring treats a missing key as empty. ``clinical_notes``
    and ``extraction_notes`` are not part of this shape - they are reference
    metadata the provider is not asked to produce.
    """

    chief_complaint: str | None
    onset: str | None
    duration: str | None
    location: str | None
    severity: str | None
    nature: str | None
    associated_symptoms: list[str]
    aggravating_factors: list[str]
    relieving_factors: list[str]
    known_medications: list[MedicationData]
    allergies: list[str]
    past_history: list[str]
    family_history: list[str]
    vitals: VitalsData
    labs_ordered: list[str]
    diagnosis_impression: str | None
    advice: list[str]
    follow_up: str | None


FieldValue = str | None | list[str] | list[MedicationData] | VitalsData


@dataclass(frozen=True)
class Usage:
    """Per-call token and INR cost accounting, persisted with run output."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_inr: float
    latency_ms: int
    tier: str


@dataclass(frozen=True)
class TranscribeResult:
    """A provider's audio → transcript step."""

    text: str
    usage: Usage


@dataclass(frozen=True)
class StructureResult:
    """A provider's transcript → structured pre-summary step."""

    structured: PreSummaryData
    confidence: float | None
    usage: Usage


@dataclass(frozen=True)
class PerClipTranscription:
    """One clip's transcription outcome and score against ground truth."""

    clip_id: str
    cohort: str
    transcript: str
    wer: float | None
    cer: float | None
    usage: Usage | None
    error: str | None = None


@dataclass(frozen=True)
class TranscriptionSummary:
    """Aggregate WER/CER for a cohort or the whole corpus."""

    median_wer: float | None
    p90_wer: float | None
    median_cer: float | None
    p90_cer: float | None
    sample_size: int


@dataclass(frozen=True)
class FieldF1:
    """Precision/recall/F1 for one field, micro-aggregated over a clip set.

    ``reference`` is the number of ground-truth tokens for the field,
    ``hypothesis`` the number produced, ``correct`` their overlap.
    """

    field: str
    correct: int
    reference: int
    hypothesis: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class PerClipStructuring:
    """One well-formed clip's structuring outcome and score against ground truth.

    ``structured`` is the provider's raw field-set object (kept for the
    forced-review gate); ``field_f1`` holds the per-field scores; the
    ``low_confidence`` flag and ``significant_error`` mark drive the AMB-006
    calibration.
    """

    clip_id: str
    cohort: str
    structured: PreSummaryData
    confidence: float | None
    low_confidence: bool
    significant_error: bool
    field_f1: dict[str, FieldF1]
    usage: Usage | None
    error: str | None = None


@dataclass(frozen=True)
class StructuringSummary:
    """Field-level F1 aggregates over the well-formed subset."""

    per_field: dict[str, FieldF1]
    overall: FieldF1
    sample_size: int


@dataclass(frozen=True)
class CalibrationReport:
    """AMB-006 threshold calibration over the structured (well-formed) clips.

    A *silent error* is a clinically-significant field error on a pre-summary
    whose ``low_confidence`` flag did not fire. The acceptance bound is
    ``silent_error_rate <= 2%``; flag precision/recall are reported so the
    threshold can be tuned at PHASE-7.
    """

    threshold: float
    clips: int
    flagged: int
    unflagged: int
    significant_errors: int
    flagged_significant: int
    silent_errors: int
    silent_error_rate: float | None
    flag_precision: float | None
    flag_recall: float | None
    passes_silent_error_bar: bool


@dataclass(frozen=True)
class RunReport:
    """The persisted output of a harness run over a corpus."""

    provider: str
    model: str
    generated_at: str
    clips_scored: int
    clips_failed: int
    coverage: frozenset[str]
    per_clip: dict[str, PerClipTranscription]
    per_cohort_wer: dict[str, TranscriptionSummary]
    overall_wer: TranscriptionSummary
    bar_passes: bool
    bar_failures: list[str]
    totals: Usage
    provider_findings: dict[str, Any] = field(default_factory=dict)
    per_clip_structuring: dict[str, PerClipStructuring] = field(default_factory=dict)
    structuring: StructuringSummary | None = None
    structuring_bar_passes: bool = False
    structuring_bar_failures: list[str] = field(default_factory=list)
    calibration: CalibrationReport | None = None
    gate_validated: bool = False
    structuring_skipped: bool = False

    def scored_clip_ids(self) -> set[str]:
        return {clip_id for clip_id, row in self.per_clip.items() if row.error is None}


def totals_usage(usages: list[Usage]) -> Usage:
    """Fold a list of per-call usages into one aggregate Usage row."""
    provider = usages[0].provider if usages else "n/a"
    model = usages[0].model if usages else "n/a"
    return Usage(
        provider=provider,
        model=model,
        input_tokens=sum(usage.input_tokens for usage in usages),
        output_tokens=sum(usage.output_tokens for usage in usages),
        cost_inr=round(sum(usage.cost_inr for usage in usages), 4),
        latency_ms=0,
        tier=usages[0].tier if usages else "n/a",
    )
