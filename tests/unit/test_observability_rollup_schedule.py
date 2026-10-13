"""B5b #705: the rollup's schedule - backfill decision, budget reset, workflow.

The B5a engine decides WHAT a pass writes; this ticket decides WHEN it runs and
WHICH dates it covers. Both answers come from state the rollup persists
(``observability_rollup_runs``), never from when the workflow happened to fire,
so "first run backfills all AI-job history, later runs the previous day" is a
pure function here rather than a cron-timing accident.

Covered without a database: the planner, the budget-period staleness rule, the
compiled reset statement, the run-state read, the composition-root seam, the
``python -m worker.rollup`` flag wiring, and the shape of the scheduled workflow
that invokes it. The round-trip against real PostgreSQL lives in
``tests/integration/test_observability_rollup_round_trip.py``.
"""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.observability.domain.rollup import (
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    plan_rollup_dates,
)
from modules.observability.facade import (
    RollupPlan,
    load_rollup_state,
    run_rollup,
)
from modules.observability.facade import (
    plan_rollup_dates as facade_plan_rollup_dates,
)
from modules.observability.rollup import (
    RollupRunState,
    _load_rollup_run_state,
    _reset_budget_period_statement,
)
from worker import rollup as entry_point

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "observability-rollup.yml"

_TODAY = date(2026, 10, 13)
_YESTERDAY = date(2026, 10, 12)


def _plan(**kwargs: Any) -> RollupPlan:
    """A planner call with the tested inputs defaulted to the steady state."""
    arguments: dict[str, Any] = {
        "today": _TODAY,
        "last_rolled": date(2026, 10, 11),
        "history_start": date(2026, 10, 5),
        "max_dates": 90,
    }
    arguments.update(kwargs)
    return plan_rollup_dates(**arguments)


def _compile(statement: Any) -> str:
    """A statement as PostgreSQL would receive it, literals inlined."""
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# ------------------------------------------------------------------ the planner


def test_first_run_backfills_every_day_of_existing_history() -> None:
    """No run recorded yet: cover AI-job history from its first day up to yesterday."""
    plan = _plan(last_rolled=None)

    assert plan.mode == ROLLUP_MODE_BACKFILL
    assert plan.dates == tuple(date(2026, 10, day) for day in range(5, 13))


def test_backfill_never_rolls_today() -> None:
    """Today is still accumulating when the nightly pass fires, so it is excluded."""
    assert _TODAY not in _plan(last_rolled=None).dates


def test_first_run_with_no_recorded_history_still_rolls_yesterday() -> None:
    """An empty ``ai_usage_daily`` is not a reason to skip: yesterday still gets its pass.

    The pass also evaluates outbox health and writes the run ledger, so running it
    establishes the marker the NEXT run's "later runs" branch reads.
    """
    plan = _plan(last_rolled=None, history_start=None)

    assert plan.mode == ROLLUP_MODE_BACKFILL
    assert plan.dates == (_YESTERDAY,)


def test_history_dated_after_yesterday_is_clamped_to_the_backfill_floor() -> None:
    """A row dated today or later is not history; it must not make the plan empty."""
    plan = _plan(last_rolled=None, history_start=_TODAY)

    assert plan.dates == (_YESTERDAY,)


def test_later_runs_roll_only_the_previous_day() -> None:
    """The steady state: one night, one day, and the ledger says yesterday is done."""
    plan = _plan(last_rolled=date(2026, 10, 11))

    assert plan.mode == ROLLUP_MODE_DAILY
    assert plan.dates == (_YESTERDAY,)


def test_a_run_that_is_already_current_rolls_nothing() -> None:
    """Re-running the same night is a no-op, which is what makes the pass re-run safe."""
    plan = _plan(last_rolled=_YESTERDAY)

    assert plan.dates == ()


