"""#766: versioned datasets, examples and judge runs against real PostgreSQL.

The ticket is a schema slice, so the seam under test is the migrated database
itself rather than a private helper:

- a dataset version carries a name, a version and a status; only one version of
  a name may be active at a time;
- an example carries a task type, a JSONB input and expected output, and tags,
  and its ``example_ref`` is unique within its dataset;
- a judge run carries its stable reference, the dataset version, a budget and a
  status;
- a judge score carries ``source = 'judge'``, its run reference and non-PHI
  metadata;
- code and human rows keep the exact uniqueness they had before, while judge
  rows are unique per run, so two runs may score the same observation;
- a run reference is required on judge rows and refused on code/human rows.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.observability.schema.models import (
    observability_evaluation_datasets,
    observability_evaluation_examples,
    observability_evaluation_judge_runs,
    observability_evaluation_scores,
)

_SCORE_DATE = date(2026, 10, 23)


async def _add_dataset(
    engine: AsyncEngine,
    *,
    name: str = "golden",
    version: int = 1,
    status: str = "active",
) -> int:
    table = observability_evaluation_datasets
    async with engine.begin() as connection:
        result = await connection.execute(
            insert(table).values(name=name, version=version, status=status).returning(table.c.id)
        )
        return int(result.scalar_one())


async def _add_example(
    engine: AsyncEngine,
    dataset_id: int,
    *,
    example_ref: str = "tx-clear",
) -> int:
    table = observability_evaluation_examples
    async with engine.begin() as connection:
        result = await connection.execute(
            insert(table)
            .values(
                dataset_id=dataset_id,
                example_ref=example_ref,
                task_type="transcription",
                input={"hypothesis": "patient reports mild headache"},
                expected_output={"reference": "patient reports mild headache"},
                tags=["transcription", "synthetic"],
            )
            .returning(table.c.id)
        )
        return int(result.scalar_one())


async def _add_run(
    engine: AsyncEngine,
    dataset_id: int,
    *,
    run_ref: str = "run-2026-10-23-1",
    budget_paise: int = 500,
    status: str = "running",
) -> int:
    table = observability_evaluation_judge_runs
    async with engine.begin() as connection:
        result = await connection.execute(
            insert(table)
            .values(
                run_ref=run_ref,
                dataset_version_id=dataset_id,
                budget_paise=budget_paise,
                status=status,
            )
            .returning(table.c.id)
        )
        return int(result.scalar_one())


async def _add_score(
    engine: AsyncEngine,
    *,
    source: str = "judge",
    judge_run_ref: str | None = "run-2026-10-23-1",
    observation_ref: str = "tx-clear",
    evaluator: str = "completeness",
) -> None:
    table = observability_evaluation_scores
    async with engine.begin() as connection:
        await connection.execute(
            insert(table).values(
                {
                    "score_date": _SCORE_DATE,
                    "source": source,
                    "observation_kind": "golden",
                    "observation_ref": observation_ref,
                    "evaluator": evaluator,
                    "data_type": "NUMERIC",
                    "value": Decimal("0.900000"),
                    "judge_run_ref": judge_run_ref,
                    "metadata": {"judge_model": "fake-judge", "prompt_version": "v1"},
                }
            )
        )


async def test_dataset_example_run_and_judge_score_round_trip(engine: AsyncEngine) -> None:
    dataset_id = await _add_dataset(engine)
    example_id = await _add_example(engine, dataset_id)
    run_id = await _add_run(engine, dataset_id)
    await _add_score(engine)

    datasets = observability_evaluation_datasets
    examples = observability_evaluation_examples
    runs = observability_evaluation_judge_runs
    scores = observability_evaluation_scores
    async with engine.connect() as connection:
        dataset = (
            await connection.execute(select(datasets).where(datasets.c.id == dataset_id))
        ).one()
        example = (
            await connection.execute(select(examples).where(examples.c.id == example_id))
        ).one()
        run = (await connection.execute(select(runs).where(runs.c.id == run_id))).one()
        score = (
            await connection.execute(select(scores).where(scores.c.judge_run_ref == run.run_ref))
        ).one()

    assert (dataset.name, dataset.version, dataset.status) == ("golden", 1, "active")
    assert example.task_type == "transcription"
    assert example.input == {"hypothesis": "patient reports mild headache"}
    assert example.expected_output == {"reference": "patient reports mild headache"}
    assert example.tags == ["transcription", "synthetic"]
    assert (run.dataset_version_id, run.budget_paise, run.status) == (dataset_id, 500, "running")
    assert score.source == "judge"
    assert score.judge_run_ref == run.run_ref
    assert score.observation_kind == "golden"
    assert score.observation_ref == example.example_ref
    assert score.evaluator == "completeness"
    assert score.metadata == {"judge_model": "fake-judge", "prompt_version": "v1"}


async def test_only_one_active_version_per_dataset_name(engine: AsyncEngine) -> None:
    await _add_dataset(engine, version=1, status="active")
    await _add_dataset(engine, version=2, status="draft")

    with pytest.raises(IntegrityError):
        await _add_dataset(engine, version=2, status="active")


async def test_dataset_version_status_is_constrained(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError):
        await _add_dataset(engine, status="published")


async def test_example_ref_is_unique_within_a_dataset(engine: AsyncEngine) -> None:
    dataset_id = await _add_dataset(engine)
    other_dataset_id = await _add_dataset(engine, version=2, status="draft")
    await _add_example(engine, dataset_id, example_ref="tx-clear")

    with pytest.raises(IntegrityError):
        await _add_example(engine, dataset_id, example_ref="tx-clear")

    await _add_example(engine, other_dataset_id, example_ref="tx-clear")


async def test_judge_uniqueness_is_partial_over_the_run(engine: AsyncEngine) -> None:
    dataset_id = await _add_dataset(engine)
    await _add_run(engine, dataset_id, run_ref="run-1")
    await _add_run(engine, dataset_id, run_ref="run-2")

    await _add_score(engine, judge_run_ref="run-1")
    await _add_score(engine, judge_run_ref="run-2")

    with pytest.raises(IntegrityError):
        await _add_score(engine, judge_run_ref="run-1")

    scores = observability_evaluation_scores
    async with engine.connect() as connection:
        result = await connection.execute(
            select(scores.c.judge_run_ref).where(
                scores.c.source == "judge",
                scores.c.observation_ref == "tx-clear",
                scores.c.evaluator == "completeness",
            )
        )
    assert {row.judge_run_ref for row in result} == {"run-1", "run-2"}


async def test_code_and_human_uniqueness_is_unchanged(engine: AsyncEngine) -> None:
    await _add_score(
        engine,
        source="code",
        judge_run_ref=None,
        evaluator="transcription_wer",
    )

    with pytest.raises(IntegrityError):
        await _add_score(
            engine,
            source="code",
            judge_run_ref=None,
            evaluator="transcription_wer",
        )

    with pytest.raises(IntegrityError):
        await _add_score(
            engine,
            source="human",
            judge_run_ref=None,
            evaluator="transcription_wer",
        )


async def test_a_run_reference_is_required_only_on_judge_rows(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError):
        await _add_score(engine, source="judge", judge_run_ref=None)

    with pytest.raises(IntegrityError):
        await _add_score(engine, source="code", judge_run_ref="run-1")


async def test_judge_run_status_is_constrained(engine: AsyncEngine) -> None:
    dataset_id = await _add_dataset(engine)
    with pytest.raises(IntegrityError):
        await _add_run(engine, dataset_id, status="paused")
