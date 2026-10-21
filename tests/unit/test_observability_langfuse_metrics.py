"""#750: the Langfuse daily batch pull - one metrics request, mapped, re-run safe.

Covers the ticket's acceptance criteria against a FAKE metrics API built on
``httpx.MockTransport`` (the EXT-001 SMS-adapter convention):

- A single run makes NO MORE than one metrics request, so the free tier's
  ~100 requests a day can never be spent by a refresh loop or a retry.
- The vendor response maps into the observability day snapshot, and the write
  is an upsert on the store's ``(metric_key, metric_date)`` natural key - a
  second run of the same date replaces the value instead of double-counting.
- An unconfigured vendor no-ops silently: no request, no write, no raise.
- The request is aggregate-only (no dimensions, no filters), so no clinical
  content can enter it, and only aggregate fields reach the stored value.
- The pull rides the nightly rollup job's schedule as a step, never a second
  timer and never behind a dashboard refresh.

The round-trip against real PostgreSQL lives in
``tests/integration/test_observability_langfuse_metrics_round_trip.py``; the
span-metadata allow-list that keeps PHI out of the vendor stays guarded by
``tests/unit/test_observability_langfuse_span.py``.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from modules.observability.facade import (
    METRIC_KEY_LANGFUSE_DAILY,
    EvaluationRunReport,
    LangfusePullReport,
    record_langfuse_daily_metrics,
    run_langfuse_daily_pull,
)
from observability.langfuse_metrics import (
    LangfuseDailyMetrics,
    build_daily_query,
    pull_daily_metrics,
)
from worker import langfuse_metrics as entry_point

_HOST = "https://langfuse.test"
_KEYS: dict[str, Any] = {
    "public_key": "pk-lf-test",
    "secret_key": "sk-lf-test",
    "host": _HOST,
    "timeout_seconds": 30.0,
}
_TARGET_DATE = date(2026, 10, 12)

#: One row for one day, exactly as the v2 metrics endpoint answers the batch's
#: fixed query: ``{aggregation}_{measure}`` keys, nothing else.
_FAKE_PAYLOAD: dict[str, Any] = {
    "data": [
        {
            "count_count": 42,
            "sum_totalTokens": 123_456,
            "sum_totalCost": 0.4213,
            "avg_latency": 815.555,
        }
    ]
}


def _compile(statement: Any) -> str:
    """The statement's SQL with bind params named, for dialect-level assertions.

    Literal binds are deliberately NOT inlined: the JSONB ``value`` has no
    literal renderer, so the payload itself is asserted through ``_params``.
    """
    return str(statement.compile(dialect=postgresql.dialect()))


def _params(statement: Any) -> dict[str, Any]:
    """The statement's bind values, where the store's payload assertions live."""
    return dict(statement.compile(dialect=postgresql.dialect()).params)


def _client(captured: list[httpx.Request], payload: dict[str, Any]) -> httpx.AsyncClient:
    """A client whose transport is the fake metrics API, recording every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _engine() -> tuple[MagicMock, MagicMock]:
    """An engine double whose single transaction captures executed statements."""
    connection = MagicMock()
    connection.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin = MagicMock(return_value=transaction)
    return engine, connection


# --- one metrics request per run -------------------------------------------


async def test_a_single_run_makes_exactly_one_metrics_request() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured, _FAKE_PAYLOAD) as client:
        metrics = await pull_daily_metrics(_TARGET_DATE, client=client, **_KEYS)

    assert metrics is not None
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert request.url.path == "/api/public/v2/metrics"


async def test_the_request_carries_the_vendor_basic_auth_keys() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured, _FAKE_PAYLOAD) as client:
        await pull_daily_metrics(_TARGET_DATE, client=client, **_KEYS)

    authorization = captured[0].headers["Authorization"]
    assert authorization.startswith("Basic ")
    decoded = base64.b64decode(authorization.removeprefix("Basic ")).decode()
    assert decoded == f"{_KEYS['public_key']}:{_KEYS['secret_key']}"


