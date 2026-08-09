"""Phase 0 harness — run orchestration (issues #4 / #5).

Drives a provider over the corpus, scores the transcription leg of the
acceptance bar (WER/CER per clip → median/p90 per cohort and overall),
then runs the structuring leg on the well-formed subset: field-level F1 vs.
the ground-truth pre-summaries, the AMB-006 calibration (low-confidence flag
at 0.70, silent-error bound <= 2%, flag precision/recall), and the
forced-review gate validation. Tokens + INR per call are recorded and the
run output is persisted as JSON.

Throwaway research code for PHASE-0 (issue #2 / #4 / #5); not production.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from phase0.harness.gate import PreSummaryRecord, validate_gate_semantics
from phase0.harness.gateway import Gateway
from phase0.harness.metrics import (
    SILENT_ERROR_RATE_CEILING,
    STRUCTURING_F1_TARGET,
    aggregate_structuring,
    calibrate,
    evaluate_structuring_bar,
    evaluate_transcription_bar,
    f1_scored_fields,
    has_clinically_significant_error,
    is_well_formed,
    low_confidence,
    pre_summary_to_plain,
    score_clip,
    score_structuring,
    summarize,
)
from phase0.harness.models import (
    CalibrationReport,
    FieldF1,
    PerClipStructuring,
    PerClipTranscription,
    RunReport,
    StructuringSummary,
    TranscriptionSummary,
    Usage,
    totals_usage,
)
from phase0.loader import Clip, Corpus, PreSummary

_T = TypeVar("_T")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _gather_guarded(
    clip_ids: Iterable[str],
    concurrency: int,
    make_coro: Callable[[str], Awaitable[_T]],
) -> list[_T]:
    """Run one coroutine per clip id under a shared concurrency cap.

    Provider free tiers rate-limit hard; serializing by default keeps a corpus
    run from tripping the quota on the first concurrent burst.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _guarded(clip_id: str) -> _T:
        async with semaphore:
            return await make_coro(clip_id)

    return list(await asyncio.gather(*(_guarded(clip_id) for clip_id in clip_ids)))


