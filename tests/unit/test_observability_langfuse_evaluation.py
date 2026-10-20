"""#751: the vendor half and the facade seam - observation-level scores, two requests.

Covers the ticket's recording acceptance criteria against a FAKE Langfuse API
built on ``httpx.MockTransport`` (the #750 / EXT-001 convention):

- Observation-level, never trace-level: every posted score names its
  ``observationId``, and a score that cannot is refused before a request is
  made - the trace-level evaluation path is deprecated with the November 2026
  cloud cutover.
- At most two requests per run (one ingestion batch, one scores post), both
  carrying the vendor's basic auth; an unconfigured vendor sends nothing.
- The golden run's observations carry allow-listed metadata only - never
  input, output or transcript text - so the vendor's evaluation history stays
  PHI-free.
- Deterministic score ids: a repeat post of the same date upserts the same
  rows instead of stacking duplicates.
- The facade writes BOTH kinds of score locally (production rows and golden
  examples) in one transaction, but posts only the golden ones, because
  production scores have no vendor observation id to name.

The domain-level evaluator tests live in ``test_observability_evaluation.py``;
the round-trip against real PostgreSQL lives in
``tests/integration/test_observability_evaluation_round_trip.py``.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
from sqlalchemy.dialects import postgresql

from modules.observability.domain.consumer import AI_JOB_SPEND_STATUS_COMPLETED
from modules.observability.domain.evaluation import (
    EVAL_JOB_SUCCEEDED,
    EVALUATOR_NAMES,
    EvaluationScore,
    evaluate_golden_dataset,
    evaluate_job_row,
    golden_observation_id,
    golden_trace_id,
    vendor_score_id,
)
from modules.observability.domain.golden_dataset import (
    GOLDEN_DATASET_VERSION,
    GOLDEN_STRUCTURINGS,
    GOLDEN_TRANSCRIPTIONS,
)
from modules.observability.facade import (
    EvaluationRunReport,
    record_evaluation_scores,
    run_daily_evaluation,
)
from observability.langfuse_evaluation import (
    INGESTION_PATH,
    SCORES_PATH,
    build_ingestion_batch,
    build_score_bodies,
    post_evaluation_scores,
)
from observability.langfuse_span import ALLOWED_SPAN_METADATA_KEYS

_HOST = "https://langfuse.test"
_KEYS: dict[str, Any] = {
    "public_key": "pk-lf-test",
    "secret_key": "sk-lf-test",
    "host": _HOST,
    "timeout_seconds": 30.0,
}
_TARGET_DATE = date(2026, 10, 12)
_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"

#: One production row for the day: completed, traced, allow-listed columns only.
_JOB_ROW: dict[str, Any] = {
    "ai_job_ref": 7,
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "task_type": "structuring",
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_paise": 120,
    "status": AI_JOB_SPEND_STATUS_COMPLETED,
    "trace_id": _TRACE_ID,
}

_INGESTION = f"/{INGESTION_PATH}"
_SCORES = f"/{SCORES_PATH}"


def _compile(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _literal_sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _client(captured: list[httpx.Request]) -> httpx.AsyncClient:
    """A client backed by a fake API that answers both evaluation endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == _INGESTION:
            return httpx.Response(200, json={"statuses": [{"success": True}]})
        if request.url.path == _SCORES:
            return httpx.Response(204)
        return httpx.Response(500, json={"error": "unexpected path"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _golden_scores() -> list[EvaluationScore]:
    return evaluate_golden_dataset(_TARGET_DATE)


# --- the vendor requests themselves -----------------------------------------


async def test_a_run_posts_exactly_two_requests_in_order() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        posted = await post_evaluation_scores(
            _TARGET_DATE, _golden_scores(), client=client, **_KEYS
        )

    assert posted == len(_golden_scores())
    assert [request.url.path for request in captured] == [_INGESTION, _SCORES]
    for request in captured:
        authorization = request.headers["Authorization"]
        decoded = base64.b64decode(authorization.removeprefix("Basic ")).decode()
        assert decoded == f"{_KEYS['public_key']}:{_KEYS['secret_key']}"


async def test_an_absent_key_posts_nothing() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured) as client:
        posted = await post_evaluation_scores(
            _TARGET_DATE,
            _golden_scores(),
            public_key="",
            secret_key="",
            host=_HOST,
            timeout_seconds=30.0,
            client=client,
        )

    assert posted is None
    assert captured == []


async def test_a_score_without_an_observation_is_refused_before_any_request() -> None:
    """Production scores stay local: naming an observation we do not mint is refused."""
    captured: list[httpx.Request] = []
    production = evaluate_job_row(_JOB_ROW, _TARGET_DATE)
    assert all(score.observation_id is None for score in production)

    async with _client(captured) as client:
        try:
            await post_evaluation_scores(_TARGET_DATE, production, client=client, **_KEYS)
        except ValueError as exc:
            assert "observation_id" in str(exc)
        else:
            raise AssertionError("a score without an observation must be refused")

    assert captured == []


# --- what the two requests carry ---------------------------------------------


def test_the_ingestion_batch_creates_one_trace_and_one_observation_per_example() -> None:
    batch = build_ingestion_batch(_TARGET_DATE, _golden_scores())
    events = batch["batch"]
    assert isinstance(events, list)

    trace_events = [event for event in events if event["type"] == "trace-create"]
    observation_events = [event for event in events if event["type"] == "observation-create"]
    assert len(trace_events) == 1
    assert trace_events[0]["body"]["id"] == golden_trace_id(_TARGET_DATE)
    assert trace_events[0]["body"]["metadata"]["model"] == GOLDEN_DATASET_VERSION

    assert len(observation_events) == 6
    assert {event["body"]["id"] for event in observation_events} == {
        golden_observation_id(_TARGET_DATE, example_id)
        for example_id in (
            *(example.example_id for example in GOLDEN_TRANSCRIPTIONS),
            *(example.example_id for example in GOLDEN_STRUCTURINGS),
        )
    }
    for event in observation_events:
        assert event["body"]["traceId"] == golden_trace_id(_TARGET_DATE)
        assert event["body"]["type"] == "SPAN"
        assert event["body"]["startTime"] == event["body"]["endTime"] == "2026-10-12T00:00:00Z"


def test_no_request_body_can_carry_content_only_allow_listed_metadata() -> None:
    batch = build_ingestion_batch(_TARGET_DATE, _golden_scores())
    for event in batch["batch"]:
        body = event["body"]
        assert "input" not in body and "output" not in body
        metadata = body["metadata"]
        assert set(metadata) <= ALLOWED_SPAN_METADATA_KEYS
        assert not any(key in metadata for key in ("transcript", "patient_name"))

    for body in build_score_bodies(_golden_scores()):
        assert set(body) == {
            "id",
            "name",
            "value",
            "dataType",
            "traceId",
            "observationId",
        }
        assert body["name"] in EVALUATOR_NAMES
        assert body["dataType"] in {"NUMERIC", "BOOLEAN"}


def test_score_bodies_are_deterministic_and_derive_their_ids() -> None:
    scores = _golden_scores()
    first = build_score_bodies(scores)
    second = build_score_bodies(list(reversed(scores)))
    assert first == second

    for body in first:
        assert body["id"] == vendor_score_id(body["observationId"], body["name"])
    ids = [body["id"] for body in first]
    assert len(ids) == len(set(ids)), "one id per (observation, evaluator), no duplicates"


def test_the_facade_writes_both_kinds_locally_but_posts_only_the_golden_scores() -> None:
    connection = MagicMock()
    load_result = MagicMock()
    load_result.mappings.return_value = [dict(_JOB_ROW)]
    connection.execute = AsyncMock(side_effect=[load_result, MagicMock()])
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin = MagicMock(return_value=transaction)

    captured: list[httpx.Request] = []

    async def _run() -> EvaluationRunReport:
        async with _client(captured) as client:
            return await run_daily_evaluation(engine, _TARGET_DATE, client=client, **_KEYS)

    report = asyncio.run(_run())

    golden_count = len(_golden_scores())
    assert report == EvaluationRunReport(
        metric_date=_TARGET_DATE,
        score_count=golden_count + 1,
        golden_count=golden_count,
        vendor_scored=golden_count,
    )
    assert engine.begin.call_count == 1
    assert connection.execute.await_count == 2

    upsert = connection.execute.await_args_list[1].args[0]
    compiled = _literal_sql(upsert)
    assert "INSERT INTO observability.observability_evaluation_scores" in compiled
    assert (
        "ON CONFLICT (score_date, observation_kind, observation_ref, evaluator) DO UPDATE"
        in compiled
    )
    assert "'ai_job', '7'" in compiled, "the production row is recorded locally"
    assert f"'{EVAL_JOB_SUCCEEDED}', 'BOOLEAN', 1.0" in compiled

    scores_request = captured[-1]
    assert scores_request.url.path == _SCORES
    posted_bodies = json.loads(scores_request.content)
    assert all(body["observationId"] for body in posted_bodies)
    assert not any(body["name"] == EVAL_JOB_SUCCEEDED for body in posted_bodies)
    assert not any(body["traceId"] == _TRACE_ID for body in posted_bodies)


async def test_an_unconfigured_vendor_still_records_scores_but_sends_nothing() -> None:
    captured: list[httpx.Request] = []
    connection = MagicMock()
    load_result = MagicMock()
    load_result.mappings.return_value = []
    connection.execute = AsyncMock(side_effect=[load_result, MagicMock()])
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin = MagicMock(return_value=transaction)

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

    golden_count = len(_golden_scores())
    assert report.score_count == golden_count
    assert report.vendor_scored is None
    assert captured == []
    assert connection.execute.await_count == 2


# --- the write path itself ---------------------------------------------------


async def test_the_writer_replaces_scores_on_a_re_run() -> None:
    connection = MagicMock()
    connection.execute = AsyncMock()
    scores = _golden_scores()

    await record_evaluation_scores(connection, scores)
    await record_evaluation_scores(connection, scores)

    assert connection.execute.await_count == 2
    statement = connection.execute.await_args.args[0]
    assert "ON CONFLICT (score_date, observation_kind, observation_ref, evaluator) DO UPDATE" in (
        _compile(statement)
    )


async def test_the_writer_never_overwrites_a_human_verdict() -> None:
    """#752's human rows outrank the nightly recompute and must survive it.

    The upsert's update clause is guarded on the stored row being a code row,
    so a future human verdict on the same observation and evaluator is left
    untouched by the nightly batch.
    """
    connection = MagicMock()
    connection.execute = AsyncMock()

    await record_evaluation_scores(connection, _golden_scores())

    compiled = _compile(connection.execute.await_args.args[0])
    assert "WHERE observability.observability_evaluation_scores.source =" in compiled


async def test_an_empty_batch_writes_nothing() -> None:
    connection = MagicMock()
    connection.execute = AsyncMock()

    await record_evaluation_scores(connection, [])

    connection.execute.assert_not_awaited()
