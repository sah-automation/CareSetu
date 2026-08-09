"""Phase 0 harness — cross-provider comparison table tests (issue #11).

Verifies the two seams of the comparison tool: ``compare_runs`` parses the
recorded run JSONs (written by ``phase0.harness.runner.report_to_json``) into
one apples-to-apples row per provider — transcription quality, structuring
accuracy, flag calibration, and per-intake cost — and ``render_comparison``
emits the comparison table. Feed is synthetic run JSONs written to a temp
directory; the table is generated from recorded runs, never eyeballed, and a
provider with no recorded run gets an explicit ``no data`` row, never a guess.
"""

import json
from pathlib import Path

import pytest

from phase0.harness.compare import compare_runs, render_comparison


def _usage(provider: str, cost: float) -> dict[str, object]:
    return {
        "provider": provider,
        "model": f"{provider}-model",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_inr": cost,
        "tier": "free",
        "latency_ms": 5,
    }


def _full_gemini_run() -> dict[str, object]:
    return {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "generated_at": "2026-08-10T10:00:00+00:00",
        "coverage": {"clips_attempted": 43, "clips_scored": 12, "clips_failed": 31},
        "transcription": {
            "per_clip": [
                {
                    "clip_id": "sample_0001",
                    "cohort": "peri_urban",
                    "wer": 0.2,
                    "cer": 0.1,
                    "error": None,
                    "usage": _usage("gemini", 0.01),
                },
                {
                    "clip_id": "sample_0002",
                    "cohort": "urban_hindi",
                    "wer": 0.3,
                    "cer": 0.15,
                    "error": None,
                    "usage": _usage("gemini", 0.02),
                },
            ],
            "per_cohort": {},
            "overall": {
                "median_wer": 0.181,
                "p90_wer": 0.429,
                "median_cer": 0.118,
                "p90_cer": 0.364,
                "sample_size": 12,
            },
            "acceptance_bar": {"passes": False, "failures": []},
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
                    "usage": _usage("gemini", 0.01),
                },
            ],
            "per_field": {},
            "overall": {
                "correct": 1,
                "reference": 1,
                "hypothesis": 1,
                "precision": 0.96,
                "recall": 0.94,
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
            "silent_error_ceiling": 0.02,
        },
        "gate_validated": True,
        "totals": _usage("gemini", 0.03),
        "provider_findings": {},
    }


def _write_run(tmp_path: Path, run: dict[str, object], filename: str) -> Path:
    path = tmp_path / filename
    path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return path


def _copy_run(run: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(run))