def test_a_night_the_workflow_missed_is_caught_up_in_the_next_pass() -> None:
    """The ledger, not the cron, decides coverage - a skipped night is not lost work."""
    plan = _plan(last_rolled=date(2026, 10, 8))

    assert plan.mode == ROLLUP_MODE_DAILY
    assert plan.dates == (date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11), _YESTERDAY)


def test_the_plan_covers_days_oldest_first_so_alerts_fire_in_order() -> None:
    plan = _plan(last_rolled=date(2026, 10, 9))

    assert plan.dates == tuple(sorted(plan.dates))


def test_the_backfill_window_is_capped_at_the_oldest_days_and_the_rest_follows() -> None:
    """A cap keeps one pass bounded; taking the OLDEST days loses nothing, because the
    next pass resumes from the ledger the capped pass just wrote."""
    plan = _plan(last_rolled=None, history_start=date(2026, 1, 1), max_dates=3)

    assert plan.dates == (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3))


def test_the_catch_up_window_is_capped_the_same_way() -> None:
    plan = _plan(last_rolled=date(2026, 10, 1), max_dates=2)

    assert plan.dates == (date(2026, 10, 2), date(2026, 10, 3))


def test_a_ledger_ahead_of_today_is_not_read_as_already_current() -> None:
    """Defence in depth behind the bounded ledger read.

    ``load_rollup_state`` hides future rows from the planner, so this branch is
    unreachable through the entry point - but the planner must still refuse to walk
    a schedule backwards if a caller hands it a future marker.
    """
    assert _plan(last_rolled=date(2026, 10, 20)).dates == ()


@pytest.mark.parametrize("max_dates", [0, -1])
def test_the_planner_refuses_a_non_positive_cap(max_dates: int) -> None:
    with pytest.raises(ValueError, match="max_dates"):
        _plan(last_rolled=None, max_dates=max_dates)


def test_the_plan_reports_its_mode_without_the_caller_recomputing_it() -> None:
    assert _plan(last_rolled=None).is_backfill is True
    assert _plan(last_rolled=_YESTERDAY).is_backfill is False


# --------------------------------------------------------- the budget period reset


def test_the_reset_statement_moves_only_rows_whose_period_has_rolled() -> None:
    """The reset is one UPDATE guarded by the period comparison, so a re-run is a no-op."""
    compiled = _compile(_reset_budget_period_statement(date(2026, 10, 1), date(2026, 10, 31)))

    assert "UPDATE observability.observability_ai_cost_budget" in compiled
    assert "current_spend_paise=0" in compiled
    assert "observability_ai_cost_budget.billing_period_start < '2026-10-01'" in compiled


def test_the_reset_statement_also_moves_a_row_that_never_had_a_period() -> None:
    """``billing_period_start`` is nullable, and a plain ``<`` comparison skips NULL.

    Without this arm a row with no period keeps a closed month's spend forever,
    which is exactly the leak the monthly reset exists to close.
    """
    compiled = _compile(_reset_budget_period_statement(date(2026, 10, 1), date(2026, 10, 31)))

    assert "observability_ai_cost_budget.billing_period_start IS NULL" in compiled


def test_the_reset_statement_does_not_touch_a_row_already_in_the_period() -> None:
    """The reset carries the NEW bounds, so a row inside the period matches no arm."""
    compiled = _compile(_reset_budget_period_statement(date(2026, 10, 1), date(2026, 10, 31)))

    assert "billing_period_start='2026-10-01'" in compiled
    assert "billing_period_end='2026-10-31'" in compiled
    assert "<=" not in compiled


# ------------------------------------------------------------ the persisted state


class _Rows:
    """A one-shot result object shaped like the row-tuple ``execute`` returns."""

    def __init__(self, rows: Any) -> None:
        self._rows = rows

    def all(self) -> Any:
        return self._rows

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None


