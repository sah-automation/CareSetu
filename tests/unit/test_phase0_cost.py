"""Phase 0 harness - launch-phase cost model and spike report tests (issue #12).

Verifies the two seams of the cost model: ``build_spike_report`` derives
per-intake INR cost + tokens from the recorded run usage, extrapolates to
KPI-001 volume (~200 intakes + ~200 rx-drafts/month) against the
launch-phase constraints (AI slice <= INR 600/month, >= 3x headroom,
per-intake <= INR 2.00, rx-draft <= INR 1.00), and applies the pre-decided
go/no-go rule mechanically; ``render_spike_report`` emits the Phase 0
decision record. Feed is synthetic run JSONs written to a temp directory;
costs come from recorded usage, never eyeballed, and an unmeasurable
constraint is reported *unverified*, never a fabricated pass.
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from phase0.harness.cost import (
    GoNoGo,
    LaunchBudget,
    build_spike_report,
    render_spike_report,
)


def _usage(
    provider: str,
    cost: float,
    in_tokens: int = 100,
    out_tokens: int = 50,
) -> dict[str, object]:
    return {
        "provider": provider,
        "model": f"{provider}-model",
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "cost_inr": cost,
        "tier": "free",
        "latency_ms": 5,
    }


def _full_gemini_run() -> dict[str, object]:
    """A synthetic two-leg gemini run whose every bar item holds (-> GO).

    Two billed clips, each with a separate transcribe + structure call; per-
    intake cost 0.015 INR (transcribe 0.010 + structure 0.005), rx-draft
    estimate 0.005 INR, monthly 4.00 INR at KPI-001 volume, headroom 150x -
    all comfortably inside every ceiling.
    """
    return {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "generated_at": "2026-08-10T10:00:00+00:00",
        "coverage": {"clips_attempted": 43, "clips_scored": 2, "clips_failed": 41},
        "transcription": {
            "per_clip": [
                {
                    "clip_id": "sample_0001",
                    "cohort": "peri_urban",
                    "wer": 0.1,
                    "cer": 0.05,
                    "error": None,
                    "usage": _usage("gemini", 0.010),
                },
                {
                    "clip_id": "sample_0002",
                    "cohort": "urban_hindi",
                    "wer": 0.12,
                    "cer": 0.06,
                    "error": None,
                    "usage": _usage("gemini", 0.010),
                },
            ],
            "per_cohort": {},
            "overall": {
                "median_wer": 0.1,
                "p90_wer": 0.15,
                "median_cer": 0.05,
                "p90_cer": 0.1,
                "sample_size": 2,
            },
            "acceptance_bar": {"passes": True, "failures": []},
        },
        "structuring": {
            "skipped": False,
            "well_formed": 2,
            "scored": 2,
            "per_clip": [
                {
                    "clip_id": "sample_0001",
                    "cohort": "peri_urban",
                    "confidence": 0.95,
                    "low_confidence": False,
                    "significant_error": False,
                    "field_f1": {},
                    "error": None,
                    "usage": _usage("gemini", 0.005),
                },
                {
                    "clip_id": "sample_0002",
                    "cohort": "urban_hindi",
                    "confidence": 0.95,
                    "low_confidence": False,
                    "significant_error": False,
                    "field_f1": {},
                    "error": None,
                    "usage": _usage("gemini", 0.005),
                },
            ],
            "per_field": {},
            "overall": {
                "correct": 1,
                "reference": 1,
                "hypothesis": 1,
                "precision": 0.95,
                "recall": 0.95,
                "f1": 0.95,
            },
            "acceptance_bar": {"passes": True, "failures": [], "target": 0.9},
        },
        "calibration": {
            "threshold": 0.7,
            "clips": 2,
            "flagged": 2,
            "unflagged": 0,
            "significant_errors": 0,
            "flagged_significant": 0,
            "silent_errors": 0,
            "silent_error_rate": 0.0,
            "flag_precision": 1.0,
            "flag_recall": 1.0,
            "passes_silent_error_bar": True,
        },
        "gate_validated": True,
        "totals": _usage("gemini", 0.03),
    }


def _collapsed_gemini_run() -> dict[str, object]:
    """A genuine single-call gemini run: one transcription usage row per clip
    plus the multimodal collapse probe, no separate structuring leg.

    The per-intake cost is the transcription call alone (0.010 INR); with no
    structuring usage recorded the rx-draft estimate is unverified, so the
    verdict is INCONCLUSIVE rather than a fabricated GO.
    """
    run = _copy_run(_full_gemini_run())
    del run["structuring"]
    del run["calibration"]
    run["provider_findings"] = {"multimodal_single_call": {"attempted": True, "collapsed": True}}
    return run


def _whisper_run() -> dict[str, object]:
    """A synthetic whisper run: 2-call pipeline, transcription and structuring pass."""
    run = _full_gemini_run()
    run["provider"] = "whisper"
    run["model"] = "whisper-1"
    run["generated_at"] = "2026-08-10T11:00:00+00:00"
    run["provider_findings"] = {}
    return run


def _write_run(tmp_path: Path, run: dict[str, object], filename: str) -> Path:
    path = tmp_path / filename
    path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return path


def _copy_run(run: dict[str, object]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(run)))


def _set_transcription_cost(run: dict[str, Any], cost: float) -> None:
    for row in _rows(run, "transcription"):
        row["usage"]["cost_inr"] = cost


def _set_structuring_cost(run: dict[str, Any], cost: float) -> None:
    for row in _rows(run, "structuring"):
        row["usage"]["cost_inr"] = cost


def _rows(run: dict[str, Any], leg: str) -> list[dict[str, Any]]:
    per_clip = run[leg]["per_clip"]
    assert isinstance(per_clip, list)
    return [row for row in per_clip if isinstance(row, dict)]


def test_go_run_derives_cost_from_recorded_usage_and_verdicts_go(
    tmp_path: Path,
) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    assert [c.provider for c in report.per_provider] == ["gemini"]
    gemini = report.per_provider[0]
    assert gemini.run_file == "20260810T100000Z.json"
    assert gemini.scored == 2
    assert gemini.per_intake_cost_inr == pytest.approx(0.015)  # transcribe + structure
    assert gemini.per_call_cost_inr == pytest.approx(0.0075)  # 0.015 / 2 calls
    assert gemini.input_tokens_per_intake == pytest.approx(200.0)  # both legs
    assert gemini.output_tokens_per_intake == pytest.approx(100.0)  # both legs
    assert gemini.input_tokens_per_call == pytest.approx(100.0)  # 200 / 2
    assert gemini.output_tokens_per_call == pytest.approx(50.0)  # 100 / 2
    assert gemini.calls_per_intake == 2
    assert gemini.monthly_ai_calls == 600  # 200 * 2 + 200 rx-drafts
    assert gemini.median_wer == pytest.approx(0.1)
    assert gemini.p90_wer == pytest.approx(0.15)
    assert gemini.rx_draft_cost_inr == pytest.approx(0.005)
    assert gemini.monthly_ai_cost_inr == pytest.approx(4.0)  # 200 * 0.015 + 200 * 0.005
    assert gemini.headroom_x == pytest.approx(150.0)  # 600 / 4
    assert gemini.breaches == ()
    assert gemini.unverified == ()
    assert report.selected == gemini
    assert report.verdict == GoNoGo.GO
    assert "all five bar items hold" in report.verdict_reason


def test_genuine_single_call_gemini_shape_is_one_call_and_inconclusive(
    tmp_path: Path,
) -> None:
    _write_run(tmp_path, _collapsed_gemini_run(), "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    gemini = report.per_provider[0]
    assert gemini.calls_per_intake == 1  # genuine collapsed single call
    assert gemini.per_intake_cost_inr == pytest.approx(0.010)  # transcription call only
    assert gemini.per_call_cost_inr == pytest.approx(0.010)
    assert gemini.monthly_ai_calls == 400  # 200 * 1 + 200 rx-drafts
    assert gemini.rx_draft_cost_inr is None
    assert gemini.monthly_ai_cost_inr is None
    assert report.verdict == GoNoGo.INCONCLUSIVE
    assert "unverified" in report.verdict_reason


def test_two_leg_pipeline_records_two_calls_per_intake(tmp_path: Path) -> None:
    _write_run(tmp_path, _whisper_run(), "20260810T110000Z.json")

    report = build_spike_report(tmp_path)

    whisper = report.per_provider[0]
    assert whisper.provider == "whisper"
    assert whisper.calls_per_intake == 2
    assert report.verdict == GoNoGo.GO


def test_unrecorded_providers_are_absent_not_fabricated(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    assert len(report.per_provider) == 1
    assert {c.provider for c in report.per_provider} == {"gemini"}


def test_transcription_floor_failure_is_no_go_text_first(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    run["transcription"]["acceptance_bar"] = {
        "passes": False,
        "failures": ["overall: median WER 0.3 > 0.2"],
    }
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    assert report.selected is not None and report.selected.provider == "gemini"
    assert report.verdict == GoNoGo.NO_GO_TEXT_FIRST
    assert "text-first intake" in report.verdict_reason


def test_unrecorded_transcription_bar_is_inconclusive_not_no_go(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    del run["transcription"]["acceptance_bar"]
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    assert report.selected is not None and report.selected.provider == "gemini"
    assert report.verdict == GoNoGo.INCONCLUSIVE
    assert "unverified" in report.verdict_reason
    assert "text-first" not in report.verdict_reason


def test_structuring_failure_is_threshold_tune(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    run["structuring"]["acceptance_bar"] = {
        "passes": False,
        "failures": [],
        "target": 0.9,
    }
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    assert report.verdict == GoNoGo.THRESHOLD_TUNE
    assert "structuring or calibration fails" in report.verdict_reason


def test_calibration_failure_is_threshold_tune(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    run["calibration"]["passes_silent_error_bar"] = False
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)

    assert report.verdict == GoNoGo.THRESHOLD_TUNE


def test_per_intake_ceiling_breach_is_no_go_cost(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    _set_transcription_cost(run, 2.5)
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)
    gemini = report.per_provider[0]

    assert gemini.per_intake_cost_inr == pytest.approx(2.505)
    assert any("per-intake cost 2.5050" in breach for breach in gemini.breaches)
    assert report.verdict == GoNoGo.NO_GO_COST


def test_rx_draft_ceiling_breach_is_reported_with_reason(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    _set_structuring_cost(run, 1.1)
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)
    gemini = report.per_provider[0]

    assert gemini.rx_draft_cost_inr == pytest.approx(1.1)
    assert any("rx-draft cost" in breach for breach in gemini.breaches)
    assert report.verdict == GoNoGo.NO_GO_COST


def test_headroom_below_three_x_is_reported_with_reason(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    _set_transcription_cost(run, 1.5)
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)
    gemini = report.per_provider[0]

    assert gemini.monthly_ai_cost_inr == pytest.approx(302.0)
    assert gemini.headroom_x == pytest.approx(1.99, abs=0.01)
    assert any("headroom" in breach and "3.0x" in breach for breach in gemini.breaches)
    assert report.verdict == GoNoGo.NO_GO_COST


def test_ai_slice_breach_is_reported_with_reason(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    _set_transcription_cost(run, 1.99)
    _set_structuring_cost(run, 1.02)
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)
    gemini = report.per_provider[0]

    assert gemini.monthly_ai_cost_inr == pytest.approx(806.0)  # 200 * 3.01 + 200 * 1.02
    assert any("projected AI spend" in breach and "600.00" in breach for breach in gemini.breaches)
    assert report.verdict == GoNoGo.NO_GO_COST


def test_missing_structuring_is_inconclusive_never_vacuous(tmp_path: Path) -> None:
    run = _copy_run(_full_gemini_run())
    del run["structuring"]
    del run["calibration"]
    _write_run(tmp_path, run, "20260810T100000Z.json")

    report = build_spike_report(tmp_path)
    gemini = report.per_provider[0]

    assert report.verdict == GoNoGo.INCONCLUSIVE
    assert "unverified" in report.verdict_reason
    assert gemini.rx_draft_cost_inr is None
    assert gemini.monthly_ai_cost_inr is None
    assert gemini.headroom_x is None
    assert gemini.breaches == ()
    assert any("rx-draft" in note for note in gemini.unverified)


def test_no_recorded_runs_is_no_data(tmp_path: Path) -> None:
    report = build_spike_report(tmp_path)

    assert report.per_provider == ()
    assert report.selected is None
    assert report.verdict == GoNoGo.NO_DATA


def test_whisper_fallback_selected_when_gemini_transcription_fails(
    tmp_path: Path,
) -> None:
    gemini_run = _copy_run(_full_gemini_run())
    gemini_run["transcription"]["acceptance_bar"] = {
        "passes": False,
        "failures": ["overall: p90 WER 0.4 > 0.35"],
    }
    _write_run(tmp_path, gemini_run, "20260810T100000Z.json")
    _write_run(tmp_path, _whisper_run(), "20260810T110000Z.json")

    report = build_spike_report(tmp_path)

    assert [c.provider for c in report.per_provider] == ["gemini", "whisper"]
    assert report.selected is not None and report.selected.provider == "whisper"
    assert report.verdict == GoNoGo.GO


def test_latest_run_per_provider_wins(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")
    later = _copy_run(_full_gemini_run())
    later["generated_at"] = "2026-08-11T09:30:00+00:00"
    _write_run(tmp_path, later, "20260811T093000Z.json")

    report = build_spike_report(tmp_path)

    assert report.per_provider[0].run_file == "20260811T093000Z.json"


def test_custom_budget_ceiling_is_honoured(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    report = build_spike_report(tmp_path, budget=LaunchBudget(per_intake_ceiling_inr=0.01))

    assert any("per-intake cost" in breach for breach in report.per_provider[0].breaches)
    assert report.verdict == GoNoGo.NO_GO_COST


def test_corrupt_run_file_is_a_hard_error(tmp_path: Path) -> None:
    (tmp_path / "corrupt.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="is not valid JSON"):
        build_spike_report(tmp_path)


def test_render_emits_decision_record(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    rendered = render_spike_report(build_spike_report(tmp_path))

    assert "# CareSetu Phase 0 spike report" in rendered
    assert "never eyeballed" in rendered
    assert f"- **Verdict:** {GoNoGo.GO}" in rendered
    assert "Per-provider model" in rendered
    assert "median/p90 WER" in rendered
    assert "per-call INR" in rendered
    assert "AI calls/mo" in rendered
    assert "in/out tok/call" in rendered
    assert "Constraint verification" in rendered
    assert "~600 AI calls" in rendered
    assert "per-intake ceiling: PASS" in rendered
    assert "rx-draft ceiling: PASS" in rendered
    assert "headroom" in rendered.lower()
    assert "AMB-006 threshold" in rendered
    assert "all five bar items hold" in rendered
