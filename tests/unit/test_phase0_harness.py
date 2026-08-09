"""Phase 0 harness — gateway port + run orchestration tests (issue #4).

Verifies the provider-agnostic gateway interface (the seam that mirrors the
future MOD-005 AI gateway port), and that the runner drives a corpus through
a provider end-to-end, scores the transcription leg, records tokens + INR per
call, and persists the run output. Providers are faked here — only the Gemini
adapter's pure request/response parsing is tested without network.
"""

import asyncio
import json
from pathlib import Path

import pytest

from phase0.harness.gateway import Gateway
from phase0.harness.models import StructureResult, TranscribeResult, Usage
from phase0.harness.runner import run_corpus
from phase0.loader import Corpus


class FakeGateway:
    """Deterministic stand-in for a real provider, implements the port."""

    def __init__(self, transcripts: dict[str, str], fail: frozenset[str] = frozenset()) -> None:
        self._transcripts = transcripts
        self._fail = fail

    @property
    def name(self) -> str:
        return "fake"

    async def transcribe(self, audio_path: Path, clip_id: str) -> TranscribeResult:
        if clip_id in self._fail:
            raise RuntimeError("provider error")
        return TranscribeResult(
            text=self._transcripts[clip_id],
            usage=Usage(
                provider="fake",
                model="fake-1",
                input_tokens=100,
                output_tokens=50,
                cost_inr=0.0,
                latency_ms=10,
                tier="free",
            ),
        )

    async def structure(self, transcript: str, clip_id: str) -> StructureResult:
        return StructureResult(structured={}, confidence=1.0, usage=self._make_usage())

    def _make_usage(self) -> Usage:
        return Usage(
            provider="fake",
            model="fake-1",
            input_tokens=20,
            output_tokens=10,
            cost_inr=0.0,
            latency_ms=5,
            tier="free",
        )


@pytest.fixture()
def fake_gateway() -> FakeGateway:
    return FakeGateway(
        transcripts={
            "sample_0001": "बुखार और खांसी",
            "sample_0002": "खांसी दो दिन",
        }
    )


def test_fake_gateway_satisfies_the_port() -> None:
    gateway: Gateway = FakeGateway({})
    assert gateway.name == "fake"


def test_runner_returns_report_shape(corpus: Corpus, fake_gateway: FakeGateway) -> None:
    report = run_corpus(
        gateway=fake_gateway,
        corpus=corpus,
        clip_ids={"sample_0001", "sample_0002"},
    )
    assert report.provider == "fake"
    assert report.clips_scored == 2
    assert report.clips_failed == 0
    assert report.coverage == {"sample_0001", "sample_0002"}


def test_runner_scores_wer_against_ground_truth(corpus: Corpus, fake_gateway: FakeGateway) -> None:
    report = run_corpus(gateway=fake_gateway, corpus=corpus, clip_ids={"sample_0001"})
    row = report.per_clip["sample_0001"]
    # Ground truth for sample_0001 comes from the committed fixtures; the fake
    # returns a deliberately-different transcript, so WER must be > 0.
    assert row.wer is not None and row.wer > 0.0
    assert row.cer is not None and row.cer > 0.0


def test_runner_persists_run_output(
    tmp_path: Path, corpus: Corpus, fake_gateway: FakeGateway
) -> None:
    output = tmp_path / "run.json"
    run_corpus(
        gateway=fake_gateway,
        corpus=corpus,
        clip_ids={"sample_0001", "sample_0002"},
        output_path=output,
    )
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["provider"] == "fake"
    assert len(payload["transcription"]["per_clip"]) == 2
    assert payload["totals"]["cost_inr"] == 0.0
    assert payload["totals"]["input_tokens"] == 200
    assert payload["totals"]["output_tokens"] == 100


def test_runner_records_failed_clip_and_excludes_from_scoring(
    corpus: Corpus, fake_gateway: FakeGateway
) -> None:
    failing = FakeGateway(
        transcripts={"sample_0001": "बुखार और खांसी"},
        fail=frozenset({"sample_0002"}),
    )
    report = run_corpus(
        gateway=failing,
        corpus=corpus,
        clip_ids={"sample_0001", "sample_0002"},
    )
    assert report.clips_failed == 1
    assert report.per_clip["sample_0002"].error is not None
    assert report.per_clip["sample_0002"].wer is None
    assert "sample_0002" not in report.scored_clip_ids()


def test_runner_aggregates_per_cohort_and_overall(
    corpus: Corpus, fake_gateway: FakeGateway
) -> None:
    report = run_corpus(
        gateway=fake_gateway,
        corpus=corpus,
        clip_ids={"sample_0001", "sample_0002"},
    )
    assert report.overall_wer is not None
    assert report.overall_wer.sample_size == 2
    assert set(report.per_cohort_wer) <= {"urban_hindi", "peri_urban", "heavy_local"}
    # Both clips must land in their manifest cohorts.
    assert sum(cohort.sample_size for cohort in report.per_cohort_wer.values()) == 2


def test_runner_rejects_unknown_clip(corpus: Corpus, fake_gateway: FakeGateway) -> None:
    with pytest.raises(ValueError):
        run_corpus(gateway=fake_gateway, corpus=corpus, clip_ids={"does_not_exist"})


class ConcurrencyProbeGateway(FakeGateway):
    """Records the maximum number of in-flight transcribe calls."""

    def __init__(self, transcripts: dict[str, str]) -> None:
        super().__init__(transcripts=transcripts)
        self._inflight = 0
        self.max_inflight = 0

    async def transcribe(self, audio_path: Path, clip_id: str) -> TranscribeResult:
        self._inflight += 1
        self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            await asyncio.sleep(0.02)
            return await super().transcribe(audio_path, clip_id)
        finally:
            self._inflight -= 1


def test_runner_respects_concurrency_limit(corpus: Corpus) -> None:
    transcripts = {clip.clip_id: "कुछ" for clip in corpus.clips[:4]}
    gateway = ConcurrencyProbeGateway(transcripts=transcripts)
    run_corpus(
        gateway=gateway,
        corpus=corpus,
        clip_ids=set(transcripts),
        concurrency=2,
    )
    assert gateway.max_inflight <= 2