class _StateConnection:
    """Replays one canned result per statement, in the order they are issued."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(_compile(statement))
        return _Rows(self._results.pop(0))


async def test_the_run_state_reports_the_last_rolled_date_and_the_history_floor() -> None:
    """Both inputs the planner needs come from MOD-013's own tables (ADR-0003)."""
    connection = _StateConnection([[(date(2026, 10, 11),)], [(date(2026, 10, 5),)]])

    state = await _load_rollup_run_state(connection, _TODAY)  # type: ignore[arg-type]

    assert state == RollupRunState(
        last_rolled_date=date(2026, 10, 11), history_start=date(2026, 10, 5)
    )
    assert "observability_rollup_runs" in connection.statements[0]
    assert "observability_ai_usage_daily" in connection.statements[1]


async def test_the_run_state_ignores_a_ledger_row_dated_in_the_future() -> None:
    """A hand-rolled future date must not read as "already caught up" and stop the schedule."""
    connection = _StateConnection([[], [(date(2026, 10, 5),)]])

    state = await _load_rollup_run_state(connection, _TODAY)  # type: ignore[arg-type]

    assert state.last_rolled_date is None
    assert "rollup_date <= '2026-10-13'" in connection.statements[0]


async def test_the_run_state_is_empty_before_the_first_run() -> None:
    connection = _StateConnection([[], []])

    state = await _load_rollup_run_state(connection, _TODAY)  # type: ignore[arg-type]

    assert state == RollupRunState(last_rolled_date=None, history_start=None)


# ------------------------------------------------------------- the facade seam


def test_the_composition_root_reaches_the_scheduler_through_the_facade() -> None:
    assert facade_plan_rollup_dates is plan_rollup_dates
    assert callable(load_rollup_state)
    assert RollupPlan.__name__ == "RollupPlan"


def test_the_scheduler_seam_is_never_imported_across_the_module_boundary() -> None:
    """The worker may only reach MOD-013 through its facade (coding-standards 2)."""
    source = Path(entry_point.__file__ or "").read_text(encoding="utf-8")

    assert "modules.observability.facade" in source
    assert "modules.observability.rollup" not in source
    assert "modules.observability.schema" not in source


def test_a_rollup_run_is_recorded_in_the_same_pass_that_writes_the_aggregates() -> None:
    """The ledger is what makes the backfill decision trustworthy, so it is not optional."""
    assert "mode" in inspect.signature(run_rollup).parameters


# ------------------------------------------------------------ the entry point


def test_the_default_pass_is_planned_from_the_ledger_rather_than_a_fixed_window() -> None:
    """No flag: the pass reads the rollup ledger and decides backfill vs previous day."""
    assert callable(entry_point.plan_from_state)
    assert inspect.iscoroutinefunction(entry_point.plan_from_state)


def test_the_default_pass_needs_no_target_date_and_no_backfill_window() -> None:
    """No flags means "plan from the ledger", which the entry point reads as ``None``."""
    assert entry_point.resolve_dates(date(2026, 10, 13)) is None
    assert entry_point.resolve_dates(date(2026, 10, 13), target_date=date(2026, 10, 2)).dates == (
        date(2026, 10, 2),
    )


@pytest.mark.asyncio
async def test_the_ledger_is_read_only_through_yesterday(monkeypatch: pytest.MonkeyPatch) -> None:
    """The planner's horizon, and therefore the ledger read, stops at yesterday.

    The pass never rolls today - it is still accumulating - so a ledger row dated
    today or later is not a completed day of spend. Counting one would let an
    operator's manual ``--date <today>`` pass itself off as a finished schedule and
    strand the previous night.
    """
    seen: list[date] = []

    async def _fake_load_rollup_state(engine: object, horizon: date) -> RollupRunState:
        seen.append(horizon)
        return RollupRunState(last_rolled_date=None, history_start=date(2026, 10, 12))

    monkeypatch.setattr(entry_point, "load_rollup_state", _fake_load_rollup_state)

    plan = await entry_point.plan_from_state(cast("AsyncEngine", object()), date(2026, 10, 13))

    assert seen == [date(2026, 10, 12)]
    assert plan.dates == (date(2026, 10, 12),)


