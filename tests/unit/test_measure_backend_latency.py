"""LAT-HARNESS (#901): the latency probe's pure functions.

Feeds ``scripts/measure_backend_latency.py`` fixed sample arrays and asserts
the percentile math (linear interpolation, the same convention as the
observability rollup's ``percentile``), the per-endpoint summary (p50/p95/min/
max over the measured totals and the server-processing split), the threshold
verdict, and the ``Server-Timing`` header parse. No network anywhere: the
script is loaded by file location because the root ``scripts/`` directory is
not a Python package (``scripts`` resolves to ``apps/backend/scripts`` - see
``test_contract_check.py``).
"""

import importlib.util
import sys
from pathlib import Path

PROBE_FILE = Path(__file__).resolve().parents[2] / "scripts" / "measure_backend_latency.py"


def _load_probe():
    """Import ``scripts/measure_backend_latency.py`` by file location."""
    spec = importlib.util.spec_from_file_location("measure_backend_latency", PROBE_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


def test_percentile_empty_sample_is_none() -> None:
    assert probe.percentile([], 0.95) is None


def test_percentile_single_sample_is_that_sample() -> None:
    assert probe.percentile([42.0], 0.50) == 42.0
    assert probe.percentile([42.0], 0.95) == 42.0


def test_percentile_unsorted_input_is_sorted_first() -> None:
    assert probe.percentile([30.0, 10.0, 20.0], 0.5) == 20.0


def test_percentile_even_count_interpolates_linearly() -> None:
    assert probe.percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0


def test_percentile_matches_rollup_convention_on_grid() -> None:
    samples = [float(i) for i in range(100)]
    assert probe.percentile(samples, 0.95) == 94.05
    assert probe.percentile(samples, 0.0) == 0.0
    assert probe.percentile(samples, 1.0) == 99.0


def test_percentile_out_of_range_fraction_raises() -> None:
    try:
        probe.percentile([1.0], 1.5)
    except ValueError:
        pass
    else:
        raise AssertionError("fraction 1.5 must raise")


def test_summarize_reports_min_max_and_percentiles() -> None:
    samples = [12.0, 4.0, 7.0, 15.0, 3.0, 9.0, 20.0, 6.0]
    stats = probe.summarize("/health", samples)
    assert stats is not None
    assert stats.endpoint == "/health"
    assert stats.count == 8
    assert stats.min_ms == 3.0
    assert stats.max_ms == 20.0
    assert stats.p50_ms == probe.percentile(samples, 0.5)
    assert stats.p95_ms == probe.percentile(samples, 0.95)


def test_summarize_empty_samples_is_none() -> None:
    assert probe.summarize("/health", []) is None


def test_verdict_passes_at_and_below_threshold() -> None:
    stats = probe.summarize("/health", [100.0, 100.0, 100.0])
    assert stats is not None
    assert probe.verdict(stats, 100.0)
    assert probe.verdict(stats, 150.0)


def test_verdict_fails_above_threshold() -> None:
    stats = probe.summarize("/health", [100.0, 100.0, 100.0])
    assert stats is not None
    assert not probe.verdict(stats, 99.9)


def test_parse_server_timing_reads_the_tagged_duration() -> None:
    header = "caresetu_tstmp;dur=12.3"
    assert probe.parse_server_timing_ms(header) == 12.3


def test_parse_server_timing_survives_extra_metrics() -> None:
    header = "db;dur=1.0, caresetu_tstmp;dur=88.5, other;dur=2.0"
    assert probe.parse_server_timing_ms(header) == 88.5


def test_parse_server_timing_absent_tag_is_none() -> None:
    assert probe.parse_server_timing_ms("db;dur=1.0") is None
    assert probe.parse_server_timing_ms("") is None


def test_format_table_marks_breach_and_server_split() -> None:
    fast = probe.summarize("/health", [10.0, 11.0, 12.0])
    slow = probe.summarize("/v1/me", [100.0, 2000.0, 100.0])
    assert fast is not None and slow is not None
    table = probe.format_table([fast, slow], threshold_ms=1500.0)
    assert "/health" in table
    assert "/v1/me" in table
    assert "PASS" in table and "FAIL" in table
