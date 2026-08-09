"""Phase 0 harness — CLI entrypoint (issue #4).

Runs the transcription leg of the acceptance bar over the committed corpus
through a provider and persists a JSON run report. Live provider runs are
gated on the provider's API key; the metrics/runner itself is deterministic
and unit-tested without network.

Examples:
    python -m phase0.harness --provider gemini --limit 3
    python -m phase0.harness --provider gemini --cohort heavy_local
    python -m phase0.harness --provider gemini --output phase0/runs/mine.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from phase0.harness.models import RunReport
from phase0.harness.providers.gemini import GeminiProvider
from phase0.harness.runner import run_corpus
from phase0.loader import load_corpus


def _provider_from_cli(args: argparse.Namespace) -> GeminiProvider:
    if args.provider == "gemini":
        return GeminiProvider(
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff,
            quota_backoff_seconds=args.quota_backoff,
        )
    raise SystemExit(f"unknown provider: {args.provider}")


def _print_summary(report: RunReport, output: Path) -> None:
    print(f"provider:      {report.provider} ({report.model})")
    print(f"scored:        {report.clips_scored}  failed: {report.clips_failed}")
    print("transcription bar: " + ("PASS" if report.bar_passes else "FAIL"))
    for failure in report.bar_failures:
        print(f"  - {failure}")
    for cohort, summary in sorted(report.per_cohort_wer.items()):
        print(
            f"  {cohort:<14} n={summary.sample_size:<3} median_wer={summary.median_wer} "
            f"p90_wer={summary.p90_wer} median_cer={summary.median_cer} p90_cer={summary.p90_cer}"
        )
    overall = report.overall_wer
    print(
        f"  {'overall':<14} n={overall.sample_size:<3} median_wer={overall.median_wer} "
        f"p90_wer={overall.p90_wer} median_cer={overall.median_cer} p90_cer={overall.p90_cer}"
    )
    print(
        f"tokens:        in={report.totals.input_tokens} out={report.totals.output_tokens} "
        f"cost_inr={report.totals.cost_inr} tier={report.totals.tier}"
    )
    print(f"report:        {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CareSetu Phase 0 evaluation harness")
    parser.add_argument("--provider", default="gemini", choices=["gemini"])
    parser.add_argument("--limit", type=int, default=None, help="max clips to score")
    parser.add_argument(
        "--cohort", action="append", default=[], help="score only this cohort (repeatable)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="run output path (default phase0/runs/<run>.json)",
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="skip the Gemini single-call multimodal probe",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="max in-flight provider calls (default 1 to respect free-tier quotas)",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="provider retries per call")
    parser.add_argument(
        "--retry-backoff", type=float, default=1.5, help="transient retry backoff (s)"
    )
    parser.add_argument(
        "--quota-backoff",
        type=float,
        default=30.0,
        help="settle time on HTTP 429 quota errors (s)",
    )
    args = parser.parse_args()

    corpus = load_corpus()
    selected = [clip.clip_id for clip in corpus.clips]
    if args.cohort:
        allowed = set(args.cohort)
        selected = [clip.clip_id for clip in corpus.clips if clip.cohort in allowed]
    if args.limit is not None:
        selected = selected[: args.limit]
    if not selected:
        print("no clips selected", file=sys.stderr)
        raise SystemExit(1)

    provider = _provider_from_cli(args)

    findings: dict[str, Any] = {}
    probe_usage = None
    if args.provider == "gemini" and not args.no_probe and selected:
        probe_clip = corpus.clips[0]
        probe = asyncio.run(provider.probe_single_call(probe_clip.audio_path, probe_clip.clip_id))
        findings["multimodal_single_call"] = probe
        probe_usage = probe.get("usage")

    if args.output is None:
        run_dir = Path(__file__).resolve().parents[1] / "runs"
        args.output = run_dir / f"{report_timestamp()}.json"

    report = run_corpus(
        gateway=provider,
        corpus=corpus,
        clip_ids=selected,
        output_path=args.output,
        gemini_findings=findings,
        concurrency=args.concurrency,
    )
    _print_summary(report, args.output)
    if probe_usage is not None and args.provider == "gemini":
        print(f"probe usage:   in={probe_usage.input_tokens} out={probe_usage.output_tokens}")


def report_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()