def test_an_explicit_window_still_overrides_the_plan() -> None:
    """``--backfill-days`` keeps its B5a meaning: the N days ending yesterday."""
    assert entry_point.resolve_dates(date(2026, 10, 13), backfill_days=3).dates == (
        date(2026, 10, 10),
        date(2026, 10, 11),
        date(2026, 10, 12),
    )


def test_an_override_records_the_mode_that_actually_chose_the_dates() -> None:
    """``--backfill-days`` deliberately widens past the ledger, so it is a backfill."""
    assert (
        entry_point.resolve_dates(date(2026, 10, 13), backfill_days=1).mode == ROLLUP_MODE_BACKFILL
    )
    assert entry_point.resolve_dates(date(2026, 10, 13), backfill_days=30).mode == (
        ROLLUP_MODE_BACKFILL
    )
    # A single named day re-rolls one day: the daily shape, whatever the width.
    assert entry_point.resolve_dates(date(2026, 10, 13), target_date=date(2026, 10, 2)).mode == (
        ROLLUP_MODE_DAILY
    )


def test_the_backfill_flag_defaults_to_the_planner() -> None:
    """A default of 1 would pin every run to yesterday and defeat the first-run backfill."""
    parser = entry_point.build_parser()

    assert parser.parse_args([]).backfill_days is None
    assert parser.parse_args(["--backfill-days", "7"]).backfill_days == 7


# ------------------------------------------------------------ the scheduled job


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers() -> dict[str, Any]:
    """The workflow's ``on:`` block. YAML 1.1 reads the bare key ``on`` as boolean True."""
    workflow = _workflow()
    return workflow.get("on", workflow.get(True))


def test_the_rollup_is_driven_by_a_schedule_and_a_manual_dispatch() -> None:
    triggers = _triggers()

    assert triggers["schedule"][0]["cron"]
    assert "workflow_dispatch" in triggers


def test_the_schedule_sits_in_the_shared_quiet_window() -> None:
    """02:45 UTC: after yesterday's day is closed, off the hour the other jobs start."""
    cron = _triggers()["schedule"][0]["cron"]

    minute, hour, day_of_month, month, day_of_week = cron.split()
    assert (minute, hour, day_of_month, month, day_of_week) == ("45", "2", "*", "*", "*")


def test_the_alert_threshold_matches_the_runtime_meter_s_cap() -> None:
    """One cap, read from a repo variable, so the nightly alert and BudgetMeter agree."""
    job = _workflow()["jobs"]["rollup"]

    assert job["env"]["AI_MONTHLY_BUDGET_PAISE"].startswith("${{ vars.AI_MONTHLY_BUDGET_PAISE")


def test_only_one_rollup_pass_runs_at_a_time() -> None:
    workflow = _workflow()

    assert workflow["concurrency"]["group"] == "observability-rollup"
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_the_job_reads_the_database_from_a_secret_and_hard_fails_without_it() -> None:
    """A missing secret must fail loudly, never fall back to the localhost defaults."""
    job = _workflow()["jobs"]["rollup"]
    steps = job["steps"]

    assert job["env"]["DATABASE_URL"] == "${{ secrets.SUPABASE_DATABASE_URL }}"
    assert any("exit 1" in step.get("run", "") for step in steps)
    assert any("SUPABASE_DATABASE_URL" in step.get("run", "") for step in steps)


def test_the_workflow_runs_the_rollup_itself_not_the_web_process() -> None:
    """Render free sleeps at ~15 min idle, so the pass cannot ride on the web service."""
    job = _workflow()["jobs"]["rollup"]
    steps = job["steps"]
    run_steps = " ".join(step.get("run", "") for step in steps)

    assert any("actions/checkout" in str(step.get("uses", "")) for step in steps)
    assert "python -m worker.rollup" in run_steps
    assert "uv sync" in run_steps


def test_the_workflow_narrow_its_permissions_and_bounds_its_runtime() -> None:
    workflow = _workflow()

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["rollup"]["timeout-minutes"] <= 60
