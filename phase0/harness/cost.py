"""Phase 0 harness - launch-phase cost model and spike report (issue #12).

Reads the recorded run JSONs (``phase0/runs/*.json``, written by
``phase0.harness.runner.report_to_json``) and derives the launch-phase cost
model per provider: per-intake INR cost and tokens from the recorded usage,
extrapolated to KPI-001 volume (~200 intakes + ~200 rx-drafts/month, ~600 AI
calls) against the launch-phase constraints - AI budget slice <= INR
600/month at KPI-001 volume with >= 3x headroom, per-intake <= INR 2.00,
rx-draft <= INR 1.00. Emits the spike report: transcription quality metric,
Hindi structuring accuracy, per-call INR/tokens, provider selection,
validated AMB-006 threshold, and the go/no-go verdict applied mechanically.

Costs come from recorded tokens + price, never eyeballed; a breach is
reported with its reason, not papered over. The rx-draft call has no corpus
in the spike (no rx-draft ground truth exists), so its per-call cost is
estimated from the recorded structuring-class per-call usage - the closest
recorded real-usage analog. Where a run records no structuring usage the
estimate has no basis and the ceiling is reported *unverified*, never
fabricated.

The go/no-go rule is the pre-decided mechanical rule (issue #2): all five
bar items hold -> GO; the transcription floor fails -> NO-GO with the
text-first intake fallback; structuring/calibration fails while
transcription passes -> threshold-tune. A cost-ceiling breach while every
quality bar holds is its own NO-GO (the budget is a hard launch
constraint), and a missing bar measurement is *unverified*, never a vacuous
pass.

Throwaway research code for PHASE-0 (issue #2 / #12); not production.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from phase0.harness.compare import PROVIDER_ORDER, _calls_per_intake
from phase0.harness.metrics import AMB_006_THRESHOLD

# KPI-001 launch-phase volume (issue #2): ~200 loops/month -> ~200 intakes +
# ~200 rx-drafts -> ~600 AI calls/month as the extrapolation denominator.
INTAKES_PER_MONTH = 200
RX_DRAFTS_PER_MONTH = 200

# Launch-phase budget (issue #2, user story 16-18): the AI slice is a hard
# ceiling of the INR 2,000 NFR-001 cap, per-intake and rx-draft ceilings are
# per-intake (not per-call) so Gemini's single-call collapse never breaks them.
AI_SLICE_INR_PER_MONTH = 600.0
MIN_HEADROOM_X = 3.0
PER_INTAKE_CEILING_INR = 2.00
RX_DRAFT_CEILING_INR = 1.00

_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class MonthlyVolume:
    """KPI-001 monthly volume the cost model extrapolates to."""

    intakes: int = INTAKES_PER_MONTH
    rx_drafts: int = RX_DRAFTS_PER_MONTH


@dataclass(frozen=True)
class LaunchBudget:
    """Launch-phase AI budget constraints (issue #2)."""

    ai_slice_inr: float = AI_SLICE_INR_PER_MONTH
    min_headroom_x: float = MIN_HEADROOM_X
    per_intake_ceiling_inr: float = PER_INTAKE_CEILING_INR
    rx_draft_ceiling_inr: float = RX_DRAFT_CEILING_INR


class GoNoGo(StrEnum):
    """The mechanical go/no-go verdicts (issue #2).

    ``GO`` requires all five bar items to hold. The two named failure
    branches are ``NO_GO_TEXT_FIRST`` (transcription floor fails) and
    ``THRESHOLD_TUNE`` (structuring/calibration fails while transcription
    passes). A cost-ceiling breach while every quality bar holds is
    ``NO_GO_COST``, a missing measurement is ``INCONCLUSIVE`` (never a vacuous
    pass), and a directory with no recorded runs is ``NO_DATA``.
    """

    GO = "GO"
    NO_GO_TEXT_FIRST = "NO-GO: text-first intake fallback"
    THRESHOLD_TUNE = "threshold-tune"
    NO_GO_COST = "NO-GO: cost ceiling breach"
    INCONCLUSIVE = "inconclusive: bar not fully measurable"
    NO_DATA = "no-data: no recorded runs"


DEFAULT_VOLUME = MonthlyVolume()
DEFAULT_BUDGET = LaunchBudget()


@dataclass(frozen=True)
class ProviderCost:
    """The cost model for one provider, derived from its recorded run(s).

    ``None`` means no recorded data (or, for ``rx_draft_cost_inr``, no
    recorded basis for the estimate). ``breaches`` holds hard constraint
    violations each with its reason; ``unverified`` holds constraints that
    could not be checked - neither is fabricated.
    """

    provider: str
    model: str | None
    run_file: str | None
    generated_at: str | None
    attempted: int | None
    scored: int | None
    transcription_passes: bool | None
    transcription_failures: tuple[str, ...]
    median_wer: float | None
    p90_wer: float | None
    structuring_f1: float | None
    structuring_passes: bool | None
    calibration_threshold: float | None
    calibration_passes: bool | None
    per_intake_cost_inr: float | None
    per_call_cost_inr: float | None
    input_tokens_per_intake: float | None
    output_tokens_per_intake: float | None
    input_tokens_per_call: float | None
    output_tokens_per_call: float | None
    calls_per_intake: int | None
    monthly_ai_calls: int | None
    rx_draft_cost_inr: float | None
    monthly_ai_cost_inr: float | None
    headroom_x: float | None
    breaches: tuple[str, ...]
    unverified: tuple[str, ...]


@dataclass(frozen=True)
class SpikeReport:
    """The full spike report: per-provider model, selection, and verdict."""

    generated_at: str
    runs_dir: str
    per_provider: tuple[ProviderCost, ...]
    selected: ProviderCost | None
    verdict: GoNoGo
    verdict_reason: str
    volume: MonthlyVolume
    budget: LaunchBudget


def build_spike_report(
    runs_dir: Path,
    volume: MonthlyVolume = DEFAULT_VOLUME,
    budget: LaunchBudget = DEFAULT_BUDGET,
) -> SpikeReport:
    """Build the spike report from the recorded run JSONs in ``runs_dir``.

    Mirrors ``compare_runs`` for run discovery: latest recorded run per
    provider in ``PROVIDER_ORDER``, a corrupt run file is a hard error, a
    provider with no run is absent from the model (not a fabricated row).
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

    per_provider: list[ProviderCost] = []
    for provider in PROVIDER_ORDER:
        runs = runs_by_provider.get(provider)
        if runs:
            per_provider.append(_cost_from_run(*_latest_run(runs), volume, budget))
    for provider in sorted(set(runs_by_provider) - set(PROVIDER_ORDER)):
        runs = runs_by_provider[provider]
        per_provider.append(_cost_from_run(*_latest_run(runs), volume, budget))

    selected = _select_provider(per_provider)
    verdict, reason = _verdict(selected, budget)
    return SpikeReport(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        runs_dir=str(runs_dir),
        per_provider=tuple(per_provider),
        selected=selected,
        verdict=verdict,
        verdict_reason=reason,
        volume=volume,
        budget=budget,
    )


def render_spike_report(report: SpikeReport) -> str:
    """Render the spike report as markdown (the Phase 0 decision record).

    Every number is read from the recorded run JSONs (provenance first
    line); a constraint verdict is PASS, BREACH (with reason), or unverified
    (with reason) - never silent.
    """
    runs_dir = report.runs_dir.replace("\\", "/")
    lines = [
        "# CareSetu Phase 0 spike report - cost model & go/no-go",
        "",
        f"Generated {report.generated_at} from the recorded run JSONs in "
        f"`{runs_dir}` - costs and bar results are read from the recorded "
        "runs, never eyeballed or re-scored.",
        "",
        "## Go/no-go verdict (mechanical)",
        "",
        f"- **Verdict:** {report.verdict.value}",
        f"- **Selected provider:** "
        f"{_provider_label(report.selected) if report.selected else 'none'}",
        f"- **Rule applied:** {report.verdict_reason}",
        "",
        "## Per-provider model",
        "",
        "| provider (model) | run | clips | WER bar | median/p90 WER | struct F1 | "
        "AMB-006 calib | per-intake INR | per-call INR | in/out tokens | "
        "in/out tok/call | calls | AI calls/mo | rx-draft INR (est) | "
        "monthly INR | headroom |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: | ---: | ---: |",
        *[_render_provider_row(cost) for cost in report.per_provider],
    ]
    if report.per_provider:
        lines.extend(
            [
                "",
                "## Constraint verification (KPI-001 volume: ~200 intakes + ~200 "
                "rx-drafts/month, ~600 AI calls at 2 calls/intake)",
                "",
            ]
        )
        for cost in report.per_provider:
            lines.extend(_render_constraints(cost, report.budget, report.volume))
    lines.extend(["", "## Provider selection", ""])
    lines.append(
        _select_explanation(report)
        if report.selected
        else "- No provider has a recorded run; provider selection is undecided."
    )
    lines.extend(["", "## AMB-006 threshold", ""])
    threshold = (
        report.selected.calibration_threshold if report.selected is not None else AMB_006_THRESHOLD
    )
    lines.append(
        f"- **Threshold:** {threshold:.2f} (pinned constant; validated by "
        "calibration on the recorded run)."
    )
    if report.selected is not None and report.selected.calibration_passes is not None:
        lines.append(
            "- **Validated:** " + ("PASS" if report.selected.calibration_passes else "FAIL")
        )
    else:
        lines.append(
            "- **Validated:** unverified - no calibration section in the "
            "recorded run (never a vacuous pass)."
        )
    lines.extend(["", "## Caveats", ""])
    lines.extend(_render_caveats(report))
    return "\n".join(lines)


def _cost_from_run(
    path: Path,
    run: dict[str, Any],
    volume: MonthlyVolume,
    budget: LaunchBudget,
) -> ProviderCost:
    transcription = _as_dict(run.get("transcription"))
    coverage = _as_dict(run.get("coverage"))
    structuring = _as_dict(run.get("structuring"))
    calibration = _as_dict(run.get("calibration"))
    bar = _as_dict(transcription.get("acceptance_bar"))
    structuring_bar = _as_dict(structuring.get("acceptance_bar"))
    structuring_overall = _as_dict(structuring.get("overall"))
    transcription_overall = _as_dict(transcription.get("overall"))
    usage_by_clip = _usage_by_clip(run)

    per_intake_cost = _mean_clip(usage_by_clip, "cost")
    in_per_intake = _mean_clip(usage_by_clip, "in")
    out_per_intake = _mean_clip(usage_by_clip, "out")
    calls = _calls_per_intake(run)
    per_call_cost = (
        round(per_intake_cost / calls, 4)
        if per_intake_cost is not None and calls is not None
        else None
    )
    in_per_call = (
        round(in_per_intake / calls, 4) if in_per_intake is not None and calls is not None else None
    )
    out_per_call = (
        round(out_per_intake / calls, 4)
        if out_per_intake is not None and calls is not None
        else None
    )
    monthly_calls = volume.intakes * calls + volume.rx_drafts if calls is not None else None
    rx_draft_cost = _rx_draft_estimate(run)
    monthly_ai = _monthly_ai_cost(per_intake_cost, rx_draft_cost, volume)
    headroom = None if monthly_ai is None else budget.ai_slice_inr / monthly_ai

    breaches: list[str] = []
    unverified: list[str] = []
    _check_ceiling(
        "per-intake",
        per_intake_cost,
        budget.per_intake_ceiling_inr,
        "per-intake cost (mean over billed clips, both legs)",
        breaches,
        unverified,
    )
    _check_ceiling(
        "rx-draft",
        rx_draft_cost,
        budget.rx_draft_ceiling_inr,
        "rx-draft estimate (mean structuring-class call, no rx-draft corpus exists)",
        breaches,
        unverified,
    )
    _check_slice_and_headroom(monthly_ai, headroom, budget, volume, breaches, unverified)

    return ProviderCost(
        provider=str(run.get("provider")),
        model=_as_str(run.get("model")),
        run_file=path.name,
        generated_at=_as_str(run.get("generated_at")),
        attempted=_as_int(coverage.get("clips_attempted")),
        scored=_as_int(coverage.get("clips_scored")),
        transcription_passes=_as_bool(bar.get("passes")),
        transcription_failures=tuple(str(f) for f in bar.get("failures", []) if isinstance(f, str)),
        median_wer=_as_float(transcription_overall.get("median_wer")),
        p90_wer=_as_float(transcription_overall.get("p90_wer")),
        structuring_f1=_as_float(structuring_overall.get("f1")),
        structuring_passes=_as_bool(structuring_bar.get("passes")),
        calibration_threshold=_as_float(calibration.get("threshold")) or AMB_006_THRESHOLD,
        calibration_passes=_as_bool(calibration.get("passes_silent_error_bar")),
        per_intake_cost_inr=per_intake_cost,
        per_call_cost_inr=per_call_cost,
        input_tokens_per_intake=in_per_intake,
        output_tokens_per_intake=out_per_intake,
        input_tokens_per_call=in_per_call,
        output_tokens_per_call=out_per_call,
        calls_per_intake=calls,
        monthly_ai_calls=monthly_calls,
        rx_draft_cost_inr=rx_draft_cost,
        monthly_ai_cost_inr=monthly_ai,
        headroom_x=headroom,
        breaches=tuple(breaches),
        unverified=tuple(unverified),
    )


def _usage_by_clip(run: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Per-clip cost + token totals summed across both legs (transcribe + structure).

    A clip is billed once it records usage in either leg; failed clips
    recorded no usage and are not billed, so they neither inflate nor dilute
    the means.
    """
    per_clip: dict[str, dict[str, float]] = {}
    for leg in ("transcription", "structuring"):
        for row in _as_dict(run.get(leg)).get("per_clip", []):
            if not isinstance(row, dict):
                continue
            clip_id = row.get("clip_id")
            usage = row.get("usage")
            if not isinstance(clip_id, str) or not clip_id or not isinstance(usage, dict):
                continue
            entry = per_clip.setdefault(clip_id, {"cost": 0.0, "in": 0.0, "out": 0.0})
            for key, dest in (
                ("cost_inr", "cost"),
                ("input_tokens", "in"),
                ("output_tokens", "out"),
            ):
                value = usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    entry[dest] += float(value)
    return per_clip


def _mean_clip(usage_by_clip: dict[str, dict[str, float]], key: str) -> float | None:
    """Mean of one usage component over the billed clips, rounded for output."""
    if not usage_by_clip:
        return None
    mean = sum(entry[key] for entry in usage_by_clip.values()) / len(usage_by_clip)
    return round(mean, 4)


def _rx_draft_estimate(run: dict[str, Any]) -> float | None:
    """Estimate the per-call rx-draft cost from the recorded structuring leg.

    The spike has no rx-draft corpus, so the estimate's basis is the mean
    cost of a recorded structuring-class call - the closest real-usage
    analog (text in, structured text out). No structuring usage recorded =>
    no basis, reported unverified, never fabricated.
    """
    costs: list[float] = []
    for row in _as_dict(run.get("structuring")).get("per_clip", []):
        if not isinstance(row, dict):
            continue
        usage = row.get("usage")
        if not isinstance(usage, dict):
            continue
        value = usage.get("cost_inr")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            costs.append(float(value))
    if not costs:
        return None
    return round(sum(costs) / len(costs), 4)


def _monthly_ai_cost(
    per_intake: float | None,
    rx_draft: float | None,
    volume: MonthlyVolume,
) -> float | None:
    if per_intake is None or rx_draft is None:
        return None
    return round(volume.intakes * per_intake + volume.rx_drafts * rx_draft, 2)


def _check_ceiling(
    label: str,
    value: float | None,
    ceiling: float,
    basis: str,
    breaches: list[str],
    unverified: list[str],
) -> None:
    if value is None:
        unverified.append(f"{label} ceiling not verifiable: {basis} has no recorded basis")
    elif value > ceiling:
        breaches.append(f"{label} cost {value:.4f} INR > {ceiling:.2f} INR ceiling ({basis})")


def _check_slice_and_headroom(
    monthly_ai: float | None,
    headroom: float | None,
    budget: LaunchBudget,
    volume: MonthlyVolume,
    breaches: list[str],
    unverified: list[str],
) -> None:
    if monthly_ai is None:
        unverified.append(
            "AI-slice and headroom not verifiable: rx-draft cost has no recorded basis"
        )
        return
    breach = (
        f"projected AI spend {monthly_ai:.2f} INR/month > "
        f"{budget.ai_slice_inr:.2f} INR/month AI slice at {volume.intakes} intakes + "
        f"{volume.rx_drafts} rx-drafts"
    )
    if monthly_ai > budget.ai_slice_inr:
        breaches.append(breach)
    if headroom is not None and headroom < budget.min_headroom_x:
        breaches.append(
            f"headroom {headroom:.2f}x < {budget.min_headroom_x:.1f}x minimum at "
            f"KPI-001 volume (projected {monthly_ai:.2f} INR/month)"
        )


def _select_provider(costs: list[ProviderCost]) -> ProviderCost | None:
    """Mechanical provider selection (issue #2 shortlist order).

    First recorded provider in shortlist order (gemini primary, then whisper
    transcription fallback, then nim) whose transcription leg passes the
    floor; if none passes the floor, the first recorded provider is returned
    so the report can state why it fails.
    """
    by_provider = {cost.provider: cost for cost in costs}
    candidates = [by_provider[provider] for provider in PROVIDER_ORDER if provider in by_provider]
    if not candidates:
        return None
    for cost in candidates:
        if cost.transcription_passes is True:
            return cost
    return candidates[0]


def _verdict(
    selected: ProviderCost | None,
    budget: LaunchBudget,
) -> tuple[GoNoGo, str]:
    """Apply the pre-decided go/no-go rule mechanically (issue #2).

    GO requires all five bar items to hold. The transcription floor failing
    is NO-GO with the text-first intake fallback; an unrecorded transcription
    bar is not a failure and is INCONCLUSIVE, never a fabricated pass (same
    rule as any other unmeasured bar item); structuring or calibration
    failing while transcription passes is threshold-tune; a cost-ceiling
    breach while every quality bar holds is NO-GO on cost; a missing
    measurement is unverified (never a vacuous pass).
    """
    if selected is None:
        return GoNoGo.NO_DATA, "no provider has a recorded run to apply the bar to"
    label = _provider_label(selected)
    if selected.transcription_passes is None:
        return (
            GoNoGo.INCONCLUSIVE,
            f"{label}: no transcription acceptance bar is recorded, so the "
            "transcription floor is unverified (never a vacuous pass)",
        )
    if not selected.transcription_passes:
        return (
            GoNoGo.NO_GO_TEXT_FIRST,
            f"{label}: transcription floor fails; text-first intake with voice "
            "as an upload-for-doctor artifact is the pre-decided fallback",
        )
    if selected.structuring_passes is None or selected.calibration_passes is None:
        return (
            GoNoGo.INCONCLUSIVE,
            f"{label}: transcription passes but structuring/calibration is not "
            "recorded, so the structuring bar is unverified (never a vacuous pass)",
        )
    if not selected.structuring_passes or not selected.calibration_passes:
        return (
            GoNoGo.THRESHOLD_TUNE,
            f"{label}: structuring or calibration fails while transcription "
            "passes; tune the AMB-006 threshold / confidence signal",
        )
    if selected.breaches:
        return (
            GoNoGo.NO_GO_COST,
            f"{label}: quality bars hold but a cost constraint breaches "
            f"({'; '.join(selected.breaches)})",
        )
    if selected.unverified:
        return (
            GoNoGo.INCONCLUSIVE,
            f"{label}: quality bars hold but cost constraints are unverified "
            f"({'; '.join(selected.unverified)})",
        )
    return (
        GoNoGo.GO,
        f"{label}: all five bar items hold (transcription, structuring, "
        f"AMB-006 calibration, silent-error bound, and cost within the "
        f"{budget.ai_slice_inr:.0f} INR/month AI slice)",
    )


def _select_explanation(report: SpikeReport) -> str:
    selected = report.selected
    if selected is None:
        return "- No provider has a recorded run; provider selection is undecided."
    passed = [c.provider for c in report.per_provider if c.transcription_passes is True]
    if selected.transcription_passes is True:
        return (
            f"- Selected **{_provider_label(selected)}** - first recorded provider "
            "in shortlist order whose transcription leg passes the floor."
        )
    transcription_status = (
        "fails the floor" if selected.transcription_passes is False else "has no recorded bar"
    )
    return (
        f"- Selected **{_provider_label(selected)}** - first recorded provider in "
        f"shortlist order; its transcription leg {transcription_status}"
        + (
            f", so the fallback candidates ({', '.join(p for p in passed)}) are moot"
            if passed
            else ""
        )
        + "."
    )


def _render_provider_row(cost: ProviderCost) -> str:
    label = _provider_label(cost)
    return (
        f"| {label} | {cost.run_file or 'no data'} | {_fmt_scored(cost.scored, cost.attempted)} | "
        f"{_fmt_bar(cost.transcription_passes)} | "
        f"{_fmt_wer_pair(cost.median_wer, cost.p90_wer)} | "
        f"{_fmt_3dp(cost.structuring_f1)} | "
        f"{_fmt_bar(cost.calibration_passes)} | {_fmt_cost(cost.per_intake_cost_inr)} | "
        f"{_fmt_cost(cost.per_call_cost_inr)} | "
        f"{_fmt_tokens(cost.input_tokens_per_intake)}/"
        f"{_fmt_tokens(cost.output_tokens_per_intake)} | "
        f"{_fmt_tokens(cost.input_tokens_per_call)}/"
        f"{_fmt_tokens(cost.output_tokens_per_call)} | "
        f"{_fmt_int(cost.calls_per_intake)} | {_fmt_int(cost.monthly_ai_calls)} | "
        f"{_fmt_cost(cost.rx_draft_cost_inr)} | "
        f"{_fmt_cost(cost.monthly_ai_cost_inr)} | {_fmt_headroom(cost.headroom_x)} |"
    )


def _render_constraints(
    cost: ProviderCost, budget: LaunchBudget, volume: MonthlyVolume
) -> list[str]:
    lines = [f"### {_provider_label(cost)}"]
    lines.append(
        _constraint_line(
            "per-intake",
            cost.per_intake_cost_inr,
            budget.per_intake_ceiling_inr,
            "recorded mean over billed clips",
            "no billed clips recorded",
        )
    )
    lines.append(
        _constraint_line(
            "rx-draft",
            cost.rx_draft_cost_inr,
            budget.rx_draft_ceiling_inr,
            "estimate from the recorded structuring-class call",
            "no structuring-class usage recorded to estimate from",
        )
    )
    if cost.monthly_ai_cost_inr is None:
        lines.append("- AI slice: unverified (rx-draft cost has no recorded basis)")
        lines.append("- Headroom: unverified (rx-draft cost has no recorded basis)")
    else:
        lines.append(
            f"- AI slice: projected {cost.monthly_ai_cost_inr:.2f} INR/month at "
            f"{volume.intakes} intakes + {volume.rx_drafts} rx-drafts <= "
            f"{budget.ai_slice_inr:.2f} INR/month -> "
            + ("PASS" if cost.monthly_ai_cost_inr <= budget.ai_slice_inr else "BREACH")
        )
        lines.append(
            f"- Headroom: {_fmt_headroom(cost.headroom_x)} (minimum {budget.min_headroom_x:.1f}x)"
        )
    for breach in cost.breaches:
        lines.append(f"- **Breach:** {breach}")
    return lines


def _constraint_line(
    label: str,
    value: float | None,
    ceiling: float,
    basis: str,
    unverified_reason: str,
) -> str:
    if value is None:
        return f"- {label} ceiling: unverified ({unverified_reason})"
    if value > ceiling:
        return f"- {label} ceiling: **BREACH** ({value:.4f} INR > {ceiling:.2f} INR; {basis})"
    return f"- {label} ceiling: PASS ({value:.4f} INR <= {ceiling:.2f} INR; {basis})"


def _render_caveats(report: SpikeReport) -> list[str]:
    caveats = [
        "Per-intake costs and tokens are the recorded means over billed clips "
        "(both legs where the run recorded them); failed clips are not billed "
        "and are excluded. Per-call figures are the per-intake means divided by "
        "the run's recorded calls per intake; the AI calls/month count is KPI-001 "
        "volume at that call rate (200 intakes + 200 rx-drafts, one call per "
        "rx-draft).",
        "The rx-draft call is not measured by the spike corpus; its per-call "
        "cost is estimated from the recorded structuring-class call. Where no "
        "structuring usage is recorded, the rx-draft ceiling and the AI-slice/"
        "headroom checks are reported unverified, never fabricated.",
    ]
    if any(cost.provider == "nim" for cost in report.per_provider):
        caveats.append(
            "NVIDIA NIM is prototyping-only; production use requires NVIDIA AI "
            "Enterprise licensing, so a NIM free-tier cost is not a production "
            "pricing reality."
        )
    return caveats


def _provider_label(cost: ProviderCost) -> str:
    return cost.provider if cost.model is None else f"{cost.provider} ({cost.model})"


def _fmt_scored(scored: int | None, attempted: int | None) -> str:
    if scored is None and attempted is None:
        return "no data"
    score = scored if scored is not None else "n/a"
    attempts = attempted if attempted is not None else "n/a"
    return f"{score}/{attempts}"


def _fmt_3dp(value: float | None) -> str:
    return "no data" if value is None else f"{value:.3f}"


def _fmt_wer_pair(median: float | None, p90: float | None) -> str:
    if median is None and p90 is None:
        return "no data"
    left = "no data" if median is None else f"{median:.3f}"
    right = "no data" if p90 is None else f"{p90:.3f}"
    return f"{left} / {right}"


def _fmt_tokens(value: float | None) -> str:
    return "no data" if value is None else f"{value:,.0f}"


def _fmt_cost(value: float | None) -> str:
    return "no data" if value is None else f"{value:.4f}"


def _fmt_int(value: int | None) -> str:
    return "no data" if value is None else str(value)


def _fmt_headroom(value: float | None) -> str:
    return "no data" if value is None else f"{value:.2f}x"


def _fmt_bar(value: bool | None) -> str:
    return "no data" if value is None else ("PASS" if value else "FAIL")


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
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


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
