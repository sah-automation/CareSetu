"""Runnable entry point for the #750 Langfuse daily batch pull.

``python -m worker.langfuse_metrics`` - the second step of the scheduled
``observability-rollup.yml`` job, on the SAME schedule as the rollup it follows
(spec #717 decision 39: Langfuse metrics reach the observability schema by one
daily batch, never behind a live dashboard refresh, because the free tier's
metrics endpoint allows ~100 requests a day). One invocation makes at most one
metrics request for one date - there is no backfill flag here by design: a
window sweep would spend the daily allowance on N requests in one run, and a
missed date is re-pulled with ``--date`` instead.

The default date is YESTERDAY's UTC day - the same day the rollup step just
rolled - so the store's ``(metric_key, metric_date)`` rows line up with the
rollup ledger. Re-running the step after a fix lands on the same date and
replaces the snapshot rather than double-counting. With ``LANGFUSE_PUBLIC_KEY``
absent the run is a silent no-op that exits 0, exactly like every other vendor
integration: a project without a Langfuse account must not fail the nightly job.

Logging is configured once with its own service name so batch-pull lines stay
separable from the rollup's, mirroring ``worker.rollup``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from modules.observability.facade import LangfusePullReport, run_langfuse_daily_pull
from observability.logging import configure_logging

logger = logging.getLogger(__name__)

SERVICE_LANGFUSE_METRICS = "caresetu-langfuse-metrics"


def parse_target_date(value: str) -> date:
    """Parse a ``--date`` argument, refusing anything that is not ``YYYY-MM-DD``."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--date must be YYYY-MM-DD, got {value!r}") from exc


def default_target_date(today: date) -> date:
    """The UTC date one scheduled run pulls: yesterday, like the rollup's pass.

    Today is never pulled - it is still accumulating when the nightly job fires,
    exactly the ceiling the rollup planner holds.
    """
    return today - timedelta(days=1)


def build_parser() -> argparse.ArgumentParser:
    """The ``python -m worker.langfuse_metrics`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m worker.langfuse_metrics",
        description="Pull one UTC day of Langfuse metrics into the observability schema.",
    )
    parser.add_argument(
        "--date",
        type=parse_target_date,
        default=None,
        help="pull this UTC date (default: yesterday)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pull for yesterday or ``--date``; ``0`` on success or no-op.

    An unconfigured vendor exits 0 with a log line - the missing-key no-op the
    brief requires. A failed request or a failed write raises out and exits 1,
    so the scheduled run reports it; the operator then re-runs the step with
    ``--date`` for the missed night, which converges on the same row.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(get_settings(), service=SERVICE_LANGFUSE_METRICS)
    settings = get_settings()
    target_date = args.date or default_target_date(datetime.now(tz=UTC).date())

    if not settings.langfuse_public_key:
        logger.info("langfuse keys absent; daily metrics pull skipped for %s", target_date)
        return 0

    async def _execute() -> LangfusePullReport:
        """One engine for the invocation: pull, upsert, dispose."""
        engine = create_async_engine(settings.database_url)
        try:
            return await run_langfuse_daily_pull(
                engine,
                target_date,
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
                timeout_seconds=settings.langfuse_timeout_seconds,
            )
        finally:
            await engine.dispose()

    try:
        report = asyncio.run(_execute())
    except KeyboardInterrupt:
        logger.warning("langfuse daily metrics pull interrupted")
        return 130
    except Exception:
        logger.exception("langfuse daily metrics pull failed for %s", target_date)
        return 1
    if report.written:
        logger.info("langfuse daily metrics landed for %s", report.metric_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
