"""Phase 0 harness — cross-provider comparison table (issue #11).

Throws the recorded run reports (``phase0/runs/*.json``, written by
``phase0.harness.runner.report_to_json``) side by side so the spike verdict is
apples-to-apples: same harness, same corpus, same five-number bar, per
provider. Covers the four comparison areas — transcription quality
(median/p90 WER and CER), structuring accuracy (overall field F1), flag
calibration (AMB-006 silent-error rate + flag precision/recall), and
per-intake cost.

The table is generated from the recorded run JSONs only; nothing is eyeballed
or re-scored from raw transcripts. A provider with no recorded run gets an
explicit ``no data`` row, never a guess. When a provider has several recorded
runs, the most recent (by ``generated_at``) is the row, with its run file
named so the provenance is auditable. The NIM production-licensing caveat is
surfaced in the output.

Per-intake cost is the mean, over billed clips, of the recorded per-clip cost
summed across both legs (transcribe + structure); the calls-per-intake column
restates the per-call ceiling the run itself records — Gemini's multimodal
single-call finding collapses to one call, the 2-leg pipelines (Whisper/NIM)
to two.

Throwaway research code for PHASE-0 (issue #2 / #11); not production.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from phase0.harness.providers.nim import LICENSING_CAVEAT

PROVIDER_ORDER = ("gemini", "whisper", "nim")
_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ComparisonRow:
    """One provider's apples-to-apples row; ``None`` means no recorded data.

    A missing metric (structuring on a transcription-only run, any metric for
    a provider with no run at all) is ``None`` and renders as ``no data`` —
    never a guess, never a fabricated zero.
    """

    provider: str
    model: str | None
    run_file: str | None
    generated_at: str | None
    attempted: int | None
    scored: int | None
    median_wer: float | None
    p90_wer: float | None
    median_cer: float | None
    p90_cer: float | None
    structuring_f1: float | None
    structuring_n: int | None
    silent_error_rate: float | None
    flag_precision: float | None
    flag_recall: float | None
    calibration_passes: bool | None
    per_intake_cost_inr: float | None
    calls_per_intake: int | None
    licensing_caveat: str | None


def compare_runs(runs_dir: Path) -> list[ComparisonRow]:
    """Latest recorded run per provider → one comparison row each.

    Every provider in ``PROVIDER_ORDER`` gets a row, in that order; any
    provider present in the directory but not in that order is appended
    alphabetically. A run file that is not valid JSON is a hard error — the
    directory is meant to hold only recorded run reports, so a corrupt file is
    surfaced, not silently skipped.
    """
    if not runs_dir.is_dir():
        raise ValueError(f"runs directory not found: {runs_dir}")

    runs_by_provider: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(runs_dir.glob("*.json")):
        try:
            run: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"run file {path.name} is not valid JSON: {exc}") from exc
        provider = run.get("provider")
        if isinstance(provider, str) and provider:
            runs_by_provider.setdefault(provider, []).append((path, run))

    rows: list[ComparisonRow] = []
    for provider in PROVIDER_ORDER:
        runs = runs_by_provider.get(provider, [])
        if runs:
            rows.append(_row_from_run(*_latest_run(runs)))
        else:
            rows.append(_row_without_run(provider))
    for provider in sorted(set(runs_by_provider) - set(PROVIDER_ORDER)):
        rows.append(_row_from_run(*_latest_run(runs_by_provider[provider])))
    return rows


def render_comparison(rows: list[ComparisonRow]) -> str:
    """Emit the comparison table as a markdown table plus caveats.

    The first line records the provenance (generated from the recorded run
    JSONs, never eyeballed); the caveat section surfaces every provider's
    recorded licensing caveat - NIM's production-licensing warning among them.
    """
    lines = [
        "Phase 0 provider comparison - same harness, same corpus, same metrics "
        "(generated from the recorded run JSONs, never eyeballed)",
        "",
        "| provider (model) | run | clips | median WER | p90 WER | median CER | "
        "p90 CER | struct F1 | struct n | silent err% | flag P | flag R | "
        "calib bar | cost/intake INR | calls |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: | ---: |",
        *[_render_row(row) for row in rows],
    ]
    caveats = [row.licensing_caveat for row in rows if row.licensing_caveat is not None]
    if caveats:
        lines.append("")
        lines.append("Caveats")
        lines.extend(f"- {caveat}" for caveat in dict.fromkeys(caveats))
    return "\n".join(lines)


def _latest_run(runs: list[tuple[Path, dict[str, Any]]]) -> tuple[Path, dict[str, Any]]:
    return max(runs, key=lambda pair: (_generated_at(pair[1]), pair[0].name))


def _generated_at(run: dict[str, Any]) -> datetime:
    raw = run.get("generated_at")
    if not isinstance(raw, str):
        return _EPOCH
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return _EPOCH
    # Naive timestamps are recorded as UTC by the harness; normalise so the
    # sentinel and every run sort on the same (aware) clock.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _row_without_run(provider: str) -> ComparisonRow:
    return ComparisonRow(
        provider=provider,
        model=None,
        run_file=None,
        generated_at=None,
        attempted=None,
        scored=None,
        median_wer=None,
        p90_wer=None,
        median_cer=None,
        p90_cer=None,
        structuring_f1=None,
        structuring_n=None,
        silent_error_rate=None,
        flag_precision=None,
        flag_recall=None,
        calibration_passes=None,
        per_intake_cost_inr=None,
        calls_per_intake=None,
        licensing_caveat=_nim_caveat(provider, {}),
    )


def _row_from_run(path: Path, run: dict[str, Any]) -> ComparisonRow:
    transcription = _as_dict(run.get("transcription"))
    overall = _as_dict(transcription.get("overall"))
    coverage = _as_dict(run.get("coverage"))
    structuring = _as_dict(run.get("structuring"))
    structuring_overall = _as_dict(structuring.get("overall"))
    calibration = _as_dict(run.get("calibration"))
    findings = _findings(run)

    return ComparisonRow(
        provider=str(run.get("provider")),
        model=_as_str(run.get("model")),
        run_file=path.name,
        generated_at=_as_str(run.get("generated_at")),
        attempted=_as_int(coverage.get("clips_attempted")),
        scored=_as_int(coverage.get("clips_scored")),
        median_wer=_as_float(overall.get("median_wer")),
        p90_wer=_as_float(overall.get("p90_wer")),
        median_cer=_as_float(overall.get("median_cer")),
        p90_cer=_as_float(overall.get("p90_cer")),
        structuring_f1=_as_float(structuring_overall.get("f1")),
        structuring_n=_as_int(structuring.get("scored")),
        silent_error_rate=_as_float(calibration.get("silent_error_rate")),
        flag_precision=_as_float(calibration.get("flag_precision")),
        flag_recall=_as_float(calibration.get("flag_recall")),
        calibration_passes=_as_bool(calibration.get("passes_silent_error_bar")),
        per_intake_cost_inr=_per_intake_cost(run),
        calls_per_intake=_calls_per_intake(run),
        licensing_caveat=_nim_caveat(str(run.get("provider")), findings),
    )


def _findings(run: dict[str, Any]) -> dict[str, Any]:
    """Provider findings from either schema key.

    The current harness records findings under ``provider_findings``; runs
    recorded before the schema settled used ``gemini_findings``. Reading both
    keeps older recorded runs' findings (e.g. the multimodal single-call
    probe) visible in the comparison.
    """
    merged: dict[str, Any] = {}
    for key in ("provider_findings", "gemini_findings"):
        value = run.get(key)
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _nim_caveat(provider: str, findings: dict[str, Any]) -> str | None:
    """The NIM production-licensing caveat, from the run or the constant."""
    if provider != "nim":
        return None
    recorded = findings.get("nim_licensing_caveat")
    return str(recorded) if isinstance(recorded, str) and recorded else LICENSING_CAVEAT


def _per_intake_cost(run: dict[str, Any]) -> float | None:
    """Mean recorded cost per billed clip across both legs (transcribe + structure).

    A clip is billed once it records any usage in either leg; its per-intake
    cost is the sum of both legs' usage for that clip. Failed clips recorded
    no usage and are not billed, so they neither inflate nor dilute the mean.
    """
    per_clip_cost: dict[str, float] = {}
    for row in _as_dict(run.get("transcription")).get("per_clip", []):
        _accumulate_usage(row, per_clip_cost)
    for row in _as_dict(run.get("structuring")).get("per_clip", []):
        _accumulate_usage(row, per_clip_cost)
    if not per_clip_cost:
        return None
    return round(sum(per_clip_cost.values()) / len(per_clip_cost), 4)


def _accumulate_usage(row: Any, per_clip_cost: dict[str, float]) -> None:
    if not isinstance(row, dict):
        return
    usage = row.get("usage")
    if not isinstance(usage, dict):
        return
    clip_id = row.get("clip_id")
    if not isinstance(clip_id, str) or not clip_id:
        return
    cost = usage.get("cost_inr")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        per_clip_cost[clip_id] = per_clip_cost.get(clip_id, 0.0) + float(cost)


def _calls_per_intake(run: dict[str, Any]) -> int | None:
    """The per-call ceiling the run itself records: 1 or 2 calls per intake.

    Gemini's multimodal single-call finding (recorded in ``provider_findings``
    or the legacy ``gemini_findings`` key) collapses transcribe + structure
    into one call; the 2-leg pipelines (Whisper/NIM) record structuring
    per-clip calls on top of transcription, so two. A run that never ran the
    structuring leg records one call; a run with no structuring section at all
    records no verdict (``None``).
    """
    probe = _as_dict(_findings(run).get("multimodal_single_call"))
    if probe.get("collapsed") is True:
        return 1
    structuring = _as_dict(run.get("structuring"))
    has_structure_calls = any(
        isinstance(row, dict) and isinstance(row.get("usage"), dict)
        for row in structuring.get("per_clip", [])
    )
    if has_structure_calls:
        return 2
    if structuring:
        return 1
    return None


def _render_row(row: ComparisonRow) -> str:
    label = row.provider if row.model is None else f"{row.provider} ({row.model})"
    return (
        f"| {label} | {row.run_file or 'no data'} | {_fmt_scored(row.scored, row.attempted)} | "
        f"{_fmt_3dp(row.median_wer)} | {_fmt_3dp(row.p90_wer)} | {_fmt_3dp(row.median_cer)} | "
        f"{_fmt_3dp(row.p90_cer)} | {_fmt_3dp(row.structuring_f1)} | "
        f"{_fmt_int(row.structuring_n)} | "
        f"{_fmt_percent(row.silent_error_rate)} | {_fmt_2dp(row.flag_precision)} | "
        f"{_fmt_2dp(row.flag_recall)} | {_fmt_bar(row.calibration_passes)} | "
        f"{_fmt_cost(row.per_intake_cost_inr)} | {_fmt_int(row.calls_per_intake)} |"
    )


def _fmt_scored(scored: int | None, attempted: int | None) -> str:
    if scored is None and attempted is None:
        return "no data"
    score = scored if scored is not None else "n/a"
    attempts = attempted if attempted is not None else "n/a"
    return f"{score}/{attempts}"


def _fmt_3dp(value: float | None) -> str:
    return "no data" if value is None else f"{value:.3f}"


def _fmt_2dp(value: float | None) -> str:
    return "no data" if value is None else f"{value:.2f}"


def _fmt_percent(value: float | None) -> str:
    return "no data" if value is None else f"{value * 100:.1f}%"


def _fmt_int(value: int | None) -> str:
    return "no data" if value is None else str(value)


def _fmt_cost(value: float | None) -> str:
    return "no data" if value is None else f"{value:.4f}"


def _fmt_bar(value: bool | None) -> str:
    return "no data" if value is None else ("PASS" if value else "FAIL")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