async def test_a_run_commits_exactly_one_upsert_on_the_natural_key() -> None:
    captured: list[httpx.Request] = []
    engine, connection = _engine()
    async with _client(captured, _FAKE_PAYLOAD) as client:
        report = await run_langfuse_daily_pull(engine, _TARGET_DATE, client=client, **_KEYS)

    assert report == LangfusePullReport(metric_date=_TARGET_DATE, written=True)
    assert len(captured) == 1
    connection.execute.assert_awaited_once()
    statement = connection.execute.await_args.args[0]
    compiled = _compile(statement)
    assert "INSERT INTO observability.observability_business_daily" in compiled
    assert "ON CONFLICT (metric_key, metric_date) DO UPDATE" in compiled
    assert _params(statement)["metric_key"] == METRIC_KEY_LANGFUSE_DAILY
    assert _params(statement)["metric_date"] == _TARGET_DATE


async def test_the_transaction_is_opened_once_for_the_whole_pull() -> None:
    captured: list[httpx.Request] = []
    engine, _connection = _engine()
    async with _client(captured, _FAKE_PAYLOAD) as client:
        await run_langfuse_daily_pull(engine, _TARGET_DATE, client=client, **_KEYS)

    assert engine.begin.call_count == 1


# --- mapping the vendor response -------------------------------------------


async def test_the_response_maps_into_the_day_snapshot() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured, _FAKE_PAYLOAD) as client:
        metrics = await pull_daily_metrics(_TARGET_DATE, client=client, **_KEYS)

    assert metrics == LangfuseDailyMetrics(
        metric_date=_TARGET_DATE,
        observation_count=42,
        total_tokens=123_456,
        total_cost_usd=Decimal("0.421300"),
        avg_latency_ms=Decimal("815.56"),
    )


async def test_an_empty_data_list_reads_as_a_day_without_observations() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured, {"data": []}) as client:
        metrics = await pull_daily_metrics(_TARGET_DATE, client=client, **_KEYS)

    assert metrics == LangfuseDailyMetrics(
        metric_date=_TARGET_DATE,
        observation_count=0,
        total_tokens=0,
        total_cost_usd=Decimal("0.000000"),
        avg_latency_ms=None,
    )


async def test_the_stored_value_carries_only_aggregate_fields() -> None:
    captured: list[httpx.Request] = []
    engine, connection = _engine()
    async with _client(captured, _FAKE_PAYLOAD) as client:
        await run_langfuse_daily_pull(engine, _TARGET_DATE, client=client, **_KEYS)

    value = _params(connection.execute.await_args.args[0])["value"]
    assert set(value) == {
        "vendor",
        "observation_count",
        "total_tokens",
        "total_cost_usd",
        "avg_latency_ms",
    }
    assert value["observation_count"] == 42
    assert value["total_tokens"] == 123_456


# --- the aggregate-only request --------------------------------------------


def test_the_query_names_one_utc_day_with_aggregates_only() -> None:
    query = build_daily_query(_TARGET_DATE)

    assert query["view"] == "observations"
    assert query["fromTimestamp"] == "2026-10-12T00:00:00Z"
    assert query["toTimestamp"] == "2026-10-13T00:00:00Z"
    assert query["filters"] == []
    assert "dimensions" not in query
    assert {measure["measure"] for measure in query["metrics"]} == {
        "count",
        "totalTokens",
        "totalCost",
        "latency",
    }


async def test_the_wire_request_carries_that_query_verbatim() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured, _FAKE_PAYLOAD) as client:
        await pull_daily_metrics(_TARGET_DATE, client=client, **_KEYS)

    wire_query = json.loads(captured[0].url.params["query"])
    assert wire_query == build_daily_query(_TARGET_DATE)


# --- the unconfigured vendor no-ops silently --------------------------------


