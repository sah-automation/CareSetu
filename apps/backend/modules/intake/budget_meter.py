"""MOD-005: NFR-001 monthly AI budget meter with a hard stop (PHASE-7 T06 #350).

Concentrates the ``NFR-001`` freemium AI-spend cap into one deep module. The
authoritative monthly spend is the SQL aggregate over the ``intake_ai_jobs``
table for the current calendar month (Postgres-first, per standard B1 - a SQL
counter over a cached/Redis counter; a Redis accelerator may speed reads up but
never overrides the SQL truth). The meter reports spend + remaining against the
configured budget, and fattens an exhausted budget into a hard gate: once the
budget is spent no new AI call may be made - the intake degrades to raw doctor
review (spec #344, standard A4/A5).

The hard stop is enforced as a gate, not a recommendation: :meth:`allows_ai_call`
returns ``False`` the moment the aggregate for the month reaches the budget, so
the AI pipeline consults it before every call and never overspends ``NFR-001``.
The pipeline's job-insertion still records each real call's cost into
``ai_jobs`` (standard A4), and the next aggregate read reflects those rows - so
the meter stays correct purely from what the pipeline writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.intake.schema.models import intake_ai_jobs

# NFR-001 freemium budget expressed in paise: <= Rs 2,000 / month at launch
# scale (project-prd NFR-001, KPI-007). Rs 2,000 = 200,000 paise. Used as the
# boot default when no Settings-level budget is injected, matching how the
# provider/model/timeout knobs carry a code-side default until configured.
DEFAULT_MONTHLY_BUDGET_PAISE = 200_000

# The current calendar-month window, computed in Postgres so the aggregate is
# always the authoritative "this month" spend regardless of app-side clocks
# (standard B1 Postgres-first; the meter never trusts an in-memory counter).
_MONTH_START = text("date_trunc('month', now())")
_NEXT_MONTH_START = text("date_trunc('month', now()) + interval '1 month'")


@dataclass(frozen=True)
class BudgetMeterResult:
    """The current monthly AI-spend state against the configured budget.

    ``spend_paise`` is the authoritative SQL aggregate over ``intake_ai_jobs``
    for the current month; ``remaining_paise`` is what is left before the cap;
    ``exhausted`` is the hard-stop flag - ``True`` exactly when the spend has
    reached the budget, meaning no further AI call is allowed this month
    (standard A4/A5 degradation to raw doctor review).
    """

    spend_paise: int
    budget_paise: int
    remaining_paise: int
    exhausted: bool

    @property
    def allows_ai_call(self) -> bool:
        """Whether a new AI call is permitted - the hard-stop gate.

        ``False`` (blocked) exactly when the budget is exhausted. The pipeline
        consults this before every call (spec #344: "hard stop: budget
        exhausted => no new AI calls").
        """
        return not self.exhausted


class BudgetMeter:
    """NFR-001 monthly AI budget meter: SQL aggregate + hard-stop gate.

    Takes the engine and the configured monthly budget (paise) in its
    constructor, mirroring the directory/deep-module seam convention. Reads the
    authoritative spend from the ``intake_ai_jobs`` SQL aggregate (Postgres
    first, standard B1) - no in-memory counter is authoritative.
    """

    def __init__(self, engine: AsyncEngine, *, monthly_budget_paise: int) -> None:
        self._engine = engine
        if monthly_budget_paise <= 0:
            raise ValueError("monthly_budget_paise must be positive")
        self._monthly_budget_paise = monthly_budget_paise

    async def read_spend_paise(self) -> int:
        """The authoritative current-month AI spend (paise), via SQL aggregate.

        ``COALESCE(SUM(cost_paise), 0)`` over ``intake_ai_jobs`` where the job
        was created in the current calendar month. Rows inserted by the AI
        pipeline (each real/mock call's recorded cost) are reflected in this
        aggregate, so spend tracks exactly what has been metered.
        """
        stmt = select(func.coalesce(func.sum(intake_ai_jobs.c.cost_paise), 0)).where(
            intake_ai_jobs.c.created_at >= _MONTH_START,
            intake_ai_jobs.c.created_at < _NEXT_MONTH_START,
        )
        async with self._engine.begin() as connection:
            spend = int((await connection.execute(stmt)).scalar_one())
        return spend

    async def meter(self) -> BudgetMeterResult:
        """Report monthly spend + remaining against the configured budget.

        Returns the populated :class:`BudgetMeterResult`; an exhausted budget is
        expressed as ``exhausted=True`` (the hard-stop result).
        """
        spend = await self.read_spend_paise()
        remaining = max(0, self._monthly_budget_paise - spend)
        return BudgetMeterResult(
            spend_paise=spend,
            budget_paise=self._monthly_budget_paise,
            remaining_paise=remaining,
            exhausted=spend >= self._monthly_budget_paise,
        )

    async def allows_ai_call(self) -> bool:
        """The hard-stop gate: whether a new AI call is permitted this month.

        ``False`` the moment the monthly SQL aggregate reaches the budget - the
        intake degrades to raw doctor review and no further AI call is made
        (standard A4/A5, spec #344). The gate, not a recommendation.
        """
        return (await self.meter()).allows_ai_call
