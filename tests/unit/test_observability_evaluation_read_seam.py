"""Facade-seam regression test for the operator evaluation read (#807).

Pins that ``get_evaluation_read()`` unwraps the ``(scores, total_count)`` tuple
produced by ``get_judge_scores()`` and exposes ``judge_scores`` as a list on
``EvaluationReadResponse``, with no database in play.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from modules.observability.facade import (
    EvaluationAgreementRead,
    EvaluationDatasetVersion,
    EvaluationReadResponse,
    EvaluationScoreRead,
    JudgeRunProgress,
    ObservabilityFacade,
)

_DATASET = EvaluationDatasetVersion(
    id=1,
    name="golden",
    version=1,
    status="active",
    created_at="2026-10-01T00:00:00+00:00",
    updated_at="2026-10-12T00:00:00+00:00",
    example_count=20,
    is_active=True,
)

_RUN = JudgeRunProgress(
    run_ref="eval-run-001",
    dataset_name="golden",
    dataset_version=1,
    status="completed",
    budget_paise=10_000,
    cost_paise=8_500,
    started_at="2026-10-12T10:00:00+00:00",
    completed_at="2026-10-12T10:05:00+00:00",
    failure_reason=None,
    example_count=20,
    scored_count=20,
    synthetic_only=True,
)

_SCORES = [
    EvaluationScoreRead(
        evaluator="completeness",
        observation_ref="transcribe-001",
        observation_kind="golden",
        source="judge",
        data_type="NUMERIC",
        value=0.95,
        judge_run_ref="eval-run-001",
        score_date="2026-10-12",
        trace_id="trace-001",
        metadata={"model": "gpt-4o-mini", "prompt_version": "v1"},
    ),
]

_AGREEMENT = [
    EvaluationAgreementRead(
        evaluator="completeness",
        count=10,
        mean_absolute_error=0.05,
        within_tolerance_share=0.9,
        kappa=None,
        tolerance=0.1,
        data_type="NUMERIC",
        synthetic_only=True,
        empty=False,
    ),
]


async def test_get_evaluation_read_exposes_judge_scores_as_list() -> None:
    facade = ObservabilityFacade(engine=None)  # type: ignore[arg-type]
    facade.get_active_evaluation_dataset = AsyncMock(return_value=_DATASET)
    facade.get_latest_judge_run = AsyncMock(return_value=_RUN)
    facade.get_judge_scores = AsyncMock(return_value=(_SCORES, len(_SCORES)))
    facade.get_evaluation_agreement_read = AsyncMock(return_value=_AGREEMENT)

    result = await facade.get_evaluation_read()

    assert isinstance(result, EvaluationReadResponse)
    assert isinstance(result.judge_scores, list)
    assert result.judge_scores == _SCORES
    assert result.active_dataset is _DATASET
    assert result.judge_run is _RUN
    assert result.agreement == _AGREEMENT
    facade.get_judge_scores.assert_awaited_once_with(run_ref="eval-run-001")