async def test_an_absent_key_makes_no_request_and_returns_none() -> None:
    captured: list[httpx.Request] = []
    async with _client(captured, _FAKE_PAYLOAD) as client:
        metrics = await pull_daily_metrics(
            _TARGET_DATE,
            public_key="",
            secret_key="",
            host=_HOST,
            timeout_seconds=30.0,
            client=client,
        )

    assert metrics is None
    assert captured == []


async def test_a_run_without_keys_never_touches_the_database() -> None:
    captured: list[httpx.Request] = []
    engine = MagicMock()
    engine.begin = MagicMock(side_effect=AssertionError("the engine must not be used"))
    async with _client(captured, _FAKE_PAYLOAD) as client:
        report = await run_langfuse_daily_pull(
            engine,
            _TARGET_DATE,
            public_key="",
            secret_key="",
            host=_HOST,
            timeout_seconds=30.0,
            client=client,
        )

    assert report == LangfusePullReport(metric_date=None, written=False)
    assert captured == []
    engine.begin.assert_not_called()


# --- the write path itself --------------------------------------------------


async def test_the_writer_replaces_the_snapshot_on_a_re_run() -> None:
    connection = MagicMock()
    connection.execute = AsyncMock()

    for cost in (Decimal("0.421300"), Decimal("0.700000")):
        await record_langfuse_daily_metrics(
            connection,
            _TARGET_DATE,
            LangfuseDailyMetrics(
                metric_date=_TARGET_DATE,
                observation_count=7,
                total_tokens=900,
                total_cost_usd=cost,
                avg_latency_ms=Decimal("12.50"),
            ),
        )

    assert connection.execute.await_count == 2
    statement = connection.execute.await_args.args[0]
    assert "ON CONFLICT (metric_key, metric_date) DO UPDATE" in _compile(statement)
    # The whole value is refreshed, never merged: the second run's cost is the
    # row's cost, so the same date cannot accumulate two snapshots.
    assert _params(statement)["value"]["total_cost_usd"] == "0.700000"


# --- the scheduled entry point (worker.langfuse_metrics) --------------------


def test_the_default_date_is_yesterday_utc() -> None:
    """The step pulls the same day the rollup just rolled, never today."""
    assert entry_point.default_target_date(date(2026, 10, 13)) == date(2026, 10, 12)


def test_an_explicit_date_overrides_the_default() -> None:
    assert entry_point.build_parser().parse_args(["--date", "2026-10-02"]).date == date(2026, 10, 2)


def test_a_malformed_date_is_refused() -> None:
    with pytest.raises(SystemExit):
        entry_point.build_parser().parse_args(["--date", "10-02-2026"])


