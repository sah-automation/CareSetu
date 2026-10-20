"""The Langfuse daily metrics pull - the vendor half of #750 (spec #717 decision 39).

The free tier's metrics endpoint allows about a hundred requests a day, so
Langfuse quality numbers reach Postgres by ONE batch request per nightly run
and never by a live query behind a dashboard refresh. This module owns that
single request: the fixed aggregate-only query, the basic-auth call, and the
mapping of the response into a typed day snapshot. The write into the
observability schema is the module's own seam
(``modules.observability.facade.run_langfuse_daily_pull``), and the schedule
is the nightly rollup's (``python -m worker.langfuse_metrics``).

Deliberately built on plain ``httpx`` rather than the vendor SDK's metrics
client: the injectable transport (``httpx.MockTransport``) is the seam the
ticket's "no more than one metrics request per run" test counts requests
against, and one request with no retries is a property this module can state
in its own code rather than hope the SDK preserves.

An absent ``public_key`` is a silent no-op - the pull returns ``None`` and
sends nothing, exactly like the rest of the Langfuse integration, so a project
without a Langfuse account runs the nightly job cleanly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

log = logging.getLogger(__name__)

#: The v2 metrics endpoint, relative to the configured host.
METRICS_PATH = "api/public/v2/metrics"

#: The four aggregate measures the batch asks for. They are counters over a
#: whole day - no dimension, no filter, no identifier - so nothing clinical or
#: personal can enter the request or leave it as a number.
_DAILY_MEASURES: tuple[dict[str, str], ...] = (
    {"measure": "count", "aggregation": "count"},
    {"measure": "totalTokens", "aggregation": "sum"},
    {"measure": "totalCost", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "avg"},
)

#: Rendered scales, matching the JSONB store's convention: exact money and
#: mean durations travel as text so they serialise without an encoder.
_COST_PLACES = Decimal("0.000001")
_LATENCY_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class LangfuseDailyMetrics:
    """One UTC day of aggregate AI activity, as the metrics endpoint reports it.

    Plain numbers only. Trace identifiers, model outputs and any other payload
    the vendor holds are never requested - the batch asks for counters over a
    closed window and this snapshot is all it can carry.
    """

    metric_date: date
    observation_count: int
    total_tokens: int
    total_cost_usd: Decimal
    avg_latency_ms: Decimal | None


def build_daily_query(target_date: date) -> dict[str, Any]:
    """The fixed aggregate-only query for one UTC day.

    The window is the full day (00:00 inclusive to next-day 00:00 exclusive,
    in UTC like every date in the observability schema). ``dimensions`` is
    absent and ``filters`` is empty on purpose: a query that cannot group or
    select rows cannot ask for a transcript, a patient, or an identifier, so
    the no-clinical-content rule is structural rather than a review habit.
    """
    window_start = datetime.combine(target_date, time.min, tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    return {
        "view": "observations",
        "metrics": [dict(measure) for measure in _DAILY_MEASURES],
        "filters": [],
        "fromTimestamp": window_start.isoformat().replace("+00:00", "Z"),
        "toTimestamp": window_end.isoformat().replace("+00:00", "Z"),
    }


def map_metrics_response(target_date: date, payload: Mapping[str, Any]) -> LangfuseDailyMetrics:
    """Map the vendor's first data row into the typed day snapshot.

    The endpoint answers with ``{aggregation}_{measure}`` keys; an empty
    ``data`` list (a day with no observations) reads as a day of zeros rather
    than as a missing row, so every date the pull runs lands in the store.
    """
    rows = payload.get("data") or []
    row: Mapping[str, Any] = rows[0] if rows else {}
    cost = row.get("sum_totalCost")
    latency = row.get("avg_latency")
    return LangfuseDailyMetrics(
        metric_date=target_date,
        observation_count=int(row.get("count_count") or 0),
        total_tokens=int(row.get("sum_totalTokens") or 0),
        total_cost_usd=Decimal(str(cost if cost is not None else 0)).quantize(
            _COST_PLACES, rounding=ROUND_HALF_UP
        ),
        avg_latency_ms=(
            None
            if latency is None
            else Decimal(str(latency)).quantize(_LATENCY_PLACES, rounding=ROUND_HALF_UP)
        ),
    )


async def pull_daily_metrics(
    target_date: date,
    *,
    public_key: str,
    secret_key: str,
    host: str,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> LangfuseDailyMetrics | None:
    """Fetch ``target_date``'s aggregates in EXACTLY one metrics request.

    Returns ``None`` without sending anything when ``public_key`` is absent -
    the unconfigured-vendor no-op shared by every vendor integration, so a
    missing key never fails the nightly run. A non-2xx response raises
    (``httpx.HTTPStatusError``): one failed night reports loudly and the
    operator re-runs the step for that date; a retry here would be a second
    request against the same day's allowance for the same answer.

    ``timeout_seconds`` is the caller's configuration (the daily pull is not a
    fixed ceiling of its own), and ``client`` is injectable so tests point the
    call at a fake metrics API (``httpx.MockTransport``) and count the requests
    a run makes.
    """
    if not public_key:
        log.info("langfuse keys absent; daily metrics pull skipped")
        return None

    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient(timeout=timeout_seconds)
    try:
        response = await http.get(
            f"{host.rstrip('/')}/{METRICS_PATH}",
            params={"query": json.dumps(build_daily_query(target_date))},
            auth=httpx.BasicAuth(public_key, secret_key),
        )
        response.raise_for_status()
        payload: Mapping[str, Any] = response.json()
    finally:
        if owns_client:
            await http.aclose()
    return map_metrics_response(target_date, payload)
