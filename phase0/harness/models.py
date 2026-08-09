"""Phase 0 harness — typed DTOs.

Throwaway research code for the PHASE-0 Hindi voice feasibility spike
(issue #2 / #4). The dataclasses here are the request/response envelope for
the provider-agnostic gateway port that mirrors the future MOD-005 AI gateway
(transcribe → structure, typed, async). Nothing here is production code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    structured: dict[str, Any]
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
    gemini_findings: dict[str, Any] = field(default_factory=dict)

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
