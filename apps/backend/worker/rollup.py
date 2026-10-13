"""Runnable entry point for the MOD-013 nightly rollup (B5a #704).

``python -m worker.rollup`` - the seam B5b's scheduled GitHub Action invokes.
Render free sleeps at 15 minutes idle, so the rollup is deliberately NOT an
in-process cron (plan-phase14 §8): it runs as a one-shot process against the
configured database, exactly like ``python -m worker.main`` runs the dispatcher
as its own process, and keeps the two composition roots independent
(coding-standards §2).

Defaults follow the plan: the pass processes the PREVIOUS UTC day, and
``--backfill-days N`` widens it to the N days ending yesterday (the first run
backfills history, later runs stay on the trailing day). Logging is configured
once with its own service name so rollup lines are separable from the dispatch
loop's, and each rolled date runs inside its own span when tracing is on.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from modules.observability.facade import RollupThresholds, run_rollup
from observability.logging import configure_logging
from observability.otel import start_span

logger = logging.getLogger(__name__)

SERVICE_ROLLUP = "caresetu-rollup"


def parse_target_date(value: str) -> date:
    """Parse a ``--date`` argument, refusing anything that is not ``YYYY-MM-DD``."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--date must be YYYY-MM-DD, got {value!r}") from exc


def resolve_target_dates(today: date, *, backfill_days: int) -> tuple[date, ...]:
    """The UTC dates one invocation rolls, oldest first.

    ``backfill_days`` counts the days ENDING yesterday, so ``1`` (the default) is
    yesterday alone and ``30`` is the trailing month up to yesterday. Today is
    never included: the day is still accumulating when the nightly pass fires.
    """
    if backfill_days < 1:
        raise ValueError("backfill_days must be at least 1")
    yesterday = today - timedelta(days=1)
    return tuple(yesterday - timedelta(days=offset) for offset in reversed(range(backfill_days)))


def build_thresholds(monthly_budget_paise: int | None) -> RollupThresholds:
    """The pass's thresholds, defaulting the budget to the configured monthly cap.

    ``AI_MONTHLY_BUDGET_PAISE`` is the same knob the ``BudgetMeter`` reports
    against, so the alert threshold and the runtime meter read one budget.
    """
    return RollupThresholds(
        monthly_budget_paise=(
            monthly_budget_paise
            if monthly_budget_paise is not None
            else get_settings().ai_monthly_budget_paise
        )
    )


async def _run(dates: Sequence[date], monthly_budget_paise: int | None) -> int:
    """Roll each date in order on one engine; return the number of dates run."""
    settings = get_settings()
    thresholds = build_thresholds(monthly_budget_paise)
    engine = create_async_engine(settings.database_url)
    try:
        for target_date in dates:
            with start_span(
                "scheduler.observability_rollup",
                attributes={"job.name": "observability-rollup", "job.system": "cli"},
            ):
                await run_rollup(engine, target_date, thresholds=thresholds)
    finally:
        await engine.dispose()
    return len(dates)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the rollup for the requested dates; ``0`` on success.

    Non-zero when a date fails or the run is interrupted: the pass raises out of
    the transaction, so the failing date rolls back whole and the operator's
    scheduled run reports the failure instead of a half-written rollup. An
    interrupt (SIGINT / the runner's cancel) exits ``130``, never ``0`` - a
    backfill stopped half way must not read as a clean run.
    """
    parser = argparse.ArgumentParser(
        prog="python -m worker.rollup",
        description="Recompute MOD-013's percentile rollups, budget snapshots and alerts.",
    )
    parser.add_argument(
        "--date",
        type=parse_target_date,
        default=None,
        help="roll this UTC date (default: yesterday)",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=1,
        help="roll the N days ending yesterday (default: 1); ignored when --date is given",
    )
    parser.add_argument(
        "--monthly-budget-paise",
        type=int,
        default=None,
        help="override the configured monthly AI budget used to seed budget rows",
    )
    args = parser.parse_args(argv)

    configure_logging(get_settings(), service=SERVICE_ROLLUP)
    dates: tuple[date, ...]
    if args.date is not None:
        dates = (args.date,)
    else:
        try:
            dates = resolve_target_dates(
                datetime.now(tz=UTC).date(), backfill_days=args.backfill_days
            )
        except ValueError as exc:
            parser.error(str(exc))

    try:
        ran = asyncio.run(_run(dates, args.monthly_budget_paise))
    except KeyboardInterrupt:
        logger.warning("observability rollup interrupted after a partial run")
        return 130
    except Exception:
        logger.exception("observability rollup failed for %s", dates[0])
        return 1
    logger.info("observability rollup completed for %d date(s)", ran)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
