"""Runnable entry point for the MOD-013 nightly rollup (B5a #704, B5b #705).

``python -m worker.rollup`` - the seam the scheduled GitHub Action
(``.github/workflows/observability-rollup.yml``) invokes. Render free sleeps at
15 minutes idle, so the rollup is deliberately NOT an in-process cron
(plan-phase14 §8): it runs as a one-shot process against the configured database,
exactly like ``python -m worker.main`` runs the dispatcher as its own process, and
keeps the two composition roots independent (coding-standards §2).

WHICH dates a pass rolls is decided here from state the rollup persists, never from
when the job fired (B5b). ``observability_rollup_runs`` says what is already
covered: with no run recorded the pass sweeps the whole AI-job history the module
has metered, and afterwards it rolls the previous UTC day. That makes the
plan-phase14 §8 rule a testable function of the database, makes a re-run of the
same night a no-op, and makes a night the workflow missed catch up on the next one
instead of being lost. Today is never rolled - it is still accumulating when the
pass fires.

``--date`` and ``--backfill-days`` override the plan for a manual dispatch
("re-roll this day", "sweep the trailing week"). Logging is configured once with
its own service name so rollup lines are separable from the dispatch loop's, and
each rolled date runs inside its own span when tracing is on.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from modules.observability.facade import (
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    RollupPlan,
    RollupThresholds,
    load_rollup_state,
    plan_rollup_dates,
    run_rollup,
)
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

    ``backfill_days`` counts the days ENDING yesterday, so ``1`` is yesterday alone
    and ``30`` is the trailing month up to yesterday. Today is never included: the
    day is still accumulating when the nightly pass fires. An explicit override -
    see :func:`resolve_dates` for the planned default this sits beside.
    """
    if backfill_days < 1:
        raise ValueError("backfill_days must be at least 1")
    yesterday = today - timedelta(days=1)
    return tuple(yesterday - timedelta(days=offset) for offset in reversed(range(backfill_days)))


def resolve_dates(
    today: date, *, target_date: date | None = None, backfill_days: int | None = None
) -> RollupPlan | None:
    """The dates an explicit flag asked for, or ``None`` to run the planner instead.

    Returning ``None`` rather than a default window is what lets the flags stay
    honest: a fixed default of one day would silently pin every run to yesterday and
    defeat the first-run backfill.

    The mode travels with the dates so the ledger records what actually happened:
    ``--date`` re-rolls one day, which is the daily shape; ``--backfill-days``
    deliberately widens past whatever the ledger covers, which is the backfill
    shape whatever the width.
    """
    if target_date is not None:
        return RollupPlan(
            mode=ROLLUP_MODE_DAILY,
            dates=(target_date,),
            last_rolled=None,
            history_start=None,
        )
    if backfill_days is not None:
        return RollupPlan(
            mode=ROLLUP_MODE_BACKFILL,
            dates=resolve_target_dates(today, backfill_days=backfill_days),
            last_rolled=None,
            history_start=None,
        )
    return None


async def plan_from_state(engine: AsyncEngine, today: date) -> RollupPlan:
    """Read the rollup ledger and plan this invocation's dates from it.

    The read is bounded by YESTERDAY, because that is the latest day the planner can
    ever plan. Today is still accumulating, so a ledger row dated today - or any date
    in the future, from an operator's ``--date`` - must not make the schedule look
    already-current and quietly switch the nightly off. Yesterday's row is still
    authoritative, so a same-day manual run is re-rolled with complete data.
    """
    state = await load_rollup_state(engine, today - timedelta(days=1))
    return plan_rollup_dates(
        today=today,
        last_rolled=state.last_rolled_date,
        history_start=state.history_start,
        max_dates=get_settings().observability_rollup_max_dates,
    )


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


async def _run(engine: AsyncEngine, plan: RollupPlan, monthly_budget_paise: int | None) -> int:
    """Roll each planned date in order on one engine; return the number of dates run."""
    thresholds = build_thresholds(monthly_budget_paise)
    for target_date in plan.dates:
        with start_span(
            "scheduler.observability_rollup",
            attributes={
                "job.name": "observability-rollup",
                "job.system": "cli",
                "rollup.mode": plan.mode,
            },
        ):
            await run_rollup(engine, target_date, thresholds=thresholds, mode=plan.mode)
    return len(plan.dates)


def build_parser() -> argparse.ArgumentParser:
    """The ``python -m worker.rollup`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m worker.rollup",
        description="Recompute MOD-013's percentile rollups, budget snapshots and alerts.",
    )
    parser.add_argument(
        "--date",
        type=parse_target_date,
        default=None,
        help="roll this UTC date (default: plan from the rollup ledger)",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=None,
        help="roll the N days ending yesterday, ignoring the plan; ignored when --date is given",
    )
    parser.add_argument(
        "--monthly-budget-paise",
        type=int,
        default=None,
        help="override the configured monthly AI budget used to seed budget rows",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the rollup for the planned or requested dates; ``0`` on success.

    Non-zero when a date fails or the run is interrupted: the pass raises out of
    the transaction, so the failing date rolls back whole - including its ledger
    row - and the operator's scheduled run reports the failure instead of a
    half-written rollup. An interrupt (SIGINT / the runner's cancel) exits ``130``,
    never ``0``: a backfill stopped half way must not read as a clean run.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(get_settings(), service=SERVICE_ROLLUP)
    today = datetime.now(tz=UTC).date()
    settings = get_settings()
    # The operator reads the failure log first, so the failing range is named there.
    planned: list[tuple[date, ...]] = []

    async def _execute() -> int:
        """One engine for the whole invocation: plan, roll, dispose."""
        engine = create_async_engine(settings.database_url)
        try:
            plan = resolve_dates(
                today, target_date=args.date, backfill_days=args.backfill_days
            ) or await plan_from_state(engine, today)
            planned.append(plan.dates)
            if not plan.dates:
                logger.info(
                    "observability rollup has nothing to do: already rolled through %s",
                    plan.last_rolled,
                )
                return 0
            logger.info(
                "observability rollup planned %d date(s) in %s mode: %s..%s",
                len(plan.dates),
                plan.mode,
                plan.dates[0],
                plan.dates[-1],
            )
            return await _run(engine, plan, args.monthly_budget_paise)
        finally:
            await engine.dispose()

    try:
        ran = asyncio.run(_execute())
    except KeyboardInterrupt:
        logger.warning("observability rollup interrupted after a partial run")
        return 130
    except Exception:
        dates = planned[0] if planned else ()
        logger.exception(
            "observability rollup failed over %s",
            f"{dates[0]}..{dates[-1]}" if dates else "an unplanned range",
        )
        return 1
    logger.info("observability rollup completed for %d date(s)", ran)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