def test_compare_runs_parses_run_and_derives_metrics(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    rows = compare_runs(tmp_path)

    assert [row.provider for row in rows] == ["gemini", "whisper", "nim"]
    gemini = rows[0]
    assert gemini.model == "gemini-2.5-flash"
    assert gemini.run_file == "20260810T100000Z.json"
    assert gemini.scored == 12
    assert gemini.attempted == 43
    assert gemini.median_wer == pytest.approx(0.181)
    assert gemini.p90_wer == pytest.approx(0.429)
    assert gemini.median_cer == pytest.approx(0.118)
    assert gemini.p90_cer == pytest.approx(0.364)
    assert gemini.structuring_f1 == pytest.approx(0.95)
    assert gemini.structuring_n == 2
    assert gemini.silent_error_rate == pytest.approx(0.0)
    assert gemini.flag_precision == pytest.approx(1.0)
    assert gemini.flag_recall == pytest.approx(1.0)
    assert gemini.calibration_passes is True
    assert gemini.per_intake_cost_inr == pytest.approx(0.0225)
    assert gemini.calls_per_intake == 2


def test_compare_runs_marks_missing_providers_as_no_data(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    rows = compare_runs(tmp_path)

    whisper = next(row for row in rows if row.provider == "whisper")
    nim = next(row for row in rows if row.provider == "nim")
    for row in (whisper, nim):
        assert row.run_file is None
        assert row.model is None
        assert row.scored is None
        assert row.median_wer is None
        assert row.structuring_f1 is None
        assert row.per_intake_cost_inr is None


def test_compare_runs_selects_the_latest_run_per_provider(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T080000Z.json")
    later = _copy_run(_full_gemini_run())
    later["generated_at"] = "2026-08-11T09:30:00+00:00"
    later["totals"] = _usage("gemini", 0.99)
    _write_run(tmp_path, later, "20260811T093000Z.json")

    rows = compare_runs(tmp_path)

    gemini = next(row for row in rows if row.provider == "gemini")
    assert gemini.run_file == "20260811T093000Z.json"
    assert gemini.model == "gemini-2.5-flash"


def test_compare_runs_surfaces_the_nim_licensing_caveat(tmp_path: Path) -> None:
    nim_run = _copy_run(_full_gemini_run())
    nim_run["provider"] = "nim"
    nim_run["model"] = "canary-1b-asr"
    nim_run["generated_at"] = "2026-08-11T09:30:00+00:00"
    nim_run["provider_findings"] = {"nim_licensing_caveat": "prototyping only"}
    _write_run(tmp_path, nim_run, "20260811T093000Z.json")

    rows = compare_runs(tmp_path)

    nim = next(row for row in rows if row.provider == "nim")
    assert nim.licensing_caveat == "prototyping only"


def test_calls_per_intake_reflects_the_recorded_pipeline_shape(tmp_path: Path) -> None:
    probe_run = _copy_run(_full_gemini_run())
    probe_run["provider"] = "gemini"
    probe_run["generated_at"] = "2026-08-11T09:30:00+00:00"
    probe_run["provider_findings"] = {
        "multimodal_single_call": {"attempted": True, "collapsed": True}
    }
    _write_run(tmp_path, probe_run, "20260811T093000Z.json")

    transcription_only = _copy_run(_full_gemini_run())
    transcription_only["provider"] = "whisper"
    transcription_only["model"] = "whisper-1"
    transcription_only["generated_at"] = "2026-08-11T10:00:00+00:00"
    transcription_only["structuring"] = {
        "skipped": True,
        "well_formed": 0,
        "scored": 0,
        "per_clip": [],
        "per_field": {},
        "overall": None,
        "acceptance_bar": {"passes": False, "failures": [], "target": 0.9},
    }
    _write_run(tmp_path, transcription_only, "20260811T100000Z.json")

    legacy = _copy_run(_full_gemini_run())
    legacy["provider"] = "nim"
    legacy["model"] = "canary-1b-asr"
    legacy["generated_at"] = "2026-08-11T11:00:00+00:00"
    del legacy["structuring"]
    _write_run(tmp_path, legacy, "20260811T110000Z.json")

    rows = {row.provider: row for row in compare_runs(tmp_path)}
    assert rows["gemini"].calls_per_intake == 1  # multimodal single-call probe
    assert rows["whisper"].calls_per_intake == 1  # transcription-only run
    assert rows["nim"].calls_per_intake is None  # run with no structuring section


def test_calls_per_intake_reads_legacy_gemini_findings_key(tmp_path: Path) -> None:
    # The recorded gemini run (20260809T144551Z.json) predates the
    # ``provider_findings`` rename and records the probe under
    # ``gemini_findings``; the single-call verdict must still surface.
    legacy = _copy_run(_full_gemini_run())
    legacy["generated_at"] = "2026-08-11T09:30:00+00:00"
    del legacy["provider_findings"]
    legacy["gemini_findings"] = {"multimodal_single_call": {"attempted": True, "collapsed": True}}
    _write_run(tmp_path, legacy, "20260811T093000Z.json")

    gemini = next(row for row in compare_runs(tmp_path) if row.provider == "gemini")

    assert gemini.calls_per_intake == 1


def test_render_comparison_emits_a_table_covering_all_providers(tmp_path: Path) -> None:
    _write_run(tmp_path, _full_gemini_run(), "20260810T100000Z.json")

    rendered = render_comparison(compare_runs(tmp_path))

    assert rendered.startswith("Phase 0 provider comparison")
    assert "generated from the recorded run JSONs" in rendered
    assert "| provider (model) | run |" in rendered
    assert "| gemini (gemini-2.5-flash) |" in rendered
    assert "| whisper" in rendered
    assert "| nim" in rendered
    assert "no data" in rendered
    assert "| 12/43 |" in rendered
    assert "| 0.950 |" in rendered
    assert "PASS" in rendered
    assert "| 0.0225 |" in rendered
    assert "Caveats" in rendered
    assert "production use requires NVIDIA AI Enterprise licensing" in rendered
