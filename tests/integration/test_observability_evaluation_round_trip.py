"""#751: the code-evaluator batch against real PostgreSQL.

Seeds one UTC day of AI-job spend (one completed job, one failed job), runs
``run_daily_evaluation`` twice against a fake Langfuse API
(``httpx.MockTransport``), and reads ``observability_evaluation_scores`` back:

- every production row and every golden example lands a score, numeric or
  boolean, in ONE short transaction per run;
- a re-run of the same date replaces its rows (the unique natural key)
  instead of stacking duplicates - and makes no third request;
- the scores AGGREGATE in SQL: ``GROUP BY evaluator`` with counts and means
  over the mixed numeric/boolean values, the property decision 40 turns on;
- every production score carries its job's ``trace_id``, the #752 join: the
  failed job's ``job_succeeded`` score is findable by that trace alone;
- an unconfigured vendor still records every score locally and sends nothing;
- a human verdict on the same observation and evaluator (#752's queue)
  outranks the nightly recompute and survives a re-run untouched.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable.
The shared integration conftest migrates to head once per file (this table is
in its ``OBSERVABILITY_TABLES`` truncation list) and empties the observability
aggregates before each test.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.observability.domain.consumer import (
    AI_JOB_SPEND_STATUS_COMPLETED,
    AI_JOB_SPEND_STATUS_FAILED,
)
from modules.observability.domain.evaluation import (
    EVAL_JOB_SUCCEEDED,
    EVAL_TRANSCRIPTION_WER,
    evaluate_golden_dataset,
    golden_trace_id,
)
from modules.observability.facade import EvaluationRunReport, run_daily_evaluation
from modules.observability.schema.models import (
    observability_ai_job_spend,
    observability_evaluation_scores,
)

_HOST = "https://langfuse.test"
_KEYS: dict[str, Any] = {
    "public_key": "pk-lf-test",
    "secret_key": "sk-lf-test",
    "host": _HOST,
    "timeout_seconds": 30.0,
}
_TARGET_DATE = date(2026, 10, 12)
_COMPLETED_TRACE = "0af7651916cd43dd8448eb211c80319c"
_FAILED_TRACE = "b11e3ad2a09b4d0f9c7e6a5d4c3b2a19"
_GOLDEN_COUNT = len(evaluate_golden_dataset(_TARGET_DATE))


def _client(captured: list[httpx.Request]) -> httpx.AsyncClient:
    """A client backed by a fake API answering both evaluation endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/api/public/ingestion":
            return httpx.Response(200, json={"statuses": [{"success": True}]})
        if request.url.path == "/api/public/scores":
            return httpx.Response(204)
        return httpx.Response(500, json={"error": "unexpected path"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _seed_jobs(engine: AsyncEngine) -> None:
    """One completed and one failed job on the target day, both traced."""
    async with engine.begin() as connection:
        await connection.execute(
            insert(observability_ai_job_spend).values(
                [
                    {
                        "usage_date": _TARGET_DATE,
                        "ai_job_ref": 101,
                        "intake_ref": 11,
                        "patient_key": "pk-fake-hash-0001",
                        "provider": "gemini",
                        "model": "gemini-2.5-flash",
                        "task_type": "structuring",
                        "status": AI_JOB_SPEND_STATUS_COMPLETED,
                        "trace_id": _COMPLETED_TRACE,
                    },
                    {
                        "usage_date": _TARGET_DATE,
                        "ai_job_ref": 102,
                        "intake_ref": 12,
                        "patient_key": "pk-fake-hash-0002",
                        "provider": "whisper",
                        "model": "whisper-1",
                        "task_type": "transcription",
                        "status": AI_JOB_SPEND_STATUS_FAILED,
                        "failure_reason": "provider timeout",
                        "trace_id": _FAILED_TRACE,
                    },
                ]
            )
        )


async def _stored_rows(engine: AsyncEngine) -> list[Any]:
    """Every score row, read back in a stable order."""
    table = observability_evaluation_scores
    async with engine.connect() as connection:
        result = await connection.execute(
            select(table).order_by(
                table.c.observation_kind,
                table.c.observation_ref,
                table.c.evaluator,
            )
        )
        return list(result.mappings())


async def test_a_batch_scores_production_and_golden_then_a_re_run_replaces_it(
    engine: AsyncEngine,
) -> None:
    await _seed_jobs(engine)
    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        report = await run_daily_evaluation(engine, _TARGET_DATE, client=client, **_KEYS)

    golden_count = _GOLDEN_COUNT
    assert report == EvaluationRunReport(
        metric_date=_TARGET_DATE,
        score_count=golden_count + 2,
        golden_count=golden_count,
        vendor_scored=golden_count,
    )
    # AC5's vendor side: exactly two requests per run, observation-level.
    assert [request.url.path for request in captured] == [
        "/api/public/ingestion",
        "/api/public/scores",
    ]

    rows = await _stored_rows(engine)
    assert len(rows) == golden_count + 2

    production = [row for row in rows if row.observation_kind == "ai_job"]
    assert [row.observation_ref for row in production] == ["101", "102"]
    assert {row.evaluator for row in production} == {EVAL_JOB_SUCCEEDED}
    by_ref = {row.observation_ref: row for row in production}
    assert float(by_ref["101"].value) == 1.0
    assert float(by_ref["102"].value) == 0.0
    assert by_ref["101"].trace_id == _COMPLETED_TRACE
    assert by_ref["102"].trace_id == _FAILED_TRACE
    assert {row.data_type for row in production} == {"BOOLEAN"}

    golden = [row for row in rows if row.observation_kind == "golden"]
    assert len(golden) == golden_count
    assert {row.trace_id for row in golden} == {golden_trace_id(_TARGET_DATE)}
    assert {row.source for row in rows} == {"code"}
    assert {row.score_date for row in rows} == {_TARGET_DATE}

    async with _client(captured) as client:
        rerun = await run_daily_evaluation(engine, _TARGET_DATE, client=client, **_KEYS)

    assert rerun == report
    rerun_rows = await _stored_rows(engine)
    assert len(rerun_rows) == golden_count + 2, "a re-run replaces, never stacks"
    assert len(captured) == 4, "two requests per run, no retries"


async def test_the_recorded_scores_aggregate_in_sql(engine: AsyncEngine) -> None:
    """AC3: numeric-or-boolean is what makes day-level aggregation possible."""
    await _seed_jobs(engine)
    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        await run_daily_evaluation(engine, _TARGET_DATE, client=client, **_KEYS)

    table = observability_evaluation_scores
    async with engine.connect() as connection:
        result = await connection.execute(
            select(
                table.c.evaluator,
                func.count().label("score_count"),
                func.avg(table.c.value).label("score_avg"),
            ).group_by(table.c.evaluator)
        )
        aggregates = {row.evaluator: (row.score_count, row.score_avg) for row in result}

    assert set(aggregates) == {
        EVAL_JOB_SUCCEEDED,
        EVAL_TRANSCRIPTION_WER,
        "transcription_well_formed",
        "structuring_field_accuracy",
        "structuring_confidence_met",
    }
    job_count, job_avg = aggregates[EVAL_JOB_SUCCEEDED]
    assert job_count == 2
    assert job_avg == Decimal("0.500000")

    wer_count, wer_avg = aggregates[EVAL_TRANSCRIPTION_WER]
    assert wer_count == 3
    # (0.0 + 0.111111 + 1.0) / 3 - the mixed golden values, averaged.
    assert wer_avg is not None
    assert float(wer_avg) == pytest.approx(0.370370, abs=1e-6)

    for _evaluator, (_count, average) in aggregates.items():
        assert average is not None


async def test_a_human_would_find_the_score_by_the_calls_trace(engine: AsyncEngine) -> None:
    """AC4/#752: trace_id is the join from an annotated call to its score."""
    await _seed_jobs(engine)
    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        await run_daily_evaluation(engine, _TARGET_DATE, client=client, **_KEYS)

    table = observability_evaluation_scores
    async with engine.connect() as connection:
        result = await connection.execute(
            select(table.c.value, table.c.data_type).where(
                table.c.trace_id == _FAILED_TRACE,
                table.c.evaluator == EVAL_JOB_SUCCEEDED,
            )
        )
        rows = list(result)

    assert len(rows) == 1
    assert rows[0].data_type == "BOOLEAN"
    assert float(rows[0].value) == 0.0


async def test_an_unconfigured_vendor_still_records_every_score(engine: AsyncEngine) -> None:
    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        report = await run_daily_evaluation(
            engine,
            _TARGET_DATE,
            public_key="",
            secret_key="",
            host=_HOST,
            timeout_seconds=30.0,
            client=client,
        )

    assert report.score_count == _GOLDEN_COUNT
    assert report.vendor_scored is None
    assert captured == []
    assert len(await _stored_rows(engine)) == _GOLDEN_COUNT


async def test_a_nightly_re_run_never_clobbers_a_human_verdict(engine: AsyncEngine) -> None:
    """#752's human row shares the natural key but outranks tonight's recompute."""
    await _seed_jobs(engine)
    table = observability_evaluation_scores
    async with engine.begin() as connection:
        await connection.execute(
            insert(table).values(
                {
                    "score_date": _TARGET_DATE,
                    "source": "human",
                    "observation_kind": "ai_job",
                    "observation_ref": "102",
                    "trace_id": _FAILED_TRACE,
                    "evaluator": EVAL_JOB_SUCCEEDED,
                    "data_type": "BOOLEAN",
                    "value": Decimal("1"),
                }
            )
        )

    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        await run_daily_evaluation(engine, _TARGET_DATE, client=client, **_KEYS)

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                select(table.c.source, table.c.value).where(
                    table.c.observation_kind == "ai_job",
                    table.c.observation_ref == "102",
                    table.c.evaluator == EVAL_JOB_SUCCEEDED,
                )
            )
        ).one()
    assert row.source == "human", "the nightly code batch leaves the human verdict untouched"
    assert row.value == Decimal("1")