async def _transcribe_clip(gateway: Gateway, clip: Clip) -> PerClipTranscription:
    reference = clip.transcript_path.read_text(encoding="utf-8")
    try:
        result = await gateway.transcribe(clip.audio_path, clip.clip_id)
    except Exception as exc:  # a provider failure must not sink the whole run
        return PerClipTranscription(
            clip_id=clip.clip_id,
            cohort=clip.cohort,
            transcript="",
            wer=None,
            cer=None,
            usage=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    scored = score_clip(clip.clip_id, reference, result.text)
    return PerClipTranscription(
        clip_id=clip.clip_id,
        cohort=clip.cohort,
        transcript=result.text,
        wer=scored.wer,
        cer=scored.cer,
        usage=result.usage,
    )


async def _run_corpus(
    gateway: Gateway,
    corpus: Corpus,
    clip_ids: frozenset[str],
    concurrency: int,
) -> dict[str, PerClipTranscription]:
    clips_by_id = corpus.clip_by_id()
    rows = await _gather_guarded(
        clip_ids,
        concurrency,
        lambda clip_id: _transcribe_clip(gateway, clips_by_id[clip_id]),
    )
    return {row.clip_id: row for row in rows}


async def _structure_clip(
    gateway: Gateway,
    clip: Clip,
    summary: PreSummary,
    scored_fields: tuple[str, ...],
    transcript: str,
) -> PerClipStructuring:
    reference = pre_summary_to_plain(summary)
    try:
        result = await gateway.structure(transcript, clip.clip_id)
    except Exception as exc:  # a provider failure must not sink the whole run
        # A provider failure produces no output: nothing clinically-significant
        # was *asserted*, so this is not a significant error — it is an error
        # row (excluded from calibration) and flagged as low-confidence.
        return PerClipStructuring(
            clip_id=clip.clip_id,
            cohort=clip.cohort,
            structured={},
            confidence=None,
            low_confidence=True,
            significant_error=False,
            field_f1={},
            usage=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    if not any(field in result.structured for field in scored_fields):
        return PerClipStructuring(
            clip_id=clip.clip_id,
            cohort=clip.cohort,
            structured=result.structured,
            confidence=result.confidence,
            low_confidence=low_confidence(result.confidence),
            significant_error=False,
            field_f1={},
            usage=result.usage,
            error="provider returned no structured fields",
        )
    scores = score_structuring(reference, result.structured, scored_fields)
    return PerClipStructuring(
        clip_id=clip.clip_id,
        cohort=clip.cohort,
        structured=result.structured,
        confidence=result.confidence,
        low_confidence=low_confidence(result.confidence),
        significant_error=has_clinically_significant_error(scores),
        field_f1=scores,
        usage=result.usage,
    )


async def _run_structuring(
    gateway: Gateway,
    corpus: Corpus,
    clip_ids: frozenset[str],
    transcripts_by_id: dict[str, str],
    concurrency: int,
) -> dict[str, PerClipStructuring]:
    clips_by_id = corpus.clip_by_id()
    summaries_by_id = corpus.pre_summary_by_id()
    scored_fields = f1_scored_fields(corpus.field_set.fields)
    rows = await _gather_guarded(
        clip_ids,
        concurrency,
        lambda clip_id: _structure_clip(
            gateway,
            clips_by_id[clip_id],
            summaries_by_id[clip_id],
            scored_fields,
            transcripts_by_id[clip_id],
        ),
    )
    return {row.clip_id: row for row in rows}


def _to_gate_record(row: PerClipStructuring) -> PreSummaryRecord:
    return PreSummaryRecord(
        clip_id=row.clip_id, confidence=row.confidence, structured=row.structured
    )


def _aggregate(
    per_clip: dict[str, PerClipTranscription],
) -> dict[str, dict[str, list[float]]]:
    cohort_names = sorted({row.cohort for row in per_clip.values() if row.error is None})
    wer_by_cohort: dict[str, list[float]] = {cohort: [] for cohort in cohort_names}
    cer_by_cohort: dict[str, list[float]] = {cohort: [] for cohort in cohort_names}
    for row in per_clip.values():
        if row.error is None and row.wer is not None and row.cer is not None:
            wer_by_cohort[row.cohort].append(row.wer)
            cer_by_cohort[row.cohort].append(row.cer)
    return {"wer_by_cohort": wer_by_cohort, "cer_by_cohort": cer_by_cohort}


def _summaries(
    wer_by_cohort: dict[str, list[float]],
    cer_by_cohort: dict[str, list[float]],
) -> dict[str, TranscriptionSummary]:
    return {
        cohort: summarize(wer_by_cohort[cohort], cer_by_cohort[cohort])
        for cohort in sorted(wer_by_cohort)
    }


def run_corpus(
    gateway: Gateway,
    corpus: Corpus,
    clip_ids: Iterable[str] | None = None,
    output_path: Path | None = None,
    gemini_findings: dict[str, Any] | None = None,
    concurrency: int = 1,
    structure: bool = True,
) -> RunReport:
    """Run both legs of the acceptance bar over (a subset of) the corpus.

    ``clip_ids`` defaults to the whole corpus. When ``output_path`` is given
    the full report is written as JSON alongside the returned object.
    ``concurrency`` caps the number of in-flight provider calls (default 1 to
    stay inside free-tier rate limits).

    The structuring leg (issue #5) runs only on the well-formed subset — the
    clips whose transcription WER cleared ``TRANSCRIPTION_FLOOR_WER`` — so
    extraction is scored without punishing it for ASR failures. Pass
    ``structure=False`` for a transcription-only run.
    """
    known = frozenset(clip.clip_id for clip in corpus.clips)
    selected = frozenset(clip_ids) if clip_ids is not None else known
    unknown = selected - known
    if unknown:
        raise ValueError(f"unknown clip ids: {sorted(unknown)}")

    per_clip = asyncio.run(_run_corpus(gateway, corpus, selected, concurrency))

    scored_rows = [row for row in per_clip.values() if row.error is None and row.wer is not None]
    wer_values = [row.wer for row in scored_rows if row.wer is not None]
    cer_values = [row.cer for row in scored_rows if row.cer is not None]
    overall = summarize(wer_values, cer_values)

    grouped = _aggregate(per_clip)
    per_cohort = _summaries(grouped["wer_by_cohort"], grouped["cer_by_cohort"])

    passes, failures = evaluate_transcription_bar(overall, per_cohort)

    well_formed = frozenset(clip_id for clip_id, row in per_clip.items() if is_well_formed(row.wer))
    per_clip_structuring: dict[str, PerClipStructuring] = {}
    structuring: StructuringSummary | None = None
    structuring_passes = False
    structuring_failures: list[str] = []
    calibration: CalibrationReport | None = None
    gate_validated = False
    if structure:
        transcripts_by_id = {clip_id: row.transcript for clip_id, row in per_clip.items()}
        per_clip_structuring = asyncio.run(
            _run_structuring(
                gateway,
                corpus,
                well_formed,
                transcripts_by_id,
                concurrency,
            )
        )
        structuring_rows = [row for row in per_clip_structuring.values() if row.error is None]
        structuring = (
            aggregate_structuring([row.field_f1 for row in structuring_rows])
            if structuring_rows
            else None
        )
        structuring_passes, structuring_failures = evaluate_structuring_bar(structuring)
        calibration = calibrate(structuring_rows) if structuring_rows else None
        gate_validated = validate_gate_semantics(
            [_to_gate_record(row) for row in structuring_rows],
            reviewed_at=_utc_now_iso(),
        )

    usages = [row.usage for row in per_clip.values() if row.usage is not None]
    totals = totals_usage(usages)
    report = RunReport(
        provider=gateway.name,
        model=getattr(gateway, "model", gateway.name),
        generated_at=_utc_now_iso(),
        clips_scored=len(scored_rows),
        clips_failed=sum(1 for row in per_clip.values() if row.error is not None),
        coverage=selected,
        per_clip=per_clip,
        per_cohort_wer=per_cohort,
        overall_wer=overall,
        bar_passes=passes,
        bar_failures=failures,
        totals=totals,
        gemini_findings=gemini_findings or {},
        per_clip_structuring=per_clip_structuring,
        structuring=structuring,
        structuring_bar_passes=structuring_passes,
        structuring_bar_failures=structuring_failures,
        calibration=calibration,
        gate_validated=gate_validated,
        structuring_skipped=not structure,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(report_to_json(report), ensure_ascii=False, indent=2)
        output_path.write_text(serialized, encoding="utf-8")
    return report


def report_to_json(report: RunReport) -> dict[str, Any]:
    """Serialize a RunReport for persistence (mirrors the schema in phase0/README)."""
    return {
        "provider": report.provider,
        "model": report.model,
        "generated_at": report.generated_at,
        "coverage": {
            "clips_attempted": len(report.coverage),
            "clips_scored": report.clips_scored,
            "clips_failed": report.clips_failed,
        },
        "transcription": {
            "per_clip": [
                {
                    "clip_id": row.clip_id,
                    "cohort": row.cohort,
                    "wer": row.wer,
                    "cer": row.cer,
                    "error": row.error,
                    "usage": _usage_to_json(row.usage),
                }
                for row in report.per_clip.values()
            ],
            "per_cohort": {
                cohort: _summary_to_json(summary)
                for cohort, summary in sorted(report.per_cohort_wer.items())
            },
            "overall": _summary_to_json(report.overall_wer),
            "acceptance_bar": {
                "passes": report.bar_passes,
                "failures": report.bar_failures,
            },
        },
        "structuring": _structuring_to_json(report),
        "calibration": _calibration_to_json(report.calibration),
        "gate_validated": report.gate_validated,
        "totals": _usage_to_json(report.totals),
        "gemini_findings": _findings_to_json(report.gemini_findings),
    }


def _structuring_to_json(report: RunReport) -> dict[str, Any]:
    return {
        "skipped": report.structuring_skipped,
        "well_formed": len(report.per_clip_structuring),
        "scored": report.structuring.sample_size if report.structuring else 0,
        "per_clip": [
            {
                "clip_id": row.clip_id,
                "cohort": row.cohort,
                "confidence": row.confidence,
                "low_confidence": row.low_confidence,
                "significant_error": row.significant_error,
                "field_f1": _field_f1_map_to_json(row.field_f1),
                "error": row.error,
                "usage": _usage_to_json(row.usage),
            }
            for row in report.per_clip_structuring.values()
        ],
        "per_field": (
            _field_f1_map_to_json(report.structuring.per_field) if report.structuring else {}
        ),
        "overall": _field_f1_to_json(report.structuring.overall) if report.structuring else None,
        "acceptance_bar": {
            "passes": report.structuring_bar_passes,
            "failures": report.structuring_bar_failures,
            "target": STRUCTURING_F1_TARGET,
        },
    }


def _calibration_to_json(calibration: CalibrationReport | None) -> dict[str, Any] | None:
    if calibration is None:
        return None
    return {
        "threshold": calibration.threshold,
        "clips": calibration.clips,
        "flagged": calibration.flagged,
        "unflagged": calibration.unflagged,
        "significant_errors": calibration.significant_errors,
        "flagged_significant": calibration.flagged_significant,
        "silent_errors": calibration.silent_errors,
        "silent_error_rate": calibration.silent_error_rate,
        "flag_precision": calibration.flag_precision,
        "flag_recall": calibration.flag_recall,
        "passes_silent_error_bar": calibration.passes_silent_error_bar,
        "silent_error_ceiling": SILENT_ERROR_RATE_CEILING,
    }


def _field_f1_map_to_json(scores: dict[str, FieldF1]) -> dict[str, dict[str, float]]:
    return {field: _field_f1_to_json(score) for field, score in sorted(scores.items())}


def _field_f1_to_json(score: FieldF1) -> dict[str, float]:
    return {
        "correct": score.correct,
        "reference": score.reference,
        "hypothesis": score.hypothesis,
        "precision": score.precision,
        "recall": score.recall,
        "f1": score.f1,
    }


def _findings_to_json(findings: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy findings replacing any Usage objects with their JSON shape."""
    serialized: dict[str, Any] = {}
    for key, value in findings.items():
        if isinstance(value, Usage):
            serialized[key] = _usage_to_json(value)
        elif isinstance(value, dict):
            serialized[key] = _findings_to_json(value)
        else:
            serialized[key] = value
    return serialized


def _usage_to_json(usage: Usage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_inr": usage.cost_inr,
        "tier": usage.tier,
        "latency_ms": usage.latency_ms,
    }


def _summary_to_json(summary: TranscriptionSummary) -> dict[str, Any]:
    return {
        "median_wer": summary.median_wer,
        "p90_wer": summary.p90_wer,
        "median_cer": summary.median_cer,
        "p90_cer": summary.p90_cer,
        "sample_size": summary.sample_size,
    }
