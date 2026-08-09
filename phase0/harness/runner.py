"""Phase 0 harness — run orchestration (issue #4).

Drives a provider over the corpus, scores the transcription leg of the
acceptance bar (WER/CER per clip → median/p90 per cohort and overall),
records tokens + INR per call, and persists the run output as JSON.

Throwaway research code for PHASE-0 (issue #2 / #4); not production.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from phase0.harness.gateway import Gateway
from phase0.harness.metrics import evaluate_transcription_bar, score_clip, summarize
from phase0.harness.models import (
    PerClipTranscription,
    RunReport,
    TranscriptionSummary,
    Usage,
    totals_usage,
)
from phase0.loader import Corpus


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _transcribe_clip(gateway: Gateway, corpus: Corpus, clip_id: str) -> PerClipTranscription:
    by_id = {clip.clip_id: clip for clip in corpus.clips}
    clip = by_id[clip_id]
    reference = clip.transcript_path.read_text(encoding="utf-8")
    try:
        result = await gateway.transcribe(clip.audio_path, clip_id)
    except Exception as exc:  # a provider failure must not sink the whole run
        return PerClipTranscription(
            clip_id=clip_id,
            cohort=clip.cohort,
            transcript="",
            wer=None,
            cer=None,
            usage=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    scored = score_clip(clip_id, reference, result.text)
    return PerClipTranscription(
        clip_id=clip_id,
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
    # Provider free tiers rate-limit hard; serialize by default so a corpus run
    # does not trip the quota on the first concurrent burst.
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _guarded(clip_id: str) -> PerClipTranscription:
        async with semaphore:
            return await _transcribe_clip(gateway, corpus, clip_id)

    rows = await asyncio.gather(*(_guarded(clip_id) for clip_id in clip_ids))
    return {row.clip_id: row for row in rows}


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
) -> RunReport:
    """Run the transcription leg over (a subset of) the corpus and score it.

    ``clip_ids`` defaults to the whole corpus. When ``output_path`` is given
    the full report is written as JSON alongside the returned object.
    ``concurrency`` caps the number of in-flight provider calls (default 1 to
    stay inside free-tier rate limits).
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
        "totals": _usage_to_json(report.totals),
        "gemini_findings": _findings_to_json(report.gemini_findings),
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
    }


def _summary_to_json(summary: TranscriptionSummary) -> dict[str, Any]:
    return {
        "median_wer": summary.median_wer,
        "p90_wer": summary.p90_wer,
        "median_cer": summary.median_cer,
        "p90_cer": summary.p90_cer,
        "sample_size": summary.sample_size,
    }
