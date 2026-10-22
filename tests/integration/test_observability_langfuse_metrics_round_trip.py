"""#750: the Langfuse daily batch pull against real PostgreSQL.

Runs the batch seam twice on the SAME UTC date against a fake metrics API
(``httpx.MockTransport``) and reads the generic store back: exactly one
``observability_business_daily`` row keyed ``(langfuse.daily, date)``, landing
the first run's snapshot and then the second run's changed figures. A re-run
replaces the value rather than stacking on it, so a retried nightly step
cannot double-count - and each run made exactly one metrics request.

The unconfigured-vendor case is driven against the same real engine: no row,
no request, no error.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable.
The shared integration conftest migrates to head once per file and empties the
observability aggregates before each test.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.observability.facade import (
    METRIC_KEY_LANGFUSE_DAILY,
    LangfusePullReport,
    run_langfuse_daily_pull,
)
from modules.observability.schema.models import observability_business_daily

_HOST = "https://langfuse.test"
_KEYS: dict[str, Any] = {
    "public_key": "pk-lf-test",
    "secret_key": "sk-lf-test",
    "host": _HOST,
    "timeout_seconds": 30.0,
}
_TARGET_DATE = date(2026, 10, 12)


def _payload(*, observations: int, tokens: int, cost: float, latency: float) -> dict[str, Any]:
    """One v2 metrics row, as the vendor answers the batch's fixed query."""
    return {
        "data": [
            {
                "count_count": observations,
                "sum_totalTokens": tokens,
                "sum_totalCost": cost,
                "avg_latency": latency,
            }
        ]
    }


def _client(captured: list[httpx.Request], payload: dict[str, Any]) -> httpx.AsyncClient:
    """A client backed by the fake metrics API, recording every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _stored_rows(engine: AsyncEngine) -> list[Any]:
    """Every generic-store row, read back in the natural key's order."""
    async with engine.connect() as connection:
        result = await connection.execute(
            select(
                observability_business_daily.c.metric_key,
                observability_business_daily.c.metric_date,
                observability_business_daily.c.value,
            ).order_by(
                observability_business_daily.c.metric_key,
                observability_business_daily.c.metric_date,
            )
        )
        return list(result.all())


async def test_a_re_run_of_the_same_date_replaces_the_snapshot(engine: AsyncEngine) -> None:
    captured: list[httpx.Request] = []
    first = _payload(observations=42, tokens=123_456, cost=0.4213, latency=815.555)
    async with _client(captured, first) as client:
        report = await run_langfuse_daily_pull(engine, _TARGET_DATE, client=client, **_KEYS)

    assert report == LangfusePullReport(metric_date=_TARGET_DATE, written=True)
    rows = await _stored_rows(engine)
    assert len(rows) == 1
    assert rows[0].metric_key == METRIC_KEY_LANGFUSE_DAILY
    assert rows[0].metric_date == _TARGET_DATE
    assert rows[0].value == {
        "vendor": "langfuse",
        "observation_count": 42,
        "total_tokens": 123_456,
        "total_cost_usd": "0.421300",
        "avg_latency_ms": "815.56",
    }

    second = _payload(observations=7, tokens=900, cost=0.7, latency=12.5)
    async with _client(captured, second) as client:
        rerun = await run_langfuse_daily_pull(engine, _TARGET_DATE, client=client, **_KEYS)

    assert rerun.written is True
    rows = await _stored_rows(engine)
    assert len(rows) == 1
    assert rows[0].value == {
        "vendor": "langfuse",
        "observation_count": 7,
        "total_tokens": 900,
        "total_cost_usd": "0.700000",
        "avg_latency_ms": "12.50",
    }
    # One request per run, never a retry and never a second call for the re-run.
    assert len(captured) == 2


async def test_each_run_writes_only_its_own_date(engine: AsyncEngine) -> None:
    captured: list[httpx.Request] = []
    payload = _payload(observations=3, tokens=10, cost=0.01, latency=5.0)
    other_date = date(2026, 10, 11)
    async with _client(captured, payload) as client:
        await run_langfuse_daily_pull(engine, _TARGET_DATE, client=client, **_KEYS)
        await run_langfuse_daily_pull(engine, other_date, client=client, **_KEYS)

    rows = await _stored_rows(engine)
    assert [row.metric_date for row in rows] == [other_date, _TARGET_DATE]
    assert all(row.metric_key == METRIC_KEY_LANGFUSE_DAILY for row in rows)


async def test_an_unconfigured_vendor_writes_no_row(engine: AsyncEngine) -> None:
    captured: list[httpx.Request] = []
    async with _client(
        captured, _payload(observations=1, tokens=1, cost=0.0, latency=1.0)
    ) as client:
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
    assert await _stored_rows(engine) == []