def test_an_unconfigured_vendor_still_scores_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keyless means no vendor requests, not no scores: the local run still lands.

    Deterministic evaluation needs no vendor account, and decision data must
    not depend on vendor churn (ADR-0024 D2), so with the #753 evaluation gate
    on (a MagicMock attribute is truthy, as any opted-in deployment's is) the
    worker invokes both seams; each seam owns its own unconfigured-vendor no-op.
    """
    settings = MagicMock(langfuse_public_key="")
    monkeypatch.setattr(entry_point, "get_settings", lambda: settings)
    monkeypatch.setattr(entry_point, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(entry_point, "create_async_engine", lambda _url: _DisposableEngine())

    pulls: list[str] = []
    evaluated: list[str] = []

    async def _fake_pull(engine: object, target_date: date, **kwargs: Any) -> LangfusePullReport:
        pulls.append(kwargs["public_key"])
        return LangfusePullReport(metric_date=None, written=False)

    async def _fake_evaluate(
        engine: object, target_date: date, **kwargs: Any
    ) -> EvaluationRunReport:
        evaluated.append(kwargs["public_key"])
        return EvaluationRunReport(
            metric_date=target_date, score_count=12, golden_count=12, vendor_scored=None
        )

    monkeypatch.setattr(entry_point, "run_langfuse_daily_pull", _fake_pull)
    monkeypatch.setattr(entry_point, "run_daily_evaluation", _fake_evaluate)

    assert entry_point.main([]) == 0
    # Both seams are invoked; the pull no-ops on the empty key, the local
    # evaluation does not - it records the day's scores with no vendor post.
    assert pulls == [""]
    assert evaluated == [""]


def test_a_successful_pull_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock(
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_host=_HOST,
        langfuse_timeout_seconds=30.0,
        database_url="postgresql+asyncpg://u:p@h/db",
    )
    monkeypatch.setattr(entry_point, "get_settings", lambda: settings)
    monkeypatch.setattr(entry_point, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(entry_point, "create_async_engine", lambda _url: _DisposableEngine())

    seen: list[date] = []
    evaluated: list[date] = []

    async def _fake_pull(engine: object, target_date: date, **kwargs: Any) -> LangfusePullReport:
        seen.append(target_date)
        return LangfusePullReport(metric_date=target_date, written=True)

    async def _fake_evaluate(
        engine: object, target_date: date, **kwargs: Any
    ) -> EvaluationRunReport:
        evaluated.append(target_date)
        return EvaluationRunReport(
            metric_date=target_date, score_count=13, golden_count=12, vendor_scored=12
        )

    monkeypatch.setattr(entry_point, "run_langfuse_daily_pull", _fake_pull)
    monkeypatch.setattr(entry_point, "run_daily_evaluation", _fake_evaluate)

    assert entry_point.main(["--date", "2026-10-12"]) == 0
    assert seen == [date(2026, 10, 12)]
    # AC5: the evaluator batch runs on the SAME invocation and date as the pull.
    assert evaluated == [date(2026, 10, 12)]


def test_the_evaluation_gate_skips_the_evaluators_but_still_pulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#753: EVALUATION_ENABLED off skips exactly the evaluators, nothing else.

    The metrics pull is its own seam with its own vendor no-op, so a deployment
    that has not opted into evaluation still lands the day's Langfuse metrics:
    the gate moves the feature it names and the exit code stays 0.
    """
    settings = MagicMock(
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_host=_HOST,
        langfuse_timeout_seconds=30.0,
        database_url="postgresql+asyncpg://u:p@h/db",
        evaluation_enabled=False,
    )
    monkeypatch.setattr(entry_point, "get_settings", lambda: settings)
    monkeypatch.setattr(entry_point, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(entry_point, "create_async_engine", lambda _url: _DisposableEngine())

    seen: list[date] = []

    async def _fake_pull(engine: object, target_date: date, **kwargs: Any) -> LangfusePullReport:
        seen.append(target_date)
        return LangfusePullReport(metric_date=target_date, written=True)

    async def _fail_evaluate(*_a: object, **_k: object) -> EvaluationRunReport:
        raise AssertionError("the evaluators must not run when the gate is off")

    monkeypatch.setattr(entry_point, "run_langfuse_daily_pull", _fake_pull)
    monkeypatch.setattr(entry_point, "run_daily_evaluation", _fail_evaluate)

    assert entry_point.main(["--date", "2026-10-12"]) == 0
    assert seen == [date(2026, 10, 12)]


def test_a_failed_pull_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock(
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_host=_HOST,
        langfuse_timeout_seconds=30.0,
        database_url="postgresql+asyncpg://u:p@h/db",
    )
    monkeypatch.setattr(entry_point, "get_settings", lambda: settings)
    monkeypatch.setattr(entry_point, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(entry_point, "create_async_engine", lambda _url: _DisposableEngine())

    async def _boom(*_a: object, **_k: object) -> object:
        raise httpx.ConnectError("vendor unreachable")

    monkeypatch.setattr(entry_point, "run_langfuse_daily_pull", _boom)

    assert entry_point.main(["--date", "2026-10-12"]) == 1


class _DisposableEngine:
    """A stand-in engine whose ``dispose`` is awaited like the real one's."""

    async def dispose(self) -> None:
        return None
